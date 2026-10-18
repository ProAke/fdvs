"""
FDVS — Folder VS compare engine.

Scans two directory trees and produces a deterministic, machine-readable
comparison report. Pure stdlib, no third-party dependencies.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
from typing import Any, Callable, Iterable

__all__ = [
    "DEFAULT_IGNORES",
    "DEFAULT_IGNORE_GLOBS",
    "walk_tree",
    "compare_trees",
    "hash_file",
]

# macOS / Windows metadata noise that should never count as a difference.
DEFAULT_IGNORES = {
    ".DS_Store",
    ".Spotlight-V100",
    ".Trashes",
    ".fseventsd",
    ".TemporaryItems",
    ".DocumentRevisions-V100",
    ".apdisk",
    "Thumbs.db",
    "desktop.ini",
    "$RECYCLE.BIN",
    "System Volume Information",
    ".fdvs-backup",
}

DEFAULT_IGNORE_GLOBS = ["*.swp", "*~", ".~*"]

HASH_CHUNK = 1024 * 1024


def hash_file(path: str, chunk: int = HASH_CHUNK) -> str:
    """SHA-256 of a file, streamed. Returns '' when unreadable."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            while True:
                block = fh.read(chunk)
                if not block:
                    break
                h.update(block)
    except OSError:
        return ""
    return h.hexdigest()


def _rel(root: str, path: str) -> str:
    rel = os.path.relpath(path, root)
    return rel.replace(os.sep, "/")


def _skipped(name: str, ignore_names: set[str], ignore_globs: list[str]) -> bool:
    if name in ignore_names:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in ignore_globs)


