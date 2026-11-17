"""Cluster memberships, missing pixel sources and per-pixel denominators stay distinct."""

from __future__ import annotations

import math
from collections import Counter
from typing import Literal

from pydantic import Field, model_validator

from crosstalk.atlas_records import (
    ArtifactBinding,
    Identifier,
    PageImage,
    PageTransform,
    PixelSettings,
)
from crosstalk.study_language_records import Digest, Record, StudyError

AssignmentRole = Literal["train", "projected-fit-issue", "heldout-issue"]


class GhostMember(Record):
    """A supplied cluster assignment; no missing page is assigned by this aggregation layer."""

    issue_id: Identifier
    pdf_sha256: Digest
    page_index: int = Field(ge=0)
    assignment_role: AssignmentRole
    page: PageImage | None
    unavailable_reason: str | None = Field(default=None, min_length=1, max_length=1000)

    @property
    def page_key(self) -> str:
        """Use the upstream physical-page key, not a thumbnail hash or printed folio."""
        return f"{self.pdf_sha256}:{self.page_index}"

    @model_validator(mode="after")
    def pixel_identity(self) -> GhostMember:
        """Missing pixels require a reason; present pixels must belong to this assignment."""
        if (self.page is None) != (self.unavailable_reason is not None):
            raise StudyError("ghost pixel eligibility must distinguish present and unavailable")
        if self.page is not None and (
            self.page.issue_id != self.issue_id or self.page.page_key != self.page_key
        ):
            raise StudyError("ghost pixel source crosses its assigned physical-page identity")
        return self


class GhostPlan(Record):
    """Source-bound cluster input, not cluster discovery or a semantic page-type label."""

    cluster_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,59}$")
    clustering_receipt: ArtifactBinding
    source_frame: ArtifactBinding
    upstream_frame_exclusions: ArtifactBinding
    aggregation_runtime: ArtifactBinding
    clustering_method_note: str = Field(min_length=1, max_length=1600)
    selection_note: str = Field(min_length=1, max_length=1600)
    members: tuple[GhostMember, ...] = Field(min_length=1, max_length=30_000)
    representative_page_keys: tuple[str, ...] = Field(min_length=1, max_length=8)
    representative_basis: str = Field(min_length=1, max_length=1000)
    weighting: Literal["equal-page", "equal-issue"]
    pixels: PixelSettings = PixelSettings()
    dark_threshold: int = Field(default=245, ge=1, le=255)
    edge_threshold: int = Field(default=24, ge=1, le=255)
    maximum_pixel_contributions: int = Field(default=50_000_000, ge=64, le=200_000_000)
    edge_operator: Literal["max(abs(right-center),abs(down-center)); all three pixels observed"] = (
        "max(abs(right-center),abs(down-center)); all three pixels observed"
    )

    @model_validator(mode="after")
    def membership(self) -> GhostPlan:
        """Reject aliases and repeated assignments; missingness does not create a cluster."""
        keys = {member.page_key for member in self.members}
        if len(keys) != len(self.members):
            raise StudyError("ghost membership repeats a physical PDF page")
        if (
            len(set(self.representative_page_keys)) != len(self.representative_page_keys)
            or not set(self.representative_page_keys) <= keys
        ):
            raise StudyError("ghost representatives must be distinct supplied cluster members")
        ids: dict[str, str] = {}
        pdfs: dict[str, str] = {}
        bases: set[str] = set()
        renderers: set[str] = set()
        for member in self.members:
            if ids.setdefault(member.issue_id, member.pdf_sha256) != member.pdf_sha256:
                raise StudyError("ghost issue refers to conflicting physical PDFs")
            if pdfs.setdefault(member.pdf_sha256, member.issue_id) != member.issue_id:
                raise StudyError("ghost physical PDF aliases require prior reconciliation")
            if member.page is not None:
                bases.add(member.page.image_basis)
                renderers.add(member.page.rendering_identity)
        if len(bases) > 1 or len(renderers) > 1:
            raise StudyError(
                "ghost aggregation cannot silently mix image bases or rendering epochs"
            )
        available = sum(member.page is not None for member in self.members)
        if available * self.pixels.width * self.pixels.height > self.maximum_pixel_contributions:
            raise StudyError(
                "ghost normalization exceeds its declared pixel-contribution work bound"
            )
        return self


class GhostIssueWeight(Record):
    """The eligible-page denominator is explicit for each issue's contribution."""

    issue_id: str
    assigned_pages: int = Field(ge=1)
    eligible_pages: int = Field(ge=0)
    per_page_weight: float | None = Field(default=None, gt=0)


