"""Display-only lexical screens and issue-support diagnostics; no semantic classification."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field, model_validator

from crosstalk.study_language_records import (
    Digest,
    Identifier,
    Layer,
    Record,
    StudyError,
    TermProfile,
)

DISPLAY_STOPLIST: Final = tuple(
    (
        ("a about above after again against all also a" + "m an and any are as at be because been ")
        + (
            "before being below between both but by can c"
            + "ould did do does doing down during each few "
        )
        + (
            "for from further had has have having he her "
            + "here hers herself him himself his how i if "
        )
        + (
            "in into is it its itself just may me might m"
            + "ore most must my myself no nor not now of "
        )
        + (
            "off on once only or other our ours ourselves"
            + " out over own same she should so some such "
        )
        + (
            "than that the their theirs them themselves t"
            + "hen there these they this those through to "
        )
        + (
            "too under until up us very was we were what "
            + "when where which while who whom why will "
        )
        + "with would you your yours yourself yourselves"
    ).split()
)


class ContentSettings(Record):
    """Freeze a display screen of single already-normalized tokens; source counts are unchanged."""

    stoplist: tuple[str, ...] = DISPLAY_STOPLIST
    minimum_characters: int = Field(default=3, ge=1, le=50)
    maximum_display_characters: int = Field(default=28, ge=3, le=100)
    minimum_issue_support: int = Field(default=5, ge=1, le=10_000)
    minimum_pair_count: int = Field(default=10, ge=1)
    displayed_terms: int = Field(default=30, ge=1, le=100)
    displayed_pairs: int = Field(default=30, ge=1, le=100)
    maximum_units: int = Field(default=30_000, ge=1, le=100_000)
    maximum_tokens: int = Field(default=20_000_000, ge=1, le=50_000_000)
    maximum_distinct_pairs: int = Field(default=1_000_000, ge=1, le=2_000_000)

    @model_validator(mode="after")
    def coherent_display(self) -> ContentSettings:
        """Refuse contradictory display lengths and repeated stoplist entries."""
        if self.minimum_characters > self.maximum_display_characters or len(self.stoplist) != len(
            set(self.stoplist)
        ):
            raise StudyError("content display lengths or stoplist entries are inconsistent")
        return self


class ContentTerm(Record):
    """A complete-frequency term and descriptive concentration among its source issues."""

    frequency: TermProfile
    maximum_issue_count_share: float = Field(gt=0, le=1)
    maximum_issue_ids: tuple[Identifier, ...] = Field(min_length=1)


class PairIssueCounts(Record):
    """Every pair-eligible issue retains its actual count and full positional opportunities."""

    issue_id: Identifier
    count: int = Field(ge=0)
    left_opportunities: int = Field(ge=0)
    right_opportunities: int = Field(ge=0)
    pair_opportunities: int = Field(gt=0)


class SupportedPair(Record):
    """Retain within-unit pair support and descriptive issue-deletion ranges."""

    left: str
    right: str
    count: int = Field(gt=0)
    left_opportunities: int = Field(gt=0)
    right_opportunities: int = Field(gt=0)
    total_pair_opportunities: int = Field(gt=0)
    per_1000_pair_opportunities: float = Field(gt=0)
    log_dice: float
    observed_issues: int = Field(gt=0)
    eligible_pair_issues: int = Field(gt=0)
    maximum_issue_count_share: float = Field(gt=0, le=1)
    deletion_eligible_issues: int = Field(ge=0)
    leave_one_issue_out_log_dice_min: float | None
    leave_one_issue_out_log_dice_max: float | None
    issue_counts: tuple[PairIssueCounts, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def support_consistency(self) -> SupportedPair:
        """Reject contradictory support, complete positional counts and missing deletion ranges."""
        peers = self.issue_counts
        if (
            len({row.issue_id for row in peers}) != len(peers)
            or len(peers) != self.eligible_pair_issues
            or sum(row.count > 0 for row in peers) != self.observed_issues
            or (
                sum(row.count for row in peers),
                sum(row.left_opportunities for row in peers),
                sum(row.right_opportunities for row in peers),
                sum(row.pair_opportunities for row in peers),
            )
            != (
                self.count,
                self.left_opportunities,
                self.right_opportunities,
                self.total_pair_opportunities,
            )
            or any(
                row.count
                > min(row.left_opportunities, row.right_opportunities, row.pair_opportunities)
                for row in peers
            )
        ):
            raise StudyError("pair issue support or opportunity counts disagree")
        bounds = (self.leave_one_issue_out_log_dice_min, self.leave_one_issue_out_log_dice_max)
        if self.deletion_eligible_issues != sum(row.count < self.count for row in peers):
            raise StudyError("pair deletion-eligible issue count disagrees")
        if self.deletion_eligible_issues == 0:
            valid = bounds == (None, None)
        else:
            valid = bounds[0] is not None and bounds[1] is not None and bounds[0] <= bounds[1]
        if not valid:
            raise StudyError("pair deletion range and eligible count disagree")
        return self


class ContentLayer(Record):
    """Native and OCR diagnostics retain separate tokens, pairs and eligible issue denominators."""

    layer: Layer
    supplied_units: int = Field(ge=0)
    tokens: int = Field(ge=0)
    positive_token_issues: int = Field(ge=0)
    pair_opportunities: int = Field(ge=0)
    eligible_pair_issues: int = Field(ge=0)
    vocabulary: int = Field(ge=0)
    distinct_pairs: int = Field(ge=0)
    screened_terms: int = Field(ge=0)
    screened_pairs: int = Field(ge=0)
    terms: tuple[ContentTerm, ...]
    pairs: tuple[SupportedPair, ...]


class ContentRun(Record):
    """Finite descriptive displays, bound to the full unchanged supplied source-unit frame."""

    method_version: Literal["study-content-1"] = "study-content-1"
    implementation_sha256: Digest
    unit_frame_sha256: Digest
    settings: ContentSettings
    layers: tuple[ContentLayer, ...]
    count_policy: str = (
        "All supplied normalized tokens and within-un"
        + "it pairs are counted before display screenin"
        + "g."
    )
    pair_policy: str = (
        ("Adjacent pairs restart at every supplied pag" + "e/region; no page-crossing pairs. ")
        + (
            "LogDice uses full positional endpoint counts"
            + ". Deletion ranges remove each eligible "
        )
        + ("issue once; they are descriptive sensitivity" + " ranges, not confidence intervals.")
    )
    interpretation: str = (
        "The explicit display stoplist and length/sup"
        + "port screen do not establish content-word, "
    ) + ("topic, syntactic, genre or accuracy labels. " + "Native and accepted OCR are separate.")
