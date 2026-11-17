"""Tiny actual PNG files exercise transformations without pretending to be journal material."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

from PIL import Image

from crosstalk.atlas_ghost_records import GhostMember, GhostPlan
from crosstalk.atlas_pixels import encode_png
from crosstalk.atlas_records import ArtifactBinding, PageImage, PixelSettings


def binding(name: str = "fixture") -> ArtifactBinding:
    return ArtifactBinding(
        path=f"output/fixture/{name}.json", sha256=hashlib.sha256(name.encode()).hexdigest()
    )


def page(
    root: Path,
    issue: str,
    index: int,
    color: int | tuple[int, int, int] | tuple[int, int, int, int],
    size: tuple[int, int] = (8, 8),
) -> PageImage:
    mode = "L" if isinstance(color, int) else "RGBA" if len(color) == 4 else "RGB"
    with Image.new(mode, size, color) as image:
        raw = encode_png(image)
    sha = hashlib.sha256(raw).hexdigest()
    relative = f"data/fixture/{sha}.png"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    _ = target.write_bytes(raw)
    pdf = hashlib.sha256(issue.encode()).hexdigest()
    return PageImage(
        issue_id=issue,
        pdf_sha256=pdf,
        page_index=index,
        total_pdf_pages=1000,
        source_pdf=ArtifactBinding(path=f"data/fixture/{issue}.pdf", sha256=pdf),
        source_evidence=binding("evidence"),
        image=ArtifactBinding(path=relative, sha256=sha),
        rendering_identity="c" * 64,
        width=size[0],
        height=size[1],
        image_basis="full-page-render",
    )


def resolve(root: Path, source: PageImage) -> bytes:
    return (root / source.image.path).read_bytes()


def member(source: PageImage) -> GhostMember:
    return GhostMember(
        issue_id=source.issue_id,
        pdf_sha256=source.pdf_sha256,
        page_index=source.page_index,
        assignment_role="train",
        page=source,
    )


def plan(
    pages: tuple[PageImage, ...], weighting: Literal["equal-page", "equal-issue"] = "equal-page"
) -> GhostPlan:
    return GhostPlan(
        cluster_id="cluster-01",
        clustering_receipt=binding("clusters"),
        source_frame=binding("frame"),
        upstream_frame_exclusions=binding("excluded"),
        aggregation_runtime=binding("runtime"),
        clustering_method_note="Generated control membership; not a learned journal cluster.",
        selection_note="All explicit generated pages.",
        members=tuple(member(p) for p in pages),
        representative_page_keys=(pages[0].page_key,),
        representative_basis="Explicit generated control exemplar; not a corpus medoid.",
        weighting=weighting,
        pixels=PixelSettings(width=8, height=8),
    )
