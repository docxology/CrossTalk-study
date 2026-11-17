"""Declared English retrieval lexicons; all labels require human review."""

import re
from typing import Final

TOKEN: Final = re.compile(r"[^\W\d_]+(?:['\u2019-][^\W\d_]+)*", re.UNICODE)
STOPWORDS: Final = frozenset(
    [
        "the",
        "a",
        "an",
        "of",
        "to",
        "and",
        "in",
        "for",
        "on",
        "with",
        "by",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "as",
        "that",
        "this",
        "it",
        "or",
        "at",
        "not",
        "we",
        "our",
        "they",
        "their",
        "you",
        "your",
        "can",
        "will",
        "have",
        "has",
        "had",
        "been",
        "which",
        "also",
        "more",
        "into",
        "its",
        "these",
        "those",
        "than",
        "such",
        "through",
        "using",
        "use",
        "used",
    ]
)
HEDGES: Final = frozenset(
    [
        "may",
        "might",
        "could",
        "perhaps",
        "possibly",
        "probably",
        "seem",
        "seems",
        "suggest",
        "suggests",
        "approximately",
    ]
)
MODALS: Final = frozenset(
    ["can", "could", "may", "might", "must", "shall", "should", "will", "would"]
)
CATEGORIES: Final = {
    "security-assurance": (
        "security",
        "assurance",
        "vulnerability",
        "cyber",
        "cryptography",
        "threat",
    ),
    "testing-quality": (
        "testing",
        "verification",
        "validation",
        "defect",
        "quality",
        "reliability",
    ),
    "acquisition-management": (
        "acquisition",
        "procurement",
        "management",
        "cost",
        "schedule",
        "contract",
    ),
    "process-agility": ("agile", "scrum", "process", "maturity", "cmmi", "devops"),
    "architecture-engineering": (
        "architecture",
        "requirements",
        "design",
        "model",
        "integration",
        "systems",
    ),
    "data-ai-automation": (
        "data",
        "artificial intelligence",
        "machine learning",
        "automation",
        "algorithm",
    ),
    "people-education": ("education", "training", "team", "human", "leadership", "workforce"),
    "defense-operations": ("defense", "military", "mission", "warfighter", "dod", "operational"),
}
