"""Appearance-only grouping keeps all physical slots and does not impute missing typography."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Final

from crosstalk.study_atlas_adapter_records import AtlasInputFrame
from crosstalk.study_cluster_records import (
    ClusterBinding,
    FeatureDefinition,
    FeatureFrame,
    PageFeatureInput,
)
from crosstalk.study_language_records import StudyError

if TYPE_CHECKING:
    from crosstalk.atlas_records import ArtifactBinding
    from crosstalk.study_atlas_adapter_records import AtlasPageSlot, AtlasUnit

APPEARANCE_FEATURES: Final = (
    FeatureDefinition(
        name="full-render-grayscale-entropy",
        channel="appearance",
        unit="bits",
        minimum=0.0,
        maximum=8.0,
    ),
    *(
        FeatureDefinition(
            name=f"full-render-dark-fraction-r{row}-c{column}",
            channel="appearance",
            unit="half-open-cell dark pixels / observed cell pixels",
            weight=1 / 16,
            minimum=0.0,
            maximum=1.0,
        )
        for row in range(4)
        for column in range(4)
    ),
)


def cluster_binding(binding: ArtifactBinding) -> ClusterBinding:
    """Adapt explicitly between public schemas without passing a generic model dump."""
    return ClusterBinding(path=binding.path, sha256=binding.sha256)


def _sources(
    frame: AtlasInputFrame, unit: AtlasUnit, slot: AtlasPageSlot
) -> tuple[ClusterBinding, ...]:
    """Retain at most seven exact local source/selection pointers for each physical observation."""
    values = [unit.pdf, frame.receipt, frame.appearance_projection, frame.layout_reconciliation]
    if slot.appearance is not None:
        values.append(slot.appearance.record_binding)
        if slot.appearance.image is not None:
            values.append(slot.appearance.image.image)
    if slot.layout is not None:
        values.append(slot.layout.source)
    unique: dict[str, str] = {}
    for item in values:
        if unique.setdefault(item.path, item.sha256) != item.sha256:
            raise StudyError("one atlas source locator claims conflicting byte versions")
    return tuple(
        ClusterBinding(path=path, sha256=digest) for path, digest in sorted(unique.items())
    )


def appearance_features(frame: AtlasInputFrame) -> FeatureFrame:
    """Entropy plus16 equally partitioned grid weights is the declared default appearance space."""
    frame = AtlasInputFrame.model_validate(frame.model_dump(mode="python"), strict=True)
    units = {unit.issue_id: unit for unit in frame.units}
    rows: list[PageFeatureInput] = []
    for slot in sorted(frame.pages, key=lambda item: (item.pdf_sha256, item.page_index)):
        unit = units[slot.issue_id]
        values: tuple[float | None, ...] = (None,) * len(APPEARANCE_FEATURES)
        if slot.appearance is not None:
            page = slot.appearance.artifact.page
            if page.settings.grid_side != 4:
                raise StudyError("appearance adapter requires the declared4x4 full-render grid")
            values = (
                page.pixels.grayscale_entropy_bits,
                *(cell.dark_fraction for cell in page.pixels.cells),
            )
        rows.append(
            PageFeatureInput(
                issue_id=slot.issue_id,
                pdf_sha256=slot.pdf_sha256,
                page_index=slot.page_index,
                total_pdf_pages=unit.physical_pages,
                values=values,
                source_bindings=_sources(frame, unit, slot),
                status=slot.status,
                reason=slot.reason,
            )
        )
    epoch = hashlib.sha256(
        json.dumps(
            (
                "appearance-adapter-1",
                frame.rendering_identity,
                tuple(item.model_dump(mode="json") for item in APPEARANCE_FEATURES),
            ),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return FeatureFrame(
        feature_epoch_sha256=epoch,
        source_frame_receipt=cluster_binding(frame.receipt),
        definitions=APPEARANCE_FEATURES,
        pages=tuple(rows),
        declared_issue_ids=tuple(sorted(units)),
        declared_total_pages=len(rows),
        physical_scope="all-physical-pages",
        space_label=(
            "Full-render entropy +4x4 dark-fraction cells; no "
            + "native-text/layout eligibility filter"
        ),
    )


def pilot_subset(frame: FeatureFrame, maximum_pages: int = 64) -> FeatureFrame:
    """Select deterministic issue rounds with explicit subset scope and refusals."""
    if not 1 <= maximum_pages <= 64:
        raise StudyError("atlas pilot capacity must be between1and64physical slots")
    groups = {
        issue: tuple(
            sorted(
                (page for page in frame.pages if page.issue_id == issue),
                key=lambda item: hashlib.sha256(
                    f"atlas-pilot-7301:{item.pdf_sha256}:{item.page_index}".encode()
                ).hexdigest(),
            )
        )
        for issue in sorted(frame.declared_issue_ids)
    }
    selected: list[PageFeatureInput] = []
    for index in range(max((len(group) for group in groups.values()), default=0)):
        for issue in sorted(
            groups,
            key=lambda name: hashlib.sha256(("atlas-pilot-7301:" + name).encode()).hexdigest(),
        ):
            if index < len(groups[issue]) and len(selected) < maximum_pages:
                selected.append(groups[issue][index])
        if len(selected) == maximum_pages:
            break
    return FeatureFrame(
        feature_epoch_sha256=frame.feature_epoch_sha256,
        source_frame_receipt=frame.source_frame_receipt,
        definitions=frame.definitions,
        pages=tuple(selected),
        declared_issue_ids=tuple(sorted({page.issue_id for page in selected})),
        declared_total_pages=len(selected),
        physical_scope="declared-subset",
        space_label=frame.space_label + "; deterministic64-slot pilot",
    )
