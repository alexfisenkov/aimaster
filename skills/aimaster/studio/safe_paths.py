"""Bound a private local path before any read/write, without following links."""
from pathlib import Path
import stat


def safe_path(root, path):
    root, path = Path(root).absolute(), Path(path).absolute()
    parts = path.relative_to(root).parts
    for item in [root, *(root / Path(*parts[:i]) for i in range(1, len(parts) + 1))]:
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValueError("unsafe_private_path")
        allowed = stat.S_ISDIR(info.st_mode) if item != path else stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
        if not allowed:
            raise ValueError("unsafe_private_path")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("unsafe_private_path")
    return path
