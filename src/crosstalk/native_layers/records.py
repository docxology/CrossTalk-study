"""Separate typed observations preserve raw metrics and uncertain wrapper identities."""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from crosstalk.analysis_records import TextMetrics  # noqa: TC001 - Pydantic runtime field.
from crosstalk.models import Digest  # noqa: TC001 - Pydantic runtime field.
from crosstalk.records import PageRecord  # noqa: TC001 - Pydantic runtime field.


class LayerRecord(BaseModel):
    """Finite immutable derivative records; no field changes the source Issue model."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, strict=True, extra="forbid", allow_inf_nan=False
    )


class HandleEvidence(LayerRecord):
    """An independently retained exact-publication linkset, never inferred from wrapper text."""

    handle_url: str = Field(pattern=r"^https://hdl\.handle\.net/10945/[0-9]+$")
    publication_url: str
    request_url: str
    snapshot_path: str
    snapshot_sha256: Digest
    body_sha256: Digest
    catalog_sha256: Digest
    robots_sha256: Digest
    provenance: Literal["retained-exact-publication-signposting", "software-fixture"]


class NativeIdentity(LayerRecord):
    """Independent expected source identity and its explicit acquisition/extraction scope."""

    issue_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,119}$")
    title: str
    issued: str | None
    landing_url: str
    catalog_sha256: Digest
    pdf_sha256: Digest
    page_artifact_sha256: Digest
    total_pdf_pages: int = Field(ge=1, le=100_000)
    extraction_status: Literal["complete", "partial"]
    source_kind: Literal["journal", "software-fixture"]
    handle_evidence: HandleEvidence | None = None


class NativePage(LayerRecord):
    """A parsed physical page plus the hash of its exact retained JSONL line bytes."""

    page: PageRecord
    record_line_sha256: Digest


class LineHash(LayerRecord):
    """Exact native text line including its original line terminator, indexed from zero."""

    line_index: int
    sha256: Digest


class Predicate(LayerRecord):
    """One mechanical condition and the original line indexes supporting the observation."""

    name: str
    passed: bool
    line_indexes: tuple[int, ...] = ()


class WrapperObservation(LayerRecord):
    """An exploratory template match is attribution evidence, not classifier accuracy."""

    rule_revision: Literal["calhoun-wrapper-v1-exploratory"] = "calhoun-wrapper-v1-exploratory"
    page_index: int
    record_line_sha256: Digest
    native_text_sha256: Digest
    line_hashes: tuple[LineHash, ...]
    status: Literal["matched-wrapper", "candidate-review", "no-signature"]
    observed_title: str | None
    observed_uri: str | None
    observed_link_to_item: str | None
    handle_status: Literal[
        "independent-match",
        "independent-conflict",
        "observed-repeated-only",
        "missing-or-inconsistent",
    ]
    predicates: tuple[Predicate, ...]
    review_flags: tuple[str, ...]


class LayerView(LayerRecord):
    """A reversible physical-page selection, with raw and unavailable denominators visible."""

    name: Literal["raw-native", "native-minus-matched-repository-wrapper"]
    included_page_indexes: tuple[int, ...]
    excluded_page_indexes: tuple[int, ...]
    text: TextMetrics
    native_characters: int
    low_text_pages: int
    low_text_fraction: float | None
    rate_status: Literal["available-native-proxy", "zero-native-tokens"]
    exploratory_native_rich: bool


class LayerSettings(LayerRecord):
    """A declared workflow threshold; it is not a validated transcription-quality gate."""

    maximum_low_text_fraction: float = Field(default=0.2, ge=0, le=1)


class IssueLayers(LayerRecord):
    """Raw baseline and paired sensitivity share identical source and scope bindings."""

    identity: NativeIdentity
    observations: tuple[WrapperObservation, ...]
    raw: LayerView
    wrapper_excluded: LayerView
    settings: LayerSettings
    matched_wrapper_pages: int
    observed_extracted_pages: int
    zero_native_body: bool
    accuracy_status: Literal["unmeasured-exploratory-template-rule"] = (
        "unmeasured-exploratory-template-rule"
    )
