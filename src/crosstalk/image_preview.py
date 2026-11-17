"""Preserve encoded sources while publishing bounded, content-addressed PNG previews."""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
from pathlib import Path
from typing import Annotated, Self, override

from PIL import Image
from pydantic import Field, model_validator

from crosstalk.acquisition_ledger import sync_directory
from crosstalk.locator_storage import publish_metadata, read_metadata
from crosstalk.models import AcquisitionError, Digest, safe_directory
from crosstalk.records import Record


class ImagePreview(Record):
    """One derived thumbnail; this is an uncomposited base raster, not page appearance."""

    path: Annotated[str, Field(pattern=r"^output/figures/image-thumbnails/[0-9a-f]{64}\.png$")]
    sha256: Digest
    width: int = Field(ge=1, le=256)
    height: int = Field(ge=1, le=256)

    @model_validator(mode="after")
    def content_address(self) -> Self:
        """Require the recorded path to name exactly the declared PNG content digest."""
        if Path(self.path).stem != self.sha256:
            raise AcquisitionError("preview path does not match its content digest")
        return self


class PreviewOutputError(RuntimeError):
    """A derivative production failure must not become a scientific source exclusion."""

    def __init__(self, reason: str) -> None:
        """Keep typed context while the exception traceback remains mutable."""
        self.reason: str = reason
        super().__init__(reason)

    @override
    def __str__(self) -> str:
        return self.reason


def _png_size(png: bytes) -> tuple[int, int]:
    """Verify a bounded PNG before accepting its dimensions or publishing any bytes."""
    if not 0 < len(png) <= 1_000_000:
        raise AcquisitionError("preview exceeds its one MB byte bound")
    with Image.open(io.BytesIO(png)) as image:
        if image.format != "PNG" or not 1 <= image.width <= 256 or not 1 <= image.height <= 256:
            raise AcquisitionError("preview must be a PNG thumbnail at most 256 pixels per side")
        width, height = image.size
        image.verify()
    return width, height


def _publish_preview(root: Path, png: bytes) -> ImagePreview:
    """Reuse exact previews; preserve any corrupt derivative before atomic regeneration."""
    width, height = _png_size(png)
    digest = hashlib.sha256(png).hexdigest()
    relative = f"output/figures/image-thumbnails/{digest}.png"
    directory = safe_directory(root, "output/figures/image-thumbnails")
    target = root / relative
    try:
        previous = read_metadata(target)
    except FileNotFoundError:
        previous = None
    if previous == png:
        return ImagePreview(path=relative, sha256=digest, width=width, height=height)
    if previous is not None:
        history = safe_directory(root, "output/figures/image-preview-history")
        old_digest = hashlib.sha256(previous).hexdigest()
        _ = publish_metadata(history, f"{old_digest}-{digest}.bin", previous)
        if read_metadata(target) != previous:
            raise AcquisitionError("preview changed while its original bytes were preserved")
    descriptor, temporary = tempfile.mkstemp(prefix=".preview-", dir=directory)
    with os.fdopen(descriptor, "wb") as stream:
        _ = stream.write(png)
        stream.flush()
        os.fsync(stream.fileno())
        if previous is not None:
            os.fchmod(stream.fileno(), target.stat().st_mode & 0o777)
    if previous is None:
        try:
            os.link(temporary, target)
        except FileExistsError as error:
            if read_metadata(target) != png:
                raise AcquisitionError(
                    "concurrent preview publication has conflicting bytes"
                ) from error
        Path(temporary).unlink()
    else:
        _ = Path(temporary).replace(target)
    sync_directory(directory)
    if read_metadata(target) != png:
        raise AcquisitionError("published preview bytes disagree with the derived PNG")
    return ImagePreview(path=relative, sha256=digest, width=width, height=height)


def publish_preview(root: Path, png: bytes) -> ImagePreview:
    """Stop the run on output trouble; valid source eligibility must stay unchanged."""
    try:
        return _publish_preview(root, png)
    except (OSError, ValueError) as error:
        raise PreviewOutputError(str(error)) from error
