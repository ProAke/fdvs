"""
FDVS — sync planner / executor.

Builds a copy plan from a comparison report and executes it transactionally:
copy to a temp file in the destination directory, verify SHA-256, then rename
into place. Overwritten files are optionally backed up first.
"""

from __future__ import annotations

import os
import shutil
import time
from typing import Any, Callable

from .compare import hash_file

__all__ = ["plan_sync", "execute_plan", "PlanError"]

COPY_STATUSES = {
    "left_only",
    "right_only",
    "size_differs",
    "content_differs",
    "mtime_differs",
    "type_differs",
    "symlink_differs",
}


class PlanError(RuntimeError):
    pass


def _safe_join(root: str, rel: str) -> str:
    """Join and refuse to escape ``root``."""
    root_abs = os.path.abspath(root)
    target = os.path.abspath(os.path.join(root_abs, rel))
    if target != root_abs and not target.startswith(root_abs + os.sep):
        raise PlanError(f"path escapes root: {rel}")
    return target


def plan_sync(
    report: dict,
    direction: str,
    *,
    delete_extras: bool = False,
    statuses: list[str] | None = None,
) -> dict[str, Any]:
    """
    Build the operations needed to make both trees equal.

    direction: "left_to_right" | "right_to_left" | "bidirectional"
      - left_to_right : right side is made to match left (default mirror)
      - right_to_left : left side is made to match right
      - bidirectional : copy each side's unique files to the other; files that
        exist on both sides but differ are resolved by ``newer_wins``

    delete_extras is destructive and OFF by default; when enabled the target
    side's extra files are removed so it becomes an exact mirror.
    """
    if direction not in ("left_to_right", "right_to_left", "bidirectional"):
        raise PlanError(f"unknown direction: {direction}")

    left_root = report["left"]["root"]
    right_root = report["right"]["root"]
    wanted = set(statuses) if statuses else None

    ops: list[dict] = []
    skipped: list[dict] = []

    def add_copy(rel: str, src_root: str, dst_root: str, src_entry: dict, dst_entry: dict | None, why: str):
        if src_entry.get("type") == "symlink":
            ops.append(
                {
                    "action": "symlink",
                    "relpath": rel,
                    "src": _safe_join(src_root, rel),
                    "dst": _safe_join(dst_root, rel),
                    "target": src_entry.get("target", ""),
                    "bytes": 0,
                    "reason": why,
                }
            )
            return
        ops.append(
            {
                "action": "copy",
                "relpath": rel,
                "src": _safe_join(src_root, rel),
                "dst": _safe_join(dst_root, rel),
                "bytes": int(src_entry.get("size", 0)),
                "reason": why,
                "overwrite": dst_entry is not None,
            }
        )

    def add_delete(rel: str, root: str, entry: dict, why: str):
        ops.append(
            {
                "action": "delete",
                "relpath": rel,
                "src": None,
                "dst": _safe_join(root, rel),
                "bytes": int(entry.get("size", 0)),
                "reason": why,
            }
        )

    for item in report["items"]:
        rel = item["relpath"]
        status = item["status"]
        if status == "same":
            continue
        if wanted is not None and status not in wanted:
            skipped.append({"relpath": rel, "status": status, "why": "filtered out"})
            continue
        if status not in COPY_STATUSES:
            skipped.append({"relpath": rel, "status": status, "why": "unsupported status"})
            continue

        lf, rf = item.get("left"), item.get("right")

        if direction == "left_to_right":
            if status == "right_only":
                if delete_extras:
                    add_delete(rel, right_root, rf, "extra on right")
                else:
                    skipped.append({"relpath": rel, "status": status, "why": "extra file kept (delete disabled)"})
            else:
                add_copy(rel, left_root, right_root, lf, rf, status)

        elif direction == "right_to_left":
            if status == "left_only":
                if delete_extras:
                    add_delete(rel, left_root, lf, "extra on left")
                else:
                    skipped.append({"relpath": rel, "status": status, "why": "extra file kept (delete disabled)"})
            else:
                add_copy(rel, right_root, left_root, rf, lf, status)

        else:  # bidirectional
            if status == "left_only":
                add_copy(rel, left_root, right_root, lf, None, "unique to left")
            elif status == "right_only":
                add_copy(rel, right_root, left_root, rf, None, "unique to right")
            else:
                newer = "left" if (lf or {}).get("mtime", 0) >= (rf or {}).get("mtime", 0) else "right"
                if newer == "left":
                    add_copy(rel, left_root, right_root, lf, rf, f"newer on left ({status})")
                else:
                    add_copy(rel, right_root, left_root, rf, lf, f"newer on right ({status})")

    # Directories that exist only on the source side must exist on the target.
    dir_ops: list[dict] = []
    if direction in ("left_to_right", "bidirectional"):
        for rel in report.get("dirs_only_left", []):
            dir_ops.append({"action": "mkdir", "relpath": rel, "dst": _safe_join(right_root, rel), "reason": "dir only on left"})
    if direction in ("right_to_left", "bidirectional"):
        for rel in report.get("dirs_only_right", []):
            dir_ops.append({"action": "mkdir", "relpath": rel, "dst": _safe_join(left_root, rel), "reason": "dir only on right"})

    total_bytes = sum(o["bytes"] for o in ops if o["action"] in ("copy", "delete"))
    return {
        "direction": direction,
        "delete_extras": delete_extras,
        "left_root": left_root,
        "right_root": right_root,
        "ops": dir_ops + ops,
        "skipped": skipped,
        "summary": {
            "total_ops": len(dir_ops) + len(ops),
            "copies": sum(1 for o in ops if o["action"] == "copy"),
            "symlinks": sum(1 for o in ops if o["action"] == "symlink"),
            "deletes": sum(1 for o in ops if o["action"] == "delete"),
            "mkdirs": len(dir_ops),
            "bytes_to_copy": sum(o["bytes"] for o in ops if o["action"] == "copy"),
            "bytes_to_delete": sum(o["bytes"] for o in ops if o["action"] == "delete"),
            "total_bytes": total_bytes,
            "skipped": len(skipped),
        },
    }


