"""secure_paths.py -- the ONE containment-checked resolver for client-supplied file
names (P0 of PLAN-audit-motion-voice.md). Every HTTP endpoint that receives a filename
from the browser resolves it here, so a hostile name ("..\\..\\boot.ini", an absolute
path, a symlink escape) can never read or write outside the ComfyUI input folder.

Pure stdlib on purpose -- importable from anywhere in the pack without dragging in
server/comfy/folder_paths.
"""

import os


def contained(path, root):
    """True when `path` (after .. / symlink resolution) lies strictly inside `root`.
    The trailing separator matters: a bare prefix check would let a SIBLING directory
    ("input_evil") pass for ("input")."""
    return os.path.realpath(path).startswith(os.path.realpath(root) + os.sep)


def upload_target(filename, upload_dir):
    """The write path for a client-supplied upload name: basename only (uploads never
    carry directories), containment-checked. Raises ValueError on an empty or escaping
    name -- the endpoint turns that into HTTP 400."""
    filename = os.path.basename(filename or "")
    path = os.path.join(upload_dir, filename)
    if not filename or not contained(path, upload_dir):
        raise ValueError("Invalid filename")
    return path


def resolve_existing(name, input_dir, subdir="whatdreamscost"):
    """Resolve a client-supplied name to an EXISTING file inside `input_dir`, trying the
    pack's historical candidate order: input_dir/name, input_dir/subdir/basename,
    input_dir/basename. Returns the absolute path, or None when the file is missing OR
    the name escapes the input folder (the two cases are deliberately indistinguishable
    to the client)."""
    if not name:
        return None
    clean = str(name).replace("\\", "/")
    basename = os.path.basename(clean)
    candidates = [
        os.path.join(input_dir, clean),
        os.path.join(input_dir, subdir, basename),
        os.path.join(input_dir, basename),
    ]
    for candidate in candidates:
        real = os.path.realpath(candidate)
        if not contained(real, input_dir):
            continue
        if os.path.isfile(real):
            return real
    return None
