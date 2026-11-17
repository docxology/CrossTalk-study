"""Source-passage checks and exact declared-method replay do not measure semantic accuracy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from crosstalk.article_quantities import quantitative_expressions

if TYPE_CHECKING:
    from crosstalk.article_quantities_records import QuantityRun
from crosstalk.article_records import ArticleError, ArticlePage
from crosstalk.article_validation import validate_evidence, validate_passage


def validate_quantity_run(pages: tuple[ArticlePage, ...], run: QuantityRun) -> dict[str, int]:
    """Recheck every witness against current source, then detect omitted/altered observations.

    The replay uses the same disclosed retrieval method. It establishes deterministic
    completeness within that method, not independent precision, recall or interpretation.
    """
    _ = validate_evidence(pages, ())
    lookup = {(p.issue_id, p.page_index, p.layer): p for p in pages}
    for row in run.expressions:
        key = row.source.issue_id, row.source.page_index, row.source.layer
        if key not in lookup:
            raise ArticleError("quantitative expression refers to an unavailable source page")
        for passage in (row.source, row.context, *(cue.source for cue in row.nearby_cues)):
            validate_passage(passage, lookup[key])
    replay = quantitative_expressions(pages, run.settings)
    if replay != run:
        raise ArticleError("quantitative retrieval differs from complete current-source replay")
    return {
        "native_pages": run.layers[0].pages,
        "ocr_pages": run.layers[1].pages,
        "expressions": len(run.expressions),
        "semantic_accuracy_validations": 0,
    }