def walk_tree(
    root: str,
    ignore_names: Iterable[str] = DEFAULT_IGNORES,
    ignore_globs: Iterable[str] = DEFAULT_IGNORE_GLOBS,
    follow_symlinks: bool = False,
    progress: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    """
    Walk ``root`` and return::

        {"root", "files": {rel: entry}, "dirs": {rel: entry},
         "errors": [...], "file_count", "dir_count", "total_bytes", "skipped"}

    Each file entry: {"size", "mtime", "mode", "type", "target"?}
    ``type`` is one of "file", "symlink", "other".
    """
    ignore_names = set(ignore_names)
    ignore_globs = list(ignore_globs)

    root = os.path.abspath(os.path.expanduser(root))
    files: dict[str, dict] = {}
    dirs: dict[str, dict] = {}
    errors: list[dict] = []
    skipped = 0
    total_bytes = 0
    scanned = 0

    if not os.path.isdir(root):
        return {
            "root": root,
            "files": {},
            "dirs": {},
            "errors": [{"path": root, "error": "not a directory or not readable"}],
            "file_count": 0,
            "dir_count": 0,
            "total_bytes": 0,
            "skipped": 0,
            "exists": False,
        }

    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            errors.append({"path": _rel(root, current) or ".", "error": f"{exc.strerror or exc}"})
            continue

        for entry in entries:
            if _skipped(entry.name, ignore_names, ignore_globs):
                skipped += 1
                continue
            rel = _rel(root, entry.path)
            try:
                is_link = entry.is_symlink()
                if entry.is_dir(follow_symlinks=False):
                    try:
                        st = entry.stat(follow_symlinks=False)
                        dirs[rel] = {"mtime": st.st_mtime, "type": "dir"}
                    except OSError:
                        dirs[rel] = {"mtime": 0, "type": "dir"}
                    if not is_link or follow_symlinks:
                        stack.append(entry.path)
                elif is_link:
                    target = ""
                    try:
                        target = os.readlink(entry.path)
                    except OSError:
                        pass
                    lst = os.lstat(entry.path)
                    files[rel] = {
                        "size": 0,
                        "mtime": lst.st_mtime,
                        "mode": stat.S_IMODE(lst.st_mode),
                        "type": "symlink",
                        "target": target,
                    }
                elif entry.is_file(follow_symlinks=False):
                    st = entry.stat(follow_symlinks=False)
                    files[rel] = {
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                        "mode": stat.S_IMODE(st.st_mode),
                        "type": "file",
                    }
                    total_bytes += st.st_size
                else:
                    lst = os.lstat(entry.path)
                    files[rel] = {
                        "size": 0,
                        "mtime": lst.st_mtime,
                        "mode": stat.S_IMODE(lst.st_mode),
                        "type": "other",
                    }
            except OSError as exc:
                errors.append({"path": rel, "error": f"{exc.strerror or exc}"})

            scanned += 1
            if progress and scanned % 400 == 0:
                progress({"scanned": scanned, "files": len(files), "current": rel})

    if progress:
        progress({"scanned": scanned, "files": len(files), "current": ""})

    return {
        "root": root,
        "files": files,
        "dirs": dirs,
        "errors": errors,
        "file_count": len(files),
        "dir_count": len(dirs),
        "total_bytes": total_bytes,
        "skipped": skipped,
        "exists": True,
    }


def _diff_reasons(left: dict, right: dict, mtime_tolerance: float) -> list[str]:
    reasons: list[str] = []
    if left.get("type") != right.get("type"):
        reasons.append("type")
    if left.get("size") != right.get("size"):
        reasons.append("size")
    if left.get("type") == "symlink" and left.get("target") != right.get("target"):
        reasons.append("symlink")
    if mtime_tolerance >= 0:
        if abs(left.get("mtime", 0) - right.get("mtime", 0)) > mtime_tolerance:
            reasons.append("mtime")
    return reasons


def compare_trees(
    left_root: str,
    right_root: str,
    *,
    hash_mode: str = "auto",
    compare_mtime: bool = True,
    mtime_tolerance: float = 2.0,
    ignore_names: Iterable[str] = DEFAULT_IGNORES,
    ignore_globs: Iterable[str] = DEFAULT_IGNORE_GLOBS,
    follow_symlinks: bool = False,
    progress: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    """
    Compare two trees.

    hash_mode:
      "none"  — size + mtime only (fastest)
      "auto"  — hash only when size matches but mtime differs (default)
      "all"   — hash every file that exists on both sides (slowest, exact)

    Statuses per item:
      same | size_differs | content_differs | mtime_differs | type_differs |
      left_only | right_only | symlink_differs
    """

    def left_progress(p: dict) -> None:
        if progress:
            progress({"phase": "scan-left", **p})

    def right_progress(p: dict) -> None:
        if progress:
            progress({"phase": "scan-right", **p})

    left = walk_tree(
        left_root,
        ignore_names=ignore_names,
        ignore_globs=ignore_globs,
        follow_symlinks=follow_symlinks,
        progress=left_progress,
    )
    right = walk_tree(
        right_root,
        ignore_names=ignore_names,
        ignore_globs=ignore_globs,
        follow_symlinks=follow_symlinks,
        progress=right_progress,
    )

    if progress:
        progress({"phase": "compare", "current": ""})

    all_paths = sorted(set(left["files"]) | set(right["files"]))
    items: list[dict] = []
    counts = {
        "same": 0,
        "size_differs": 0,
        "content_differs": 0,
        "mtime_differs": 0,
        "type_differs": 0,
        "symlink_differs": 0,
        "left_only": 0,
        "right_only": 0,
    }
    same_bytes = 0
    diff_bytes_left = 0
    diff_bytes_right = 0

    for rel in all_paths:
        lf = left["files"].get(rel)
        rf = right["files"].get(rel)

        if lf and not rf:
            status = "left_only"
            entry = {"relpath": rel, "status": status, "left": lf, "right": None, "reasons": ["missing-right"]}
            diff_bytes_left += lf.get("size", 0)
        elif rf and not lf:
            status = "right_only"
            entry = {"relpath": rel, "status": status, "left": None, "right": rf, "reasons": ["missing-left"]}
            diff_bytes_right += rf.get("size", 0)
        else:
            reasons = _diff_reasons(lf, rf, mtime_tolerance if compare_mtime else -1)
            hashed = False
            if hash_mode != "none" and lf.get("type") == "file" and rf.get("type") == "file":
                need_hash = hash_mode == "all" or (hash_mode == "auto" and "mtime" in reasons and "size" not in reasons)
                if need_hash:
                    lh = hash_file(os.path.join(left["root"], rel))
                    rh = hash_file(os.path.join(right["root"], rel))
                    hashed = True
                    lf = {**lf, "sha256": lh}
                    rf = {**rf, "sha256": rh}
                    if lh and rh and lh == rh:
                        reasons = [r for r in reasons if r != "mtime"]
                    elif lh and rh:
                        reasons = [r for r in reasons if r not in ("size", "mtime")] + ["content"]

            if not reasons:
                status = "same"
                same_bytes += lf.get("size", 0)
            elif "content" in reasons:
                status = "content_differs"
            elif "size" in reasons:
                status = "size_differs"
            elif "type" in reasons:
                status = "type_differs"
            elif "symlink" in reasons:
                status = "symlink_differs"
            else:
                status = "mtime_differs"

            if status != "same":
                diff_bytes_left += lf.get("size", 0)
                diff_bytes_right += rf.get("size", 0)

            entry = {
                "relpath": rel,
                "status": status,
                "left": lf,
                "right": rf,
                "reasons": reasons,
                "hashed": hashed,
            }

        counts[status] += 1
        items.append(entry)

    dirs_only_left = sorted(set(left["dirs"]) - set(right["dirs"]))
    dirs_only_right = sorted(set(right["dirs"]) - set(left["dirs"]))
    dirs_both = sorted(set(left["dirs"]) & set(right["dirs"]))

    equal_count = counts["same"]
    different_count = len(items) - equal_count
    sizes_equal = left["total_bytes"] == right["total_bytes"]
    identical = different_count == 0 and not dirs_only_left and not dirs_only_right

    return {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "options": {
            "hash_mode": hash_mode,
            "compare_mtime": compare_mtime,
            "mtime_tolerance": mtime_tolerance,
            "follow_symlinks": follow_symlinks,
        },
        "left": {k: v for k, v in left.items() if k not in ("files", "dirs")},
        "right": {k: v for k, v in right.items() if k not in ("files", "dirs")},
        "summary": {
            "total_items": len(items),
            "same": counts["same"],
            "different": different_count,
            "left_only": counts["left_only"],
            "right_only": counts["right_only"],
            "size_differs": counts["size_differs"],
            "content_differs": counts["content_differs"],
            "mtime_differs": counts["mtime_differs"],
            "type_differs": counts["type_differs"],
            "symlink_differs": counts["symlink_differs"],
            "dirs_only_left": len(dirs_only_left),
            "dirs_only_right": len(dirs_only_right),
            "dirs_common": len(dirs_both),
            "same_bytes": same_bytes,
            "left_total_bytes": left["total_bytes"],
            "right_total_bytes": right["total_bytes"],
            "left_file_count": left["file_count"],
            "right_file_count": right["file_count"],
            "left_dir_count": left["dir_count"],
            "right_dir_count": right["dir_count"],
            "sizes_equal": sizes_equal,
            "identical": identical,
            "left_errors": len(left["errors"]),
            "right_errors": len(right["errors"]),
        },
        "items": items,
        "dirs_only_left": dirs_only_left,
        "dirs_only_right": dirs_only_right,
        "left_errors": left["errors"],
        "right_errors": right["errors"],
    }
