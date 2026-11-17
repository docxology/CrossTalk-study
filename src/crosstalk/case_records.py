"""Strict curated case observations and current source bindings without truth claims."""

from __future__ import annotations

import re
from datetime import date  # noqa: TC003 -- Pydantic resolves this field's runtime schema.
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Key = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,119}$")]
Text = Annotated[str, Field(min_length=1, max_length=20_000)]
Version = Literal["2", "3"]


class CaseError(ValueError):
    """A ledger or source failure that prevents current case publication."""


class Record(BaseModel):
    """Frozen finite data; hashes establish custody rather than scholarly agreement."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True, strict=True, extra="forbid", allow_inf_nan=False
    )


class Evidence(Record):
    """One reviewed physical journal page; artifact/render hashes retain historical meaning."""

    key: Key
    issue_id: Key
    catalog_title: Text
    source_url: Text
    source_pdf_sha256: Digest
    page_index: int = Field(ge=0, le=499)
    reviewed_native_artifact_sha256: Digest
    reviewed_extractor_version: Version
    page_text_sha256: Digest
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    printed_folio: Text | None
    region_roles: Annotated[tuple[Text, ...], Field(min_length=1, max_length=30)]
    inspection: Literal["native-text-only", "native-text-and-render"]
    review_render_sha256: Digest | None
    source_family: Literal["calhoun-nps"] = "calhoun-nps"

    @model_validator(mode="after")
    def inspection_provenance(self) -> Evidence:
        """Keep native-only inspection distinct from recorded historical rendering."""
        if (self.inspection == "native-text-only") != (self.review_render_sha256 is None):
            raise CaseError("inspection mode and historical rendering identity disagree")
        if len(set(self.region_roles)) != len(self.region_roles):
            raise CaseError("duplicate region role in one case page")
        if not re.fullmatch(r"ct-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", self.issue_id):
            raise CaseError("case evidence requires an NPS catalog publication identity")
        if self.source_url != "https://calhoun.nps.edu/entities/publication/" + self.issue_id[3:]:
            raise CaseError("case source URL does not identify its exact NPS publication")
        return self


class Claim(Record):
    """A bounded interpretation with explicit evidence references and scope."""

    key: Key
    evidence_keys: Annotated[tuple[Key, ...], Field(min_length=1, max_length=100)]
    statement: Text
    claim_kind: Literal[
        "source-observation-and-method-implication",
        "bounded-cross-case-interpretation",
        "bounded-qualitative-visual-interpretation",
        "source-internal-label-discrepancy",
        "source-internal-date-label-discrepancy",
    ]
    scope: Text


class Ledger(Record):
    """The curator's declared review process; no independent-review status is inferred."""

    schema_version: Literal[1]
    review_process: Text
    selection: Text
    reviewed_at: date
    admission_rule: Text
    evidence: Annotated[tuple[Evidence, ...], Field(min_length=1, max_length=500)]
    claims: Annotated[tuple[Claim, ...], Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def identities(self) -> Ledger:
        """Refuse duplicate anchors/pages and claims with ambiguous or dangling references."""
        keys = [row.key for row in (*self.evidence, *self.claims)]
        if len(keys) != len(set(keys)):
            raise CaseError("duplicate case ledger key")
        pages = [(row.issue_id, row.page_index) for row in self.evidence]
        if len(pages) != len(set(pages)):
            raise CaseError("duplicate issue/physical-page evidence unit")
        evidence = {row.key for row in self.evidence}
        for claim in self.claims:
            if len(claim.evidence_keys) != len(set(claim.evidence_keys)):
                raise CaseError("duplicate evidence reference within a claim")
            if not set(claim.evidence_keys) <= evidence:
                raise CaseError("dangling claim evidence reference")
        return self


class InputBinding(Record):
    """A current project-relative source file returned by native-only admission."""

    path: str
    sha256: Digest


class AdmittedEvidence(Record):
    """Current custody and unchanged audit identities; interpretation remains declared."""

    reviewed: Evidence
    current_native_artifact_sha256: Digest
    current_extractor_version: Version
    compatibility: Literal["exact-reviewed-native-artifact", "native-text-geometry-v2-to-v3"]


class ValidatedCases(Record):
    """All case sources admitted together; the result does not validate the claims' meaning."""

    ledger: Ledger
    ledger_path: str
    ledger_sha256: Digest
    native_bindings: tuple[InputBinding, ...]
    evidence: tuple[AdmittedEvidence, ...]
    human_review_verified: None = None
    interpretation_truth_verified: None = None
    limitations: tuple[str, ...] = (
        "Source hashes and software tests do not validate interpretation or scholarly agreement",
        "The ledger retains its declared purposive selection and single AI-assisted review process",
        "Reviewed native-artifact and render hashes are historical audit identities",
        "Version 2 to 3 compatibility requires exact PDF, page, text and geometry identities",
        "No article-wide appraisal, journal prevalence or corpus accuracy is inferred",
    )
