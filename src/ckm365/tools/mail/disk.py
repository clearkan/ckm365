"""Writing mail content to LOCAL disk, safely.

download_attachment and export_message are read-tier tools that
nonetheless put bytes on this machine, so the rules live in one place:
names derived from mail are reduced to a bare filename, writes are
confined to CKM365_DOWNLOAD_ROOT (falling back to CKM365_ATTACH_ROOT),
an existing file is never overwritten, and a failure part-way leaves
nothing behind.
"""

import os
from pathlib import Path


def safe_name(name: str) -> str:
    """An attachment's own name reduced to a bare filename.

    Attachment names are chosen by whoever sent the mail: separators (both
    kinds — a Windows sender's name reaches us verbatim) and control
    characters go, and '', '.', '..' fall back to a fixed name. Containment
    is enforced by the root check below as well; this only keeps a derived
    filename sane.
    """
    base = Path((name or "").replace("\\", "/")).name
    base = "".join(c for c in base if ord(c) >= 32 and ord(c) != 127).strip()
    return base if base not in ("", ".", "..") else "attachment"


def write_target(dest_path: str, dir_name: str | None) -> Path:
    """Resolve where bytes may land, or refuse with the reason. Shared by
    every tool here that writes to local disk.

    Mirrors add_attachment's containment in the opposite direction:
    CKM365_DOWNLOAD_ROOT confines writes, falling back to
    CKM365_ATTACH_ROOT so an operator who already fenced the read side
    gets the write side fenced by the same setting.

    dir_name is the filename to use when dest_path names an existing
    DIRECTORY; None means a directory is an error, because that caller has
    no natural name to fall back on.
    """
    if not (dest_path or "").strip():
        raise ValueError("dest_path is required")
    dest = Path(dest_path).expanduser()
    if dest.is_dir():
        if dir_name is None:
            raise ValueError(f"dest_path is a directory ({dest}); name the "
                             "file to write, including its extension")
        dest = dest / safe_name(dir_name)
    dest = dest.resolve()
    root = os.environ.get("CKM365_DOWNLOAD_ROOT") or \
        os.environ.get("CKM365_ATTACH_ROOT")
    if root and not dest.is_relative_to(Path(root).expanduser().resolve()):
        raise ValueError(f"destination is outside the download root ({root}); "
                         "refusing to write there")
    if dest.exists():
        raise ValueError(f"refusing to overwrite an existing file: {dest}")
    if not dest.parent.is_dir():
        raise ValueError(f"destination directory does not exist: {dest.parent}")
    return dest


def write_atomic(dest: Path, produce) -> int:
    """Run `produce` against a .part file and rename it into place, so a
    failure part-way leaves nothing behind and a retry is not blocked by
    its own debris. Returns whatever `produce` reports it wrote."""
    part = dest.with_name(dest.name + ".part")
    try:
        written = produce(part)
        part.replace(dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return written
