"""Writing mail content to LOCAL disk, safely.

download_attachment and export_message are read-tier tools that
nonetheless put bytes on this machine, so the rules live in one place:
names derived from mail are reduced to a bare filename, writes are
always confined to CKM365_DOWNLOAD_ROOT (falling back to CKM365_ATTACH_ROOT,
then the private default data directory). Attachment reads are always
confined too. State, profiles and hidden paths below the root are denied;
an existing file is never overwritten, and a failure leaves nothing behind.
"""

import os
from pathlib import Path

from ... import config


def default_root() -> Path:
    """The private data directory used when no disk root is configured."""
    base = Path(os.environ.get("XDG_DATA_HOME") or "~/.local/share")
    root = (base / "ckm365").expanduser().resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def download_root() -> Path:
    """Download override, then the attachment override, then the default."""
    root = os.environ.get("CKM365_DOWNLOAD_ROOT") or \
        os.environ.get("CKM365_ATTACH_ROOT")
    return Path(root).expanduser().resolve() if root else default_root()


def attach_root() -> Path:
    """Attachment override or the default; downloads never widen reads."""
    root = os.environ.get("CKM365_ATTACH_ROOT")
    return Path(root).expanduser().resolve() if root else default_root()


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


def confine(path: Path, what: str, root: Path | None = None) -> Path:
    """Resolve a local path and enforce confinement, following symlinks.

    The download root applies unless the caller supplies an explicit root
    (add_attachment uses attach_root()). State, profiles and hidden path
    components below the root are refused even with a broad root configured.
    """
    path = path.expanduser().resolve()
    root = (download_root() if root is None else root).expanduser().resolve()
    if path.is_relative_to(config.state_dir().resolve()):
        raise ValueError(f"{what} is in the ckm365 state directory; refusing to touch it")
    profiles = config.profiles_path().expanduser()
    if path == profiles.resolve() or path.is_relative_to(profiles.parent.resolve()):
        raise ValueError(f"{what} is in the profiles directory; refusing to touch it")
    if not path.is_relative_to(root):
        kind = "attachment" if what == "attachment" else "download"
        env = "CKM365_ATTACH_ROOT" if kind == "attachment" else "CKM365_DOWNLOAD_ROOT"
        raise ValueError(f"{what} is outside the {kind} root ({root}); "
                         f"set {env} to change it")
    if any(part.startswith(".") for part in path.relative_to(root).parts):
        raise ValueError(f"{what} has a hidden path component below the root; "
                         "refusing to touch it")
    return path


def write_target(dest_path: str, dir_name: str | None) -> Path:
    """Resolve where bytes may land, or refuse with the reason. Shared by
    every tool here that writes to local disk.

    Mirrors add_attachment's containment in the opposite direction (see
    confine).

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
    dest = confine(dest, "destination")
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
