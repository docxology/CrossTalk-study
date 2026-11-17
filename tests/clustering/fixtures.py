"""Small declared numeric fixtures exercise arithmetic/source contracts, not corpus claims."""

from __future__ import annotations

from crosstalk.study_cluster_records import (
    ClusterBinding,
    ClusterPlan,
    FeatureDefinition,
    FeatureFrame,
    PageFeatureInput,
)

BINDING = ClusterBinding(path="synthetic/features.json", sha256="a" * 64)


def frame(groups: tuple[tuple[float, ...], ...] = ((0.0, 1.0), (9.0, 10.0))) -> FeatureFrame:
    """Each tuple is one complete synthetic issue, with exact physical-page coverage."""
    pages = tuple(
        PageFeatureInput(
            issue_id=f"synthetic-{issue}",
            pdf_sha256=f"{issue + 1:064x}",
            page_index=index,
            total_pdf_pages=len(values),
            values=(value,),
            source_bindings=(BINDING,),
            status="measured",
            reason="Synthetic numeric control",
        )
        for issue, values in enumerate(groups)
        for index, value in enumerate(values)
    )
    return FeatureFrame(
        feature_epoch_sha256="b" * 64,
        source_frame_receipt=BINDING,
        definitions=(
            FeatureDefinition(
                name="synthetic-density", channel="appearance", unit="synthetic-unit"
            ),
        ),
        pages=pages,
        declared_issue_ids=tuple(f"synthetic-{issue}" for issue in range(len(groups))),
        declared_total_pages=len(pages),
        physical_scope="all-physical-pages",
        space_label="Explicit synthetic arithmetic control; not journal features",
    )


def plan(
    **changes: float | str | tuple[int, ...] | tuple[str, ...] | ClusterBinding | None,
) -> ClusterPlan:
    """Tests choose their tiny frame explicitly rather than relax production gates."""
    base = ClusterPlan(requested_k=(1, 2), per_issue_training_cap=2, minimum_training_issues=2)
    return ClusterPlan.model_validate({**base.model_dump(mode="python"), **changes}, strict=True)
