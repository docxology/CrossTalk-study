"""Robots wildcard policy parsing shared by sequential archive readers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import unquote, urlsplit

from crosstalk.models import AcquisitionError

USER_AGENT: Final = "CrossTalkResearch/0.1"


def host_key(url: str) -> str:
    """Share pacing across case aliases and explicit default HTTPS ports."""
    return urlsplit(url).netloc.lower().removesuffix(":443")


@dataclass(frozen=True, slots=True)
class RobotsPolicy:
    """Relevant robots rules selected for this crawler's user agent."""

    rules: tuple[tuple[bool, str], ...]
    delay: float = 10.0

    def permits(self, url: str) -> bool:
        """Apply wildcard rules, longest-match precedence and allow ties."""
        parsed = urlsplit(url)
        target = unquote(parsed.path + (f"?{parsed.query}" if parsed.query else ""))
        matches: list[tuple[int, bool]] = []
        for allowed, pattern in self.rules:
            anchored = pattern.endswith("$")
            body = pattern[:-1] if anchored else pattern
            expression = "^" + ".*".join(re.escape(part) for part in body.split("*"))
            if re.search(expression + ("$" if anchored else ""), target):
                matches.append((len(body.replace("*", "")), allowed))
        return max(matches, default=(0, True))[1]


def parse_robots(text: str) -> RobotsPolicy:
    """Preserve crawler-specific groups and Calhoun's wildcard path restrictions."""
    groups: list[tuple[tuple[str, ...], RobotsPolicy]] = []
    agents: list[str] = []
    rules: list[tuple[bool, str]] = []
    delay = 10.0
    directives_started = False
    for line in [*text.splitlines(), "User-agent: __end__"]:
        key, separator, raw_value = line.split("#", 1)[0].partition(":")
        if not separator:
            continue
        value = raw_value.strip()
        key = key.strip().lower()
        if key == "user-agent":
            if directives_started:
                groups.append((tuple(agents), RobotsPolicy(tuple(rules), delay)))
                agents, rules, delay = [], [], 10.0
                directives_started = False
            agents.append(value.lower())
        elif agents:
            directives_started = True
            if key in {"allow", "disallow"} and value:
                rules.append((key == "allow", value))
            elif key == "crawl-delay":
                try:
                    parsed_delay = float(value)
                except ValueError as error:
                    raise AcquisitionError("invalid robots crawl-delay") from error
                if not 0 <= parsed_delay < float("inf"):
                    raise AcquisitionError("invalid robots crawl-delay")
                delay = max(10.0, parsed_delay)
    ranked = [
        (
            max(
                (len(name) for name in names if name != "*" and name in USER_AGENT.lower()),
                default=0,
            ),
            policy,
        )
        for names, policy in groups
    ]
    longest = max((length for length, _policy in ranked), default=0)
    selected = (
        [policy for length, policy in ranked if length == longest]
        if longest
        else [policy for names, policy in groups if "*" in names]
    )
    return RobotsPolicy(
        tuple(rule for policy in selected for rule in policy.rules),
        max((p.delay for p in selected), default=10.0),
    )
