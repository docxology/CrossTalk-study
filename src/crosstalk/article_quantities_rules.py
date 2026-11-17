"""Declared raw English/unit forms avoid normalization and preserve source character offsets."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from crosstalk.article_quantities_records import CueForm, QuantityForm

FORMS: Final[tuple[QuantityForm, ...]] = (
    "percent-form",
    "percentage-point-form",
    "fold-form",
    "colon-form",
    "ratio-word-form",
    "count-unit-form",
)
NUMBER: Final = (
    r"[-+\u2212]?(?:\d{1,3}(?:,\d{3}){1,4}(?:\.\d{1,8})?|" + r"\d{1,15}(?:\.\d{1,8})?|\.\d{1,8})"
)
SPACE: Final = r"[ \t\r\n]{0,4}"
VALUES: Final = NUMBER + r"(?:(?:[ \t]*[\u2013—-][ \t]*|[ \t]+to[ \t]+)" + NUMBER + r")?"
# These explicitly marked powers/scientific forms are excluded as a whole so
# neither their mantissa-times sign nor their exponent becomes a quantity form.
EXPONENT_NOTATION: Final = re.compile(
    r"(?<![\w.,+\u2212\u2013—-])"
    + rf"(?:{NUMBER}[ \t\r\n]{{0,8}}(?:[\u00d7x*·]|\\times)[ \t\r\n]{{0,8}})?"
    + rf"{NUMBER}[ \t\r\n]{{0,8}}"
    + rf"(?:\^[ \t]{{0,4}}(?:\{{[ \t]{{0,4}}{NUMBER}[ \t]{{0,4}}\}}|{NUMBER})|[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+)",
    re.IGNORECASE | re.ASCII,
)
POINT_UNIT: Final = r"(?:percentage[ -]points?|percent[ -]points?)"
PERCENT_UNIT: Final = r"(?:%|\uff05|percent(?:age)?|per[ \t]+cent)"
COUNT_UNIT: Final = (
    r"(?:person[ -]hours?|person[ -]months?|staff[ -]hours?|function[ -]points?|"
    + r"lines[ \t]+of[ \t]+code|test[ -]cases?|SLOC|LOC|hours?|minutes?|seconds?|"
    + r"days?|weeks?|months?|years?|projects?|organi[sz]ations?|people|participants?|"
    + r"releases?|deliver(?:y|ies)|applications?|tests?|defects?|errors?)"
)
EXPRESSION: Final = re.compile(
    r"(?<![\w.,+\u2212\u2013—-])(?:"
    + rf"(?P<points>(?P<points_value>{VALUES}){SPACE}(?P<points_unit>{POINT_UNIT}))(?![\w%])"
    + rf"|(?P<percent>(?P<percent_value>{VALUES}){SPACE}(?P<percent_unit>{PERCENT_UNIT}))(?![\w%])"
    + rf"|(?P<fold>(?P<fold_value>{VALUES})[ \t-]*(?P<fold_unit>times|fold|x|\u00d7))(?!\w)"
    + r"|(?P<ratio_word>(?P<ratio_word_unit>ratio)[ \t]+(?:of[ \t]+)?"
    + rf"(?P<ratio_word_value>{VALUES}))(?!\w|[.,]\d)"
    + rf"|(?P<count>(?P<count_value>{VALUES}){SPACE}(?P<count_unit>{COUNT_UNIT}))(?!\w)"
    + rf"|(?P<colon>(?P<colon_value>{NUMBER}[ \t]*:[ \t]*{NUMBER}))(?!\w|[.,]\d)"
    + r")",
    re.IGNORECASE | re.ASCII,
)
GROUPS: Final[tuple[tuple[str, QuantityForm], ...]] = (
    ("points", "percentage-point-form"),
    ("percent", "percent-form"),
    ("fold", "fold-form"),
    ("ratio_word", "ratio-word-form"),
    ("count", "count-unit-form"),
    ("colon", "colon-form"),
)
CUE_SPECS: Final[tuple[tuple[CueForm, str], ...]] = (
    (
        "assumption-or-estimation-word",
        r"\b(?:assum\w*|hypothetic\w*|suppos\w*|would|if|estimat\w*)\b",
    ),
    ("model-or-simulation-word", r"\b(?:model\w*|simulat\w*)\b"),
    ("observation-word", r"\b(?:measur\w*|observ\w*|recorded|found|reported)\b"),
    ("qualification-word", r"\b(?:however|limit\w*|uncertain\w*|may|might|caution\w*|approx\w*)\b"),
    ("future-or-proposal-word", r"\b(?:will|planned|propos\w*|future)\b"),
    (
        "attribution-or-source-word",
        r"\b(?:according[ \t]+to|cited|reported[ \t]+by|survey\w*|interview\w*)\b",
    ),
    (
        "comparison-word",
        r"\b(?:versus|compared|before|after|increase\w*|decrease\w*|reduc\w*|improv\w*)\b",
    ),
    (
        "statistical-word",
        r"\b(?:p[ -]value|confidence[ \t]+interval|standard[ \t]+deviation|"
        + r"correlation|variance|significan\w*)\b",
    ),
)
CUES: Final[tuple[tuple[CueForm, re.Pattern[str]], ...]] = tuple(
    (form, re.compile(expression, re.IGNORECASE | re.ASCII)) for form, expression in CUE_SPECS
)
SCOPE: Final = (
    "Raw ASCII-number English/unit forms; exact original Unicode-code-point offsets, "
    + "no NFKC, numeric conversion, arithmetic or source-text deduplication. Leftmost "
    + "nonoverlapping expressions; percentage-point alternatives precede percent. "
    + "Ranges retain their literal text. Colon notation can be time, aspect or other notation. "
    + "Number forms allow at most 15 integer digits and 8 fractional digits. "
    + "Scientific notation, decimal-comma notation, written-out numbers, unsupported units, "
    + "cross-page expressions and interrupted/hyphenated source words are outside scope. "
    + "Explicit caret/superscript powers, optionally preceded by a mantissa and multiplication "
    + "marker, are excluded before matching; no mantissa-fold or exponent-unit tail is counted. "
    + "Nearby cues are words in a fixed character context, not attached or negation-resolved "
    + "evidence labels. Repeated pull quotes, code, references, ads and wrappers remain unless "
    + "an independently recorded upstream selection removes them. No semantic precision, "
    + "recall, causal interpretation, effect estimate or rate denominator is inferred."
)
