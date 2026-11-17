"""Adopt separately executed native-layer results through their current source guard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from crosstalk.dossier_records import DossierFigure, SourceBinding
from crosstalk.native_layer_read import current_native_layer_report
from crosstalk.native_view_store import publish_native_view

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class NativeLayerAppendix:
    """An executed observation or explicit current unavailability, with source bindings."""

    paragraphs: tuple[str, ...]
    bindings: tuple[SourceBinding, ...]
    figures: tuple[DossierFigure, ...] = ()


def current_native_layer_appendix(root: Path) -> NativeLayerAppendix:
    """Missing or stale results remain explicit, without supplying historical values as current."""
    try:
        with current_native_layer_report(root) as current:
            run = current.run
            paragraphs = [
                f"Separate native-layer phase: {len(run.issues)} source-distinct NPS issues "
                + f"accepted from {len(run.selected_issue_ids)} selected; "
                + f"{len(run.deferred_issue_ids)} deferred; "
                + f"{len(run.unavailable)} unavailable. Raw lexical metrics remain preserved. "
                + "OCR derivatives and visual decoder success do not determine this native cohort. "
                + f"Source kind: {run.settings.source_kind}.",
                "Matched repository wrappers are a reversible exploratory template view, "
                + "not a validated classifier. Native-zero sources have unavailable rates. "
                + "Each view has its own eligible frame; a changed estimate is not solely "
                + "cleaning on a fixed paired sample. Intervals are nominal marginal diagnostics, "
                + "without joint-family coverage or across-view difference inference.",
            ]
            for variant in run.variants:
                cohort = variant.cohort
                paragraphs.append(
                    f"Native view {variant.label}: {len(cohort.workflow_selected_issue_ids)} "
                    + "workflow-selected issues; "
                    + f"{len(cohort.eligible_complete_nonzero_issue_ids)} complete positive-token "
                    + f"eligible issues; {cohort.observed_native_tokens} selected native tokens; "
                    + f"{len(cohort.zero_native_token_issue_ids)} native-zero issues. "
                    + "Exact eligible IDs, weighting, diagnostic status and metadata-year/decade "
                    + "availability are retained in the sealed JSONL and HTML report.",
                )
            figure = publish_native_view(root, current)
            bindings = tuple(
                SourceBinding(path=binding.path, sha256=binding.sha256)
                for binding in current.reader.source_bindings()
            )
            result = NativeLayerAppendix(tuple(paragraphs), bindings, (figure,))
    except (OSError, ValueError) as error:
        return NativeLayerAppendix(
            (
                "Separate native-layer results are unavailable for the current source frame: "
                + str(error),
            ),
            (),
        )
    return result
