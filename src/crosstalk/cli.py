"""Command entry points; research behavior lives in importable modules."""

from pathlib import Path
from typing import Annotated, Final

import typer
from rich import print_json

from crosstalk.acquire import download_manifest
from crosstalk.analysis import analyze_corpus
from crosstalk.catalog import import_catalog
from crosstalk.catalog_report import build_catalog_atlas
from crosstalk.corpus_index import build_corpus_index
from crosstalk.corpus_report import write_corpus_report
from crosstalk.dossier_source import render_project_dossier
from crosstalk.extract import extract_corpus
from crosstalk.linguistics import analyze_linguistics
from crosstalk.locator_records import LocatorBounds
from crosstalk.locator_resolution import resolve_catalog_locators
from crosstalk.models import load_manifest
from crosstalk.publisher_catalog import import_publisher_catalog
from crosstalk.publisher_cli import publisher_app
from crosstalk.statistical_analysis import analyze_statistics
from crosstalk.statistical_records import BootstrapSettings
from crosstalk.statistical_visual_report import render_statistical_report
from crosstalk.template_projection import MANUSCRIPT_DIR
from crosstalk.text_index import build_text_index
from crosstalk.text_search import search_pages

app = typer.Typer(no_args_is_help=True, help="CrossTalk literature and visual corpus research.")
app.add_typer(publisher_app, name="publisher")
Root = Annotated[Path, typer.Option(help="CrossTalk project directory.")]
DEFAULT_ROOT: Final = Path()


@app.command("import-catalog")
def catalog(snapshot: Path, root: Root = DEFAULT_ROOT) -> None:
    """Normalize a captured rendered-series catalog, retaining date conflicts."""
    summary = import_catalog(snapshot, root)
    _ = build_catalog_atlas(root)
    print_json(data=summary.model_dump(mode="json"))


@app.command()
def validate(root: Root = DEFAULT_ROOT) -> None:
    """Validate the supplied issue inventory without downloading."""
    issues = load_manifest(root / "data/manifest/issues.jsonl")
    print_json(data={"manifest_records": len(issues), "archive_complete": False})


@app.command("import-publisher")
def publisher(snapshot: Path, root: Root = DEFAULT_ROOT) -> None:
    """Index official publisher cards separately, retaining unverified dates and access gaps."""
    summary = import_publisher_catalog(snapshot, root)
    print_json(data=summary.model_dump(mode="json"))


@app.command()
def download(
    root: Root = DEFAULT_ROOT,
    limit: Annotated[
        int,
        typer.Option(
            min=1, help="Maximum new-work attempts; verified files do not consume this bound."
        ),
    ] = 5,
    delay: Annotated[float, typer.Option(min=10.0, help="Minimum host request interval.")] = 10.0,
    max_seconds: Annotated[
        float, typer.Option(min=1.0, max=240.0, help="Finite new-work network budget.")
    ] = 240.0,
) -> None:
    """Download a bounded batch from the reviewed inventory, respecting robots."""
    summary = download_manifest(
        root / "data/manifest/issues.jsonl", root, limit, delay, max_seconds=max_seconds
    )
    print_json(data=summary.model_dump(mode="json"))


@app.command("resolve")
def resolve(
    root: Root = DEFAULT_ROOT,
    limit: Annotated[int, typer.Option(min=1, max=10_000)] = 10,
    delay: Annotated[float, typer.Option(min=10.0)] = 10.0,
    max_seconds: Annotated[float, typer.Option(min=80.0, max=240.0)] = 240.0,
) -> None:
    """Resolve official item PDF links through documented, permitted Signposting."""
    result = resolve_catalog_locators(
        root, LocatorBounds(limit=limit, delay=delay, max_seconds=max_seconds)
    )
    print_json(data=result.model_dump(mode="json"))


@app.command()
def extract(
    root: Root = DEFAULT_ROOT,
    max_pages: Annotated[
        int, typer.Option(min=1, help="Page bound per issue (hard maximum 500).")
    ] = 200,
) -> None:
    """Extract text, page coordinates, images, and quality flags from local PDFs."""
    summary = extract_corpus(root, max_pages=max_pages)
    print_json(data=summary.model_dump(mode="json"))


@app.command()
def analyze(root: Root = DEFAULT_ROOT) -> None:
    """Generate reproducible exploratory metrics and an HTML evidence report."""
    summary = analyze_corpus(root)
    print_json(data=summary.model_dump(mode="json"))


@app.command()
def linguistics(root: Root = DEFAULT_ROOT) -> None:
    """Measure page-bounded n-grams, diversity windows and repeated-line candidates."""
    summary = analyze_linguistics(root)
    print_json(data=summary.model_dump(mode="json"))


@app.command()
def dossier(
    root: Root = DEFAULT_ROOT,
    revision: Annotated[
        str, typer.Option(help="Known source revision label; exact input hashes are recorded.")
    ] = "Uncommitted working tree; exact input digests recorded",
) -> None:
    """Render a project with a JSON dossier manifest."""
    if any(
        (root / directory / name).is_file()
        for directory in (MANUSCRIPT_DIR, "manuscript")
        for name in ("80_evidence_figures.md", "90_appendix_inventory.md")
    ):
        raise typer.BadParameter(
            "Use docxology/template for the study manuscript. See docs/reproduction/manuscript.md.",
            param_hint="--root",
        )
    summary = render_project_dossier(root, revision)
    print_json(data=summary.model_dump(mode="json"))


@app.command("index")
def index_corpus(root: Root = DEFAULT_ROOT) -> None:
    """Rebuild current catalog and page-text indexes without inventing missing URLs."""
    catalog = build_corpus_index(root)
    text = build_text_index(root)
    report = write_corpus_report(root)
    print_json(
        data={
            "catalog": catalog.model_dump(
                mode="json", exclude={"source_bindings", "missing_inputs"}
            ),
            "page_search": text.model_dump(
                mode="json", exclude={"source_bindings", "skipped_issue_ids"}
            ),
            "skipped_page_search_issues": len(text.skipped_issue_ids),
            "report": str(report),
        }
    )


@app.command("search")
def search(
    query: Annotated[
        str, typer.Argument(help="Literal word terms; all must match one indexed page.")
    ],
    root: Root = DEFAULT_ROOT,
    limit: Annotated[int, typer.Option(min=1, max=100)] = 20,
) -> None:
    """Retrieve current source-grounded PDF pages with bounded excerpts."""
    result = search_pages(root, query, limit)
    print_json(data=result.model_dump(mode="json"))


@app.command()
def statistics(
    root: Root = DEFAULT_ROOT,
    seed: Annotated[int, typer.Option(min=0, max=2**63 - 1)] = 20261105,
    resamples: Annotated[int, typer.Option(min=100, max=10_000)] = 2000,
) -> None:
    """Recompute source-bound descriptions, conditional issue diagnostics and figures."""
    run = analyze_statistics(root, BootstrapSettings(seed=seed, resamples=resamples))
    visual = render_statistical_report(root, run)
    print_json(
        data={
            "issues": len(run.issues),
            "pages": len(run.pages),
            "distinct_assets": run.unique_saved_assets,
            "unavailable_issues": len(run.unavailable),
            "deferred_issues": len(run.deferred_issue_ids),
            "intervals": [interval.model_dump(mode="json") for interval in run.bootstrap],
            "statistics_receipt": "output/reports/statistics.jsonl",
            "report": visual.report_path,
            "figure_count": len(visual.figures),
            "archive_complete": False,
        }
    )