def execute_plan(
    plan: dict,
    *,
    dry_run: bool = True,
    verify: bool = True,
    backup: bool = True,
    backup_dir: str | None = None,
    progress: Callable[[dict], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """
    Execute a plan produced by :func:`plan_sync`.

    Each copy goes to ``<dst>.fdvs-tmp-<pid>`` first, is SHA-256 verified
    against the source, then is atomically renamed onto the destination.
    """
    ops = plan.get("ops", [])
    results: list[dict] = []
    copied = 0
    deleted = 0
    failed = 0
    copied_bytes = 0
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_root = backup_dir or os.path.join(
        os.path.dirname(plan.get("right_root") or "."), f".fdvs-backup-{stamp}"
    )

    for index, op in enumerate(ops, 1):
        if should_stop and should_stop():
            results.append({"action": op.get("action"), "relpath": op.get("relpath"), "ok": False, "error": "cancelled"})
            failed += 1
            break

        action = op.get("action")
        rel = op.get("relpath")
        record = {"action": action, "relpath": rel, "ok": True, "error": None, "bytes": op.get("bytes", 0)}

        try:
            if action == "mkdir":
                if not dry_run:
                    os.makedirs(op["dst"], exist_ok=True)
                record["detail"] = "created" if not dry_run else "would create"

            elif action == "copy":
                src, dst = op["src"], op["dst"]
                if not os.path.exists(src):
                    raise PlanError(f"source missing: {src}")
                if not dry_run:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    if backup and os.path.exists(dst):
                        rel_dir = os.path.dirname(rel)
                        bdst = os.path.join(backup_root, rel_dir) if rel_dir else backup_root
                        os.makedirs(bdst, exist_ok=True)
                        shutil.copy2(dst, os.path.join(bdst, os.path.basename(dst)))
                        record["backup"] = os.path.join(bdst, os.path.basename(dst))

                    tmp = f"{dst}.fdvs-tmp-{os.getpid()}"
                    shutil.copy2(src, tmp)
                    if verify:
                        src_hash = hash_file(src)
                        dst_hash = hash_file(tmp)
                        if not src_hash or src_hash != dst_hash:
                            os.remove(tmp)
                            raise PlanError("checksum mismatch after copy")
                        record["sha256"] = src_hash
                    os.replace(tmp, dst)
                    copied += 1
                    copied_bytes += op.get("bytes", 0)
                record["detail"] = "copied" if not dry_run else "would copy"

            elif action == "symlink":
                if not dry_run:
                    os.makedirs(os.path.dirname(op["dst"]), exist_ok=True)
                    if os.path.lexists(op["dst"]):
                        os.remove(op["dst"])
                    os.symlink(op["target"], op["dst"])
                record["detail"] = "linked" if not dry_run else "would link"

            elif action == "delete":
                dst = op["dst"]
                if not dry_run:
                    if backup and os.path.exists(dst):
                        os.makedirs(backup_root, exist_ok=True)
                        shutil.copy2(dst, os.path.join(backup_root, os.path.basename(dst)))
                    if os.path.isdir(dst) and not os.path.islink(dst):
                        shutil.rmtree(dst)
                    else:
                        os.remove(dst)
                    deleted += 1
                record["detail"] = "deleted" if not dry_run else "would delete"

            else:
                record["ok"] = False
                record["error"] = f"unknown action: {action}"
                failed += 1

        except Exception as exc:  # noqa: BLE001 - reported, not raised
            record["ok"] = False
            record["error"] = f"{type(exc).__name__}: {exc}"
            failed += 1

        results.append(record)
        if progress:
            progress(
                {
                    "index": index,
                    "total": len(ops),
                    "current": rel,
                    "copied": copied,
                    "deleted": deleted,
                    "failed": failed,
                }
            )

    return {
        "dry_run": dry_run,
        "verify": verify,
        "backup": backup,
        "backup_root": backup_root if (backup and not dry_run) else None,
        "summary": {
            "total": len(ops),
            "copied": copied,
            "deleted": deleted,
            "failed": failed,
            "copied_bytes": copied_bytes,
            "ok": failed == 0,
        },
        "results": results,
    }