class GhostMaps(Record):
    """Population descriptors of supplied pixels; these are not uncertainty intervals."""

    width: int = Field(ge=1)
    height: int = Field(ge=1)
    mean_gray: tuple[float | None, ...]
    population_variance: tuple[float | None, ...]
    dark_fraction: tuple[float | None, ...]
    edge_fraction: tuple[float | None, ...]
    support_weight: tuple[float, ...]
    edge_support_weight: tuple[float, ...]
    page_support: tuple[int, ...]
    edge_page_support: tuple[int, ...]

    @model_validator(mode="after")
    def finite_denominators(self) -> GhostMaps:
        """Unobserved padded cells stay null, never zero-valued gray or occupancy observations."""
        rows = (
            self.mean_gray,
            self.population_variance,
            self.dark_fraction,
            self.edge_fraction,
            self.support_weight,
            self.edge_support_weight,
            self.page_support,
            self.edge_page_support,
        )
        if any(len(row) != self.width * self.height for row in rows):
            raise StudyError("ghost map dimensions disagree with their per-pixel arrays")
        for index, weight in enumerate(self.support_weight):
            if (
                weight < 0
                or self.edge_support_weight[index] < 0
                or self.page_support[index] < 0
                or self.edge_page_support[index] < 0
            ):
                raise StudyError("ghost support cannot be negative")
            observed = weight > 0
            values = (
                self.mean_gray[index],
                self.population_variance[index],
                self.dark_fraction[index],
            )
            if (
                any((value is not None) != observed for value in values)
                or (self.page_support[index] > 0) != observed
            ):
                raise StudyError("ghost value presence differs from its observed pixel denominator")
            gray, variance, dark = values
            if observed and (
                gray is None
                or variance is None
                or dark is None
                or not 0 <= gray <= 255
                or not 0 <= variance <= 16_256.250001
                or not 0 <= dark <= 1
            ):
                raise StudyError("ghost gray/variance/occupancy is outside its bounded scale")
            edge_observed = self.edge_support_weight[index] > 0
            edge = self.edge_fraction[index]
            if (edge is not None) != edge_observed or (
                self.edge_page_support[index] > 0
            ) != edge_observed:
                raise StudyError("ghost edge presence differs from its three-pixel support")
            if edge is not None and not 0 <= edge <= 1:
                raise StudyError("ghost edge fraction is outside its own denominator")
            if (
                self.edge_page_support[index] > self.page_support[index]
                or self.edge_support_weight[index] > weight + 1e-9
            ):
                raise StudyError("edge support exceeds whole-pixel support")
        return self


class GhostAggregate(Record):
    """A reproducible descriptive stack with all membership and weighting decisions retained."""

    method_version: Literal["visual-atlas-ghost-1"] = "visual-atlas-ghost-1"
    implementation_sha256: Digest
    input_plan_sha256: Digest
    plan: GhostPlan
    eligible_source_pages: int = Field(ge=0)
    eligible_issues: int = Field(ge=0)
    unavailable_page_keys: tuple[str, ...]
    total_source_weight: float = Field(ge=0)
    issue_weights: tuple[GhostIssueWeight, ...]
    transforms: tuple[PageTransform, ...]
    maps: GhostMaps
    pillow_version: str
    python_version: str
    semantic_genre: Literal["unclassified"] = "unclassified"
    independent_sample_inference: Literal[False] = False

    @model_validator(mode="after")
    def result_scope(self) -> GhostAggregate:
        """Counts and transformations cannot contradict the supplied membership/weighting frame."""
        eligible = tuple(
            sorted((m for m in self.plan.members if m.page is not None), key=lambda m: m.page_key)
        )
        counts = Counter(member.issue_id for member in eligible)
        assigned = Counter(member.issue_id for member in self.plan.members)
        if self.eligible_source_pages != len(eligible) or self.eligible_issues != len(counts):
            raise StudyError("ghost eligible counts differ from declared pixel membership")
        if self.unavailable_page_keys != tuple(
            sorted(m.page_key for m in self.plan.members if m.page is None)
        ):
            raise StudyError("ghost unavailable identities differ from the declared missing frame")
        expected = tuple(
            GhostIssueWeight(
                issue_id=issue,
                assigned_pages=assigned[issue],
                eligible_pages=counts[issue],
                per_page_weight=(
                    1.0 if self.plan.weighting == "equal-page" else 1.0 / counts[issue]
                )
                if counts[issue]
                else None,
            )
            for issue in sorted(assigned)
        )
        if self.issue_weights != expected:
            raise StudyError(
                "ghost issue weights differ from the declared eligible-page denominators"
            )
        weights = {row.issue_id: row.per_page_weight for row in expected}
        total = math.fsum(weights[m.issue_id] or 0.0 for m in eligible)
        if self.total_source_weight != total or (self.maps.width, self.maps.height) != (
            self.plan.pixels.width,
            self.plan.pixels.height,
        ):
            raise StudyError("ghost weight/canvas summary contradicts its actual plan")
        if tuple(t.page_key for t in self.transforms) != tuple(m.page_key for m in eligible):
            raise StudyError("ghost normalization transformations omit or repeat eligible pages")
        if any(support > self.eligible_source_pages for support in self.maps.page_support) or any(
            weight > total + 1e-8 for weight in self.maps.support_weight
        ):
            raise StudyError("ghost pixel support exceeds the available source-frame denominator")
        return self
