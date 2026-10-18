"""FDVS — Folder VS package."""

from .compare import compare_trees, hash_file, walk_tree
from .sync import PlanError, execute_plan, plan_sync
from .volumes import list_dir, list_volumes, probe_access, request_access

__version__ = "1.0.0"
__all__ = [
    "compare_trees",
    "walk_tree",
    "hash_file",
    "plan_sync",
    "execute_plan",
    "PlanError",
    "list_volumes",
    "list_dir",
    "probe_access",
    "request_access",
]
