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
import time
from typing import Any, Callable, Iterable

__all__ = [
    "DEFAULT_IGNORES",
    "DEFAULT_IGNORE_GLOBS",
    "walk_tree",
    "compare_trees",
    "hash_file",
    "estimate_tree",
    "estimate_scan",
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

# Measured lazily on real data; used only for the pre-scan time estimate.
_HASH_RATE_CACHE: dict[str, float] = {}
_HASH_RATE_FALLBACK = 400 * 1024 * 1024  # bytes/sec, conservative SSD figure

# Walk throughput varies enormously by volume (SSD vs external USB vs network).
# Measured on this machine: /Volumes/MNG (external) ≈ 3,000 entries/sec.
# We self-calibrate from every real walk instead of trusting a constant.
_WALK_RATE_CACHE: dict[str, float] = {}
_WALK_RATE_FALLBACK = 8_000  # entries/sec, conservative external-volume figure


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


def _measure_hash_rate(root: str, sample_bytes: int = 64 * 1024 * 1024) -> float:
    """
    Measure real hashing throughput on ``root`` so the pre-scan estimate is
    grounded in this machine + this volume instead of a guess.

    Samples files (largest first, since they dominate) until ``sample_bytes``
    is covered or 6 files are read. Result is cached per root.
    """
    cached = _HASH_RATE_CACHE.get(root)
    if cached:
        return cached

    sizes: list[tuple[int, str]] = []
    budget = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                if _skipped(name, DEFAULT_IGNORES, DEFAULT_IGNORE_GLOBS):
                    continue
                p = os.path.join(dirpath, name)
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode) or st.st_size == 0:
                    continue
                sizes.append((st.st_size, p))
                budget += st.st_size
            if budget >= sample_bytes * 4:
                break
    except OSError:
        pass

    if not sizes:
        return _HASH_RATE_FALLBACK

    sizes.sort(reverse=True)
    read_bytes = 0
    elapsed = 0.0
    for size, path in sizes[:6]:
        try:
            t0 = time.perf_counter()
            with open(path, "rb") as fh:
                while fh.read(HASH_CHUNK):
                    pass
            elapsed += time.perf_counter() - t0
            read_bytes += size
        except OSError:
            continue
        if read_bytes >= sample_bytes:
            break

    rate = (read_bytes / elapsed) if elapsed > 0 and read_bytes else _HASH_RATE_FALLBACK
    rate = max(min(rate, 4 * 1024**3), 20 * 1024**2)  # clamp 20 MB/s .. 4 GB/s
    _HASH_RATE_CACHE[root] = rate
    return rate


def _measure_walk_rate(root: str, budget_s: float = 1.0) -> float:
    """
    Measure how many directory entries per second this volume actually yields.

    The constant is a poor substitute: an internal SSD does tens of thousands of
    entries/sec while an external USB volume does ~1-3k. Critically, we must do
    the *same work* the real walk does — calling ``entry.stat()`` per file,
    which is where nearly all the cost lives on a slow volume. Measuring a bare
    ``scandir`` count overestimates throughput by ~20x.

    Cached per root.
    """
    cached = _WALK_RATE_CACHE.get(root)
    if cached:
        return cached

    entries = 0
    stack = [root]
    started = time.perf_counter()
    try:
        while stack and (time.perf_counter() - started) < budget_s:
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        entries += 1
                        # Mirror walk_tree: this stat is the dominant cost.
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if not entry.is_symlink():
                                    stack.append(entry.path)
                            else:
                                entry.stat(follow_symlinks=False)
                        except OSError:
                            pass
            except OSError:
                continue
    except OSError:
        pass

    elapsed = time.perf_counter() - started
    if entries < 50 or elapsed <= 0:
        return _WALK_RATE_FALLBACK
    rate = entries / elapsed
    rate = max(min(rate, 200_000), 100)  # clamp 100 .. 200k entries/sec
    _WALK_RATE_CACHE[root] = rate
    return rate


