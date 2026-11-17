"""Source-bound issue accounting, annual evidence heatmap and normalized index exports."""

from __future__ import annotations

from crosstalk.holdings_exports import (
    article_index_csv,
    coverage_csv,
    coverage_svg,
    holdings_html,
    issues_csv,
)

__all__ = [
    "article_index_csv",
    "build_holdings_report",
    "coverage_csv",
    "coverage_svg",
    "holdings_html",
    "implementation_digest",
    "issues_csv",
]

import hashlib
from pathlib import Path
from typing import Final

from crosstalk.acquisition_lock import project_lock
from crosstalk.holdings_reconcile import reconcile_holdings
from crosstalk.holdings_records import HoldingsError, HoldingsPublication, InputBinding
from crosstalk.holdings_source import load_holdings, recheck_holdings_inputs
from crosstalk.locator_storage import publish_metadata
from crosstalk.models import file_digest, safe_directory

IMPLEMENTATION_FILES: Final = (
    "holdings_parse.py",
    "holdings_exports.py",
    "holdings_records.py",
    "holdings_reconcile.py",
    "holdings_source.py",
    "holdings_report.py",
    "case_files.py",
    "case_records.py",
    "catalog.py",
    "records.py",
    "models.py",
    "locator_storage.py",
    "acquisition_lock.py",
)


def implementation_digest() -> str:
    """Bind actual reconciliation/report/custody dependencies independently of their results."""
    digest = hashlib.sha256()
    for name in IMPLEMENTATION_FILES:
        digest.update(name.encode())
        digest.update(bytes.fromhex(file_digest(Path(__file__).parent / name)))
    return digest.hexdigest()


def build_holdings_report(root: Path) -> HoldingsPublication:
    """Publish a replay-stable immutable bundle under the actual project operation lock."""
    with project_lock(root):
        method = implementation_digest()
        inputs = load_holdings(root)
        run = reconcile_holdings(inputs)
        raw = run.model_dump_json().encode() + b"\n"
        digest = hashlib.sha256(raw).hexdigest()
        directory = f"output/data/holdings/{digest}-{method}"
        payloads = (
            ("run.jsonl", raw),
            ("coverage.csv", coverage_csv(run).encode()),
            ("issues.csv", issues_csv(run).encode()),
            ("article-index.csv", article_index_csv(inputs.article_entries).encode()),
            ("coverage.svg", coverage_svg(run).encode()),
            ("report.html", holdings_html(run).encode()),
        )
        recheck_holdings_inputs(root, inputs)
        artifacts: list[InputBinding] = []
        for name, payload in payloads:
            if len(payload) > 8_000_000:
                raise HoldingsError("holdings report exceeds its finite artifact byte bound")
            path = publish_metadata(safe_directory(root, directory), name, payload)
            artifacts.append(
                InputBinding(
                    path=path.relative_to(root).as_posix(),
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
            )
        recheck_holdings_inputs(root, inputs)
        if implementation_digest() != method:
            raise HoldingsError("holdings implementation changed before report publication")
        return HoldingsPublication(
            directory=directory,
            run_sha256=digest,
            implementation_sha256=method,
            artifacts=tuple(artifacts),
        )
