"""
FDVS — volume discovery, permission probing, and directory browsing.

macOS gates removable drives and user folders behind TCC. This module makes
that explicit instead of failing with a bare PermissionError: every access is
probed and reported as ``ok`` / ``permission_required`` / ``not_found``.
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Any

__all__ = [
    "list_volumes",
    "probe_access",
    "list_dir",
    "request_access",
    "SYSTEM_SETTINGS_URLS",
    "home_roots",
]

IS_MAC = platform.system() == "Darwin"

# Real macOS System Settings privacy anchors (Ventura+). "Removable Volumes" is a
# sub-permission under Files and Folders, not its own pane, so it maps there too.
SYSTEM_SETTINGS_URLS = {
    "full_disk_access": "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
    "files_and_folders": "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders",
    "removable_volumes": "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders",
}

# Human-readable pane name per hint.
PANE_NAMES = {
    "full_disk_access": "Full Disk Access",
    "files_and_folders": "Files and Folders",
    "removable_volumes": "Files and Folders → Removable Volumes",
}

# Folders macOS protects per-app; we surface them as known permission targets.
PROTECTED_HINTS = {
    "Desktop": "files_and_folders",
    "Documents": "files_and_folders",
    "Downloads": "files_and_folders",
    "Library": "full_disk_access",
}


def home_roots() -> list[dict[str, Any]]:
    home = os.path.expanduser("~")
    out: list[dict[str, Any]] = [{"path": home, "name": "Home", "kind": "home"}]
    for name in ("Desktop", "Documents", "Downloads"):
        p = os.path.join(home, name)
        if os.path.exists(p):
            out.append(
                {
                    "path": p,
                    "name": name,
                    "kind": "user_folder",
                    "hint": PROTECTED_HINTS.get(name, "full_disk_access"),
                }
            )
    return out


def list_volumes() -> dict[str, Any]:
    """Enumerate mounted volumes under /Volumes plus the root filesystem."""
    volumes: list[dict[str, Any]] = []

    root_stat = os.statvfs("/") if hasattr(os, "statvfs") else None
    if root_stat:
        volumes.append(
            {
                "path": "/",
                "name": "Macintosh HD (system root)",
                "kind": "system",
                "total_bytes": root_stat.f_blocks * root_stat.f_frsize,
                "free_bytes": root_stat.f_bavail * root_stat.f_frsize,
                "removable": False,
            }
        )

    vol_dir = "/Volumes"
    if os.path.isdir(vol_dir):
        try:
            names = sorted(os.listdir(vol_dir))
        except OSError:
            names = []
        for name in names:
            if name.startswith("."):
                continue
            path = os.path.join(vol_dir, name)
            if not os.path.isdir(path):
                continue
            entry: dict[str, Any] = {
                "path": path,
                "name": name,
                "kind": "volume",
                "removable": True,
                "hint": "removable_volumes",
            }
            try:
                st = os.statvfs(path)
                entry["total_bytes"] = st.f_blocks * st.f_frsize
                entry["free_bytes"] = st.f_bavail * st.f_frsize
            except OSError:
                entry["total_bytes"] = 0
                entry["free_bytes"] = 0
            entry["access"] = probe_access(path)
            volumes.append(entry)

    # External disks registered with diskutil but not mounted get surfaced too.
    if IS_MAC:
        try:
            res = subprocess.run(
                ["diskutil", "list", "-plist", "external"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0 and "Volume Name" not in res.stdout:
                pass  # nothing extra to add; unmounted disks have no path
        except (OSError, subprocess.SubprocessError):
            pass

    return {"volumes": volumes, "home": home_roots(), "platform": platform.platform()}


def probe_access(path: str) -> dict[str, Any]:
    """
    Test whether this process can actually read ``path``.

    Returns {"status", "readable", "writable", "error", "hint"}.
    """
    path = os.path.abspath(os.path.expanduser(path))
    result: dict[str, Any] = {
        "path": path,
        "status": "ok",
        "readable": False,
        "writable": False,
        "error": None,
        "hint": None,
    }

    if not os.path.exists(path):
        result["status"] = "not_found"
        result["error"] = "path does not exist"
        return result

    if not os.path.isdir(path):
        result["status"] = "not_a_directory"
        result["error"] = "path is not a directory"
        return result

    try:
        with os.scandir(path) as it:
            next(it, None)
        result["readable"] = True
    except PermissionError as exc:
        result["status"] = "permission_required"
        result["error"] = exc.strerror or "permission denied"
        result["hint"] = _hint_for(path)
        return result
    except OSError as exc:
        result["status"] = "error"
        result["error"] = f"{exc.strerror or exc}"
        return result

    result["writable"] = os.access(path, os.W_OK)
    return result


def _hint_for(path: str) -> str:
    if path.startswith("/Volumes/"):
        return "removable_volumes"
    base = os.path.basename(path.rstrip("/"))
    if base in PROTECTED_HINTS:
        return PROTECTED_HINTS[base]
    return "full_disk_access"


def request_access(path: str) -> dict[str, Any]:
    """
    Attempt to trigger the OS permission prompt for ``path`` and report state.

    On macOS the TCC prompt is raised by the first real read attempt, so we
    probe again (which may itself raise the dialog) and, when still denied,
    hand back the System Settings URL the user must visit.
    """
    probe = probe_access(path)
    if probe["status"] == "permission_required":
        hint = probe.get("hint") or "full_disk_access"
        probe["settings_url"] = SYSTEM_SETTINGS_URLS.get(hint)
        probe["pane"] = PANE_NAMES.get(hint, "Full Disk Access")
        probe["instructions"] = (
            "เปิด System Settings → Privacy & Security → "
            + probe["pane"]
            + " แล้วเพิ่ม Terminal (หรือแอปที่รัน FDVS) จากนั้นกด 'ตรวจสอบสิทธิ์อีกครั้ง'"
        )
        probe["settings_commands"] = {
            "full_disk_access": SYSTEM_SETTINGS_URLS["full_disk_access"],
            "files_and_folders": SYSTEM_SETTINGS_URLS["files_and_folders"],
        }
    return probe


def list_dir(path: str, *, show_hidden: bool = False, limit: int = 3000) -> dict[str, Any]:
    """List one directory level for the folder picker."""
    path = os.path.abspath(os.path.expanduser(path or "/"))
    access = probe_access(path)
    if access["status"] != "ok":
        return {"path": path, "entries": [], "access": access}

    dirs: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    truncated = False
    try:
        with os.scandir(path) as it:
            for entry in it:
                if not show_hidden and entry.name.startswith("."):
                    continue
                if len(dirs) + len(files) >= limit:
                    truncated = True
                    break
                try:
                    is_dir = entry.is_dir(follow_symlinks=True)
                    size = 0 if is_dir else entry.stat(follow_symlinks=False).st_size
                except OSError:
                    is_dir, size = False, 0
                rec = {
                    "name": entry.name,
                    "path": entry.path,
                    "is_dir": is_dir,
                    "size": size,
                    "is_link": entry.is_symlink(),
                }
                (dirs if is_dir else files).append(rec)
    except PermissionError as exc:
        return {
            "path": path,
            "entries": [],
            "access": {**access, "status": "permission_required", "error": exc.strerror, "hint": _hint_for(path)},
        }
    except OSError as exc:
        return {"path": path, "entries": [], "access": {**access, "status": "error", "error": str(exc)}}

    dirs.sort(key=lambda d: d["name"].lower())
    files.sort(key=lambda f: f["name"].lower())
    parent = os.path.dirname(path.rstrip("/")) or "/"

    return {
        "path": path,
        "parent": parent,
        "entries": dirs + files,
        "access": access,
        "truncated": truncated,
        "counts": {"dirs": len(dirs), "files": len(files)},
    }
