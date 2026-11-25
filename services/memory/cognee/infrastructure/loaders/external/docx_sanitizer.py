"""Sanitize OOXML (zip-based) documents whose internal relationships are broken.

Doc generators sometimes emit relationships with a non-existent internal
target (e.g. Target="NULL"). python-docx — the parser behind docling's
MsWordDocumentBackend — resolves every relationship in ``*.rels`` eagerly,
so one dangling target makes the whole document unloadable:

    KeyError: "There is no item named 'word/NULL' in the archive"

docling upstream (<= 2.132) only strips fragment-only targets ("#anchor"),
not dangling targets. This module scans every ``*.rels`` part of a
zip-based document and rewrites the package without the broken
relationships into a temp file. The original file is never modified.
"""

import contextlib
import os
import posixpath
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

from cognee.shared.logging_utils import get_logger

logger = get_logger(__name__)

# Zip-package formats routed through docling that can carry "*.rels" parts.
# Legacy binary formats (.doc/.ppt/.xls) are not zip packages — excluded.
ZIP_BASED_EXTS = {
    "docx", "docm", "dotx", "dotm",   # Word
    "pptx", "pptm", "potx", "ppsm",   # PowerPoint
    "xlsx", "xlsm", "xltm",           # Excel
    "odt", "ods", "odp",              # OpenDocument
}

_RELNS = "http://schemas.openxmlformats.org/package/2006/relationships"
_REL_TAG = f"{{{_RELNS}}}Relationship"


def _rels_base_dir(rels_entry: str) -> str:
    """Directory a .rels part's targets resolve against.

    "word/_rels/document.xml.rels" -> "word"
    "_rels/.rels"                  -> ""   (package root)
    """
    return posixpath.dirname(posixpath.dirname(rels_entry))


def _target_to_part(rels_entry: str, target: str) -> str:
    """Resolve a relationship Target to the package part name it points to."""
    target = urllib.parse.unquote(target)          # "%20" -> " " (URL-encoded targets)
    if target.startswith("/"):                     # absolute: from package root
        return posixpath.normpath(target.lstrip("/"))
    return posixpath.normpath(                     # relative: from the rels' base dir
        posixpath.join(_rels_base_dir(rels_entry), target)
    )


def find_broken_rels(path: str) -> dict[str, list[str]]:
    """Map each ``*.rels`` entry to the Ids of relationships with dead targets."""
    broken: dict[str, list[str]] = {}
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            for entry in [n for n in names if n.endswith(".rels")]:
                try:
                    root = ET.fromstring(zf.read(entry))
                except ET.ParseError:
                    continue                       # malformed rels: not our problem
                for rel in root.iter(_REL_TAG):
                    if rel.get("TargetMode", "Internal").lower() == "external":
                        continue                   # web/mail links are valid, keep
                    part = _target_to_part(entry, rel.get("Target", ""))
                    if part not in names:
                        broken.setdefault(entry, []).append(rel.get("Id", "?"))
    except zipfile.BadZipFile:
        return {}                                  # not a zip: let the loader report it
    return broken


def sanitize_ooxml(path: str) -> tuple[str | None, int]:
    """Rewrite the package without dangling relationships.

    Returns ``(temp_path, removed_count)``, or ``(None, 0)`` when the package
    is clean (no temp file is created). The caller owns the temp file.
    """
    broken = find_broken_rels(path)
    if not broken:
        return None, 0

    removed = 0
    fd, tmp_path = tempfile.mkstemp(
        suffix=os.path.splitext(path)[1] or ".docx", prefix="sanitized_"
    )
    os.close(fd)
    try:
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp_path, "w") as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename in broken:
                    root = ET.fromstring(data)
                    for rel in list(root.iter(_REL_TAG)):
                        if rel.get("Id") in broken[info.filename]:
                            root.remove(rel)
                            removed += 1
                    ET.register_namespace("", _RELNS)
                    data = ET.tostring(root, xml_declaration=True, encoding="UTF-8")
                # Same ZipInfo -> original compress_type/date_time/attrs preserved
                zout.writestr(info, data)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise

    logger.warning(
        "Sanitized OOXML document '%s': removed %d dangling relationship(s): %s",
        path,
        removed,
        broken,
    )
    return tmp_path, removed
