"""Publisher commands keep their roots, source families and coverage panels separate."""

from pathlib import Path
from typing import Annotated, Final

import typer
from rich import print_json

from crosstalk.publisher_dataset import publisher_dataset
from crosstalk.publisher_download import download_publisher
from crosstalk.publisher_index import extract_publisher, write_publisher_coverage

publisher_app = typer.Typer(no_args_is_help=True, help="Separate official publisher acquisition.")
Root = Annotated[Path, typer.Option(help="Parent CrossTalk project; publisher data stay separate.")]
DEFAULT_ROOT: Final = Path()


@publisher_app.command("download")
def download(
    root: Root = DEFAULT_ROOT,
    limit: Annotated[int, typer.Option(min=1, max=2000)] = 4,
    delay: Annotated[float, typer.Option(min=10.0)] = 10.0,
    max_seconds: Annotated[float, typer.Option(min=1, max=240)] = 240.0,
    failure_limit: Annotated[int, typer.Option(min=1, max=10)] = 3,
) -> None:
    """Acquire only observed public PDF candidates under a fresh exact-host robots policy."""
    run = download_publisher(
        root, limit, delay, max_seconds=max_seconds, consecutive_failure_limit=failure_limit
    )
    print_json(data=run.model_dump(mode="json"))


@publisher_app.command("extract")
def extract(
    root: Root = DEFAULT_ROOT, max_pages: Annotated[int, typer.Option(min=1, max=500)] = 200
) -> None:
    """Extract verified publisher inputs without adding them to the NPS frame."""
    result = extract_publisher(publisher_dataset(root), max_pages)
    print_json(data=result.model_dump(mode="json"))


@publisher_app.command("index")
def index(root: Root = DEFAULT_ROOT) -> None:
    """Rebuild separate candidate-to-PDF/extraction coverage and keep printed dates unknown."""
    result = write_publisher_coverage(publisher_dataset(root))
    print_json(data=result.summary.model_dump(mode="json"))
