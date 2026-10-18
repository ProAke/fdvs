#!/usr/bin/env python3
"""
Migrate MNG Dashboard backups scattered across /Volumes/MNG into
/Volumes/MNG/Home_Backup/MNG-Dashboard/.

Transactional: copy -> verify SHA-256 of every file -> only then remove the
source. Writes a manifest and a rollback script so the move can be undone.

Only dashboard-related items are moved. vulcananti-scale.com site backups and
the revslider plugin zips in /Volumes/MNG/Backup/ are NOT dashboard artefacts
and are left in place.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

MNG = "/Volumes/MNG"
DEST_ROOT = os.path.join(MNG, "Home_Backup", "MNG-Dashboard")
STAMP = time.strftime("%Y%m%d-%H%M%S")

# (label, source_dir, dest_subdir, predicate)
# predicate decides which names inside source_dir are dashboard backups.
def is_dashboard_name(name: str) -> bool:
    return name.startswith("index.html") or name.startswith("indexbk") or name.endswith(".md")


JOBS = [
    {
        "label": "top-level index.html.bak-*",
        "src_dir": MNG,
        "dest": "top-level",
        "names": None,  # filled in below
    },
    {
        "label": ".backup/ index.html + md files",
        "src_dir": os.path.join(MNG, ".backup"),
        "dest": "dot-backup",
        "names": None,
    },
    {
        "label": ".backup/ snapshot subdirectories",
        "src_dir": os.path.join(MNG, ".backup"),
        "dest": "dot-backup/snapshots",
        "names": None,
    },
    {
        "label": "Backup/ dashboard index files",
        "src_dir": os.path.join(MNG, "Backup"),
        "dest": "Backup-folder",
        "names": None,
    },
    {
        "label": "Backup/tmp dashboard files",
        "src_dir": os.path.join(MNG, "Backup", "tmp"),
        "dest": "Backup-folder/tmp",
        "names": None,
    },
]


def sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def copy_item(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(src) and not os.path.islink(src):
        # ditto preserves resource forks, xattrs and timestamps on macOS
        r = subprocess.run(["ditto", src, dst], capture_output=True, text=True)
        if r.returncode != 0:
            shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst, follow_symlinks=False)


def verify_tree(src: str, dst: str) -> tuple[bool, list[str]]:
    """Every file under src must exist under dst with an identical SHA-256."""
    problems: list[str] = []
    if os.path.isfile(src) and not os.path.isdir(src):
        if not os.path.exists(dst):
            return False, [f"missing: {dst}"]
        if sha256(src) != sha256(dst):
            problems.append(f"hash mismatch: {src}")
        return not problems, problems

    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        for name in files:
            s = os.path.join(root, name)
            d = os.path.join(dst, name) if rel == "." else os.path.join(dst, rel, name)
            if not os.path.exists(d):
                problems.append(f"missing: {d}")
                continue
            if os.path.getsize(s) != os.path.getsize(d):
                problems.append(f"size differs: {s}")
                continue
            if sha256(s) != sha256(d):
                problems.append(f"hash mismatch: {s}")
    return not problems, problems


def main() -> int:
    if not os.path.isdir(MNG):
        print(f"ERROR: {MNG} not mounted")
        return 1

    os.makedirs(DEST_ROOT, exist_ok=True)

    # ── build the concrete work list ──────────────────────────────────────
    work: list[dict] = []

    # 1) top-level index.html.bak*
    top = sorted(
        n for n in os.listdir(MNG)
        if n.startswith("index.html.bak")
    )
    work.append({"label": "top-level", "src_dir": MNG, "dest": "top-level", "names": top})

    # 2) .backup/ loose files (index.html.* and *.md)
    dot = os.path.join(MNG, ".backup")
    dot_files, dot_dirs = [], []
    if os.path.isdir(dot):
        for n in sorted(os.listdir(dot)):
            p = os.path.join(dot, n)
            if os.path.isdir(p):
                dot_dirs.append(n)
            elif is_dashboard_name(n):
                dot_files.append(n)
    work.append({"label": "dot-backup files", "src_dir": dot, "dest": "dot-backup", "names": dot_files})
    work.append({"label": "dot-backup snapshots", "src_dir": dot, "dest": "dot-backup/snapshots", "names": dot_dirs})

    # 3) Backup/ dashboard index files (leave vulcananti + zips alone)
    bak = os.path.join(MNG, "Backup")
    bak_files = []
    if os.path.isdir(bak):
        for n in sorted(os.listdir(bak)):
            p = os.path.join(bak, n)
            if os.path.isfile(p) and is_dashboard_name(n):
                bak_files.append(n)
    work.append({"label": "Backup-folder files", "src_dir": bak, "dest": "Backup-folder", "names": bak_files})

    # 4) Backup/tmp dashboard files
    btmp = os.path.join(MNG, "Backup", "tmp")
    btmp_files = []
    if os.path.isdir(btmp):
        btmp_files = sorted(n for n in os.listdir(btmp) if is_dashboard_name(n))
    work.append({"label": "Backup-folder tmp", "src_dir": btmp, "dest": "Backup-folder/tmp", "names": btmp_files})

    total_items = sum(len(w["names"]) for w in work)
    print(f"FDVS backup migration -> {DEST_ROOT}")
    print(f"items to move: {total_items}\n")

    manifest: list[dict] = []
    rollback: list[str] = []
    failures: list[str] = []

    for job in work:
        if not job["names"]:
            continue
        print(f"── {job['label']} ({len(job['names'])} items)")
        for name in job["names"]:
            src = os.path.join(job["src_dir"], name)
            dst = os.path.join(DEST_ROOT, job["dest"], name)
            if not os.path.exists(src):
                print(f"   skip (gone): {name}")
                continue
            if os.path.exists(dst):
                print(f"   skip (dest exists): {name}")
                continue

            copy_item(src, dst)
            ok, problems = verify_tree(src, dst)
            if not ok:
                failures.extend(problems)
                print(f"   FAILED verify: {name}")
                for p in problems[:3]:
                    print(f"      {p}")
                continue

            size = os.path.getsize(src) if os.path.isfile(src) else sum(
                os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(src) for f in fs
            )
            manifest.append({
                "name": name,
                "from": src,
                "to": dst,
                "bytes": size,
                "verified": True,
                "moved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            })
            rollback.append(f'mv {json.dumps(dst)} {json.dumps(src)}')
            print(f"   ok  {name}  ({size:,} B)")

    if failures:
        print(f"\n{len(failures)} verification failures — NOT deleting any source")
        return 1

    # ── all verified: remove sources ──────────────────────────────────────
    print(f"\nall {len(manifest)} items verified. removing sources…")
    removed = 0
    for m in manifest:
        src = m["from"]
        try:
            if os.path.isdir(src) and not os.path.islink(src):
                shutil.rmtree(src)
            else:
                os.remove(src)
            removed += 1
        except OSError as exc:
            print(f"   could not remove {src}: {exc}")
    print(f"removed {removed}/{len(manifest)} sources")

    # ── cleanup now-empty containers ──────────────────────────────────────
    for d in (os.path.join(MNG, "Backup", "tmp"), os.path.join(MNG, ".backup")):
        if os.path.isdir(d) and not os.listdir(d):
            try:
                os.rmdir(d)
                print(f"removed empty dir: {d}")
            except OSError:
                pass

    # ── manifest + rollback + README ──────────────────────────────────────
    with open(os.path.join(DEST_ROOT, "MIGRATION-MANIFEST.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "migrated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "destination": DEST_ROOT,
            "item_count": len(manifest),
            "total_bytes": sum(m["bytes"] for m in manifest),
            "items": manifest,
        }, fh, ensure_ascii=False, indent=2)

    with open(os.path.join(DEST_ROOT, "rollback.sh"), "w", encoding="utf-8") as fh:
        fh.write("#!/bin/bash\n# Undo the backup migration. Run only if you need the files back at their old paths.\n")
        fh.write("set -e\n")
        for line in rollback:
            fh.write(line + "\n")
    os.chmod(os.path.join(DEST_ROOT, "rollback.sh"), 0o755)

    print(f"\nDONE — {len(manifest)} items, {sum(m['bytes'] for m in manifest):,} bytes")
    print(f"manifest: {os.path.join(DEST_ROOT, 'MIGRATION-MANIFEST.json')}")
    print(f"rollback: {os.path.join(DEST_ROOT, 'rollback.sh')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