def estimate_tree(
    root: str,
    *,
    ignore_names: Iterable[str] = DEFAULT_IGNORES,
    ignore_globs: Iterable[str] = DEFAULT_IGNORE_GLOBS,
    follow_symlinks: bool = False,
    budget_s: float = 8.0,
    progress: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    """
    Cheap pre-scan estimate: how many files/dirs and how many bytes are in
    ``root``, without hashing anything.

    ``budget_s`` bounds the walk. When the budget runs out, the counts seen so
    far are **extrapolated** to the whole tree using the fraction of
    directories already visited, and ``partial`` is set so the UI can label the
    number as an estimate rather than a measurement.
    """
    root = os.path.abspath(os.path.expanduser(root))
    started = time.perf_counter()

    result: dict[str, Any] = {
        "root": root,
        "exists": os.path.isdir(root),
        "files": 0,
        "dirs": 0,
        "bytes": 0,
        "skipped": 0,
        "partial": False,
        "elapsed": 0.0,
        "scanned_files": 0,
        "scanned_dirs": 0,
        "scanned_bytes": 0,
        "extrapolated": False,
        "errors": 0,
    }
    if not result["exists"]:
        return result

    ignore_names = set(ignore_names)
    ignore_globs = list(ignore_globs)
    stack = [root]
    visited_dirs = 0
    pending_dirs = 0

    while stack:
        if (time.perf_counter() - started) > budget_s:
            result["partial"] = True
            break
        current = stack.pop()
        visited_dirs += 1
        try:
            entries = list(os.scandir(current))
        except OSError:
            result["errors"] += 1
            continue
        for entry in entries:
            if _skipped(entry.name, ignore_names, ignore_globs):
                result["skipped"] += 1
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    result["dirs"] += 1
                    if not entry.is_symlink() or follow_symlinks:
                        stack.append(entry.path)
                        pending_dirs += 1
                elif entry.is_file(follow_symlinks=False):
                    result["files"] += 1
                    result["bytes"] += entry.stat(follow_symlinks=False).st_size
                else:
                    result["files"] += 1
            except OSError:
                result["errors"] += 1
        if progress and visited_dirs % 200 == 0:
            progress({"phase": "estimate", "root": root, "dirs": visited_dirs, "files": result["files"]})

    result["scanned_files"] = result["files"]
    result["scanned_dirs"] = result["dirs"]
    result["scanned_bytes"] = result["bytes"]

    if result["partial"] and visited_dirs > 0:
        # We stopped mid-walk. We know how many dirs we visited and how many are
        # still queued, so scale the totals by the fraction of the tree covered.
        total_dirs_known = visited_dirs + len(stack)
        if total_dirs_known > visited_dirs:
            factor = total_dirs_known / visited_dirs
            result["files"] = int(result["files"] * factor)
            result["dirs"] = int(result["dirs"] * factor)
            result["bytes"] = int(result["bytes"] * factor)
            result["extrapolated"] = True
            result["extrapolation_factor"] = round(factor, 2)
            result["note"] = (
                f"ประเมินไม่ครบใน {budget_s:.0f} วิ — ขยายผลจาก {visited_dirs:,} "
                f"จาก ~{total_dirs_known:,} โฟลเดอร์ (×{factor:.1f}) ตัวเลขเป็นค่าประมาณ"
            )
        else:
            result["note"] = f"ประเมินไม่ครบใน {budget_s:.0f} วิ — ตัวเลขเป็นค่าประมาณ"
    elif result["partial"]:
        # Budget expired before a single directory was read — nothing to
        # extrapolate from, so say so rather than reporting a misleading zero.
        result["note"] = (
            f"งบเวลา {budget_s:.0f} วิ หมดก่อนเริ่มอ่าน — ลองเพิ่มเวลา หรือเลือกโฟลเดอร์ที่เล็กลง"
        )

    result["elapsed"] = round(time.perf_counter() - started, 3)
    # Derive the walk rate from THIS walk — same tree, same volume, same moment.
    # A separate probe measures a cold cache on a possibly different subtree and
    # was off by ~10x; the real walk is the only honest sample.
    entries_seen = result["scanned_files"] + visited_dirs
    if result["elapsed"] > 0.02 and entries_seen >= 20:
        result["observed_walk_rate"] = entries_seen / result["elapsed"]
    if progress:
        progress({"phase": "estimate", "root": root, "dirs": visited_dirs, "files": result["files"], "done": True})
    return result


def estimate_scan(
    left_root: str,
    right_root: str,
    *,
    hash_mode: str = "auto",
    compare_mtime: bool = True,
    ignore_names: Iterable[str] = DEFAULT_IGNORES,
    ignore_globs: Iterable[str] = DEFAULT_IGNORE_GLOBS,
    follow_symlinks: bool = False,
    budget_s: float = 8.0,
    measure_throughput: bool = True,
) -> dict[str, Any]:
    """
    Pre-scan estimate for both sides: file counts, total bytes, and how long
    the real scan is expected to take.

    Cost model: walk (metadata ops, rate measured on this volume) +
    hash (only when hash_mode asks; rate measured on this volume) + compare.
    """
    left = estimate_tree(
        left_root,
        ignore_names=ignore_names,
        ignore_globs=ignore_globs,
        follow_symlinks=follow_symlinks,
        budget_s=budget_s,
    )
    right = estimate_tree(
        right_root,
        ignore_names=ignore_names,
        ignore_globs=ignore_globs,
        follow_symlinks=follow_symlinks,
        budget_s=budget_s,
    )

    total_files = left["files"] + right["files"]
    total_entries = total_files + left["dirs"] + right["dirs"]
    total_bytes = left["bytes"] + right["bytes"]

    # Walk cost. Prefer the rate observed during the estimate walks themselves:
    # same tree, same volume, warm cache — exactly what the real scan will meet.
    observed = [
        t.get("observed_walk_rate")
        for t in (left, right)
        if t.get("observed_walk_rate")
    ]
    if observed and measure_throughput:
        walk_rate = sum(observed) / len(observed)
        walk_rate_source = "observed"
    else:
        walk_rate = _measure_walk_rate(left_root if left["exists"] else right_root) if measure_throughput else _WALK_RATE_FALLBACK
        walk_rate_source = "probe" if measure_throughput else "default"
    walk_s = total_entries / walk_rate if walk_rate else total_entries / _WALK_RATE_FALLBACK

    # Hashing cost. Hashing only ever happens for files that exist on BOTH
    # sides — a file present on one side is copied, never hashed. So the bytes
    # at risk are bounded by the SMALLER side, not the total (assuming every
    # byte of both trees gets hashed made a 0.6s scan look like 20s).
    hash_bytes = 0
    hash_note = ""
    smaller_bytes = min(left["bytes"], right["bytes"])
    if hash_mode == "all":
        hash_bytes = smaller_bytes
        hash_note = "hash ทุกไฟล์ที่มีทั้งสองฝั่ง (จำกัดด้วยฝั่งที่เล็กกว่า)"
    elif hash_mode == "auto":
        hash_bytes = int(smaller_bytes * 0.15)
        hash_note = "hash เฉพาะไฟล์ที่ขนาดเท่าแต่เวลาไม่ตรง (ประมาณ 15% ของฝั่งที่เล็กกว่า)"

    rate = _measure_hash_rate(left_root if left["exists"] else right_root) if measure_throughput else _HASH_RATE_FALLBACK
    hash_s = (hash_bytes / rate) if rate else 0.0

    compare_s = total_files / 60_000

    # The countdown predicts the SCAN only. The pre-scan estimate has already
    # finished by the time the countdown starts, so adding its elapsed time here
    # would inflate the prediction (it made a 2s scan look like 23s).
    estimate_s = walk_s + hash_s + compare_s

    return {
        "left": left,
        "right": right,
        "hash_mode": hash_mode,
        "compare_mtime": compare_mtime,
        "assumptions": {
            "walk_rate_entries_per_sec": int(walk_rate),
            "walk_rate_source": walk_rate_source,
            "hash_rate_bytes_per_sec": int(rate),
            "hash_rate_mb_per_sec": round(rate / 1024 / 1024, 1),
            "hash_bytes_estimated": hash_bytes,
            "hash_note": hash_note,
            "model": "walk + hash + compare",
            "walk_rate_measured": measure_throughput,
        },
        "totals": {
            "files": total_files,
            "dirs": left["dirs"] + right["dirs"],
            "entries": total_entries,
            "bytes": total_bytes,
            "bytes_hash": hash_bytes,
        },
        "seconds": {
            "walk": round(walk_s, 3),
            "hash": round(hash_s, 3),
            "compare": round(compare_s, 3),
            "total": round(estimate_s, 3),
        },
        "partial": left["partial"] or right["partial"],
        "extrapolated": left.get("extrapolated") or right.get("extrapolated"),
        "left_total": left["bytes"],
        "right_total": right["bytes"],
        "sizes_equal_estimate": left["bytes"] == right["bytes"],
    }


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
