"""Publication guard for generated visual files."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from PIL import Image


def save_visual(image: Image.Image, target: Path) -> None:
    """Refuse terminal symlinks before Pillow can follow them during a save."""
    if target.is_symlink():
        message = f"Visual output symlink refused: {target.name}"
        raise ValueError(message)
    image.save(target)
