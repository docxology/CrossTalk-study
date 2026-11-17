"""New atlas producers retain a separate source/runtime identity from prior measurements."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Final

from PIL import __version__ as pillow_version

FILES: Final = (
    "atlas_records.py",
    "atlas_pixels.py",
    "atlas_mosaic.py",
    "atlas_ghost_records.py",
    "atlas_ghost.py",
    "atlas_ghost_figures.py",
    "atlas_lineage.py",
    "study_language_records.py",
)


def implementation_digest() -> str:
    """Caller qualification must additionally bind actual installed provider/native file bytes."""
    directory = Path(__file__).parent
    members = tuple(
        (name, hashlib.sha256((directory / name).read_bytes()).hexdigest()) for name in FILES
    )
    return hashlib.sha256(
        json.dumps((members, sys.version, pillow_version), separators=(",", ":")).encode()
    ).hexdigest()
