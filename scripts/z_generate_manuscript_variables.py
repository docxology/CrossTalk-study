# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Stage the selected study inputs and hydrate the manuscript for Template."""

from __future__ import annotations

import os
import sys
from argparse import ArgumentParser
from io import BytesIO
from pathlib import Path
from typing import Final
from zipfile import ZipFile

ROOT: Final = Path(__file__).resolve().parents[1]
RELEASE_KIT: Final = "publication/CrossTalk-v0.1.0-preprint-build-inputs.zip"
RELEASE_KIT_SHA: Final = "2961ce6017517f34c0fdd64fd5380cd67e00bec7163327fb7606436fd593c181"
RELEASE_MANIFEST: Final = "docs/reproduction/template-render-inputs-v0.1.0.csv"
RELEASE_MANIFEST_SHA: Final = "c2b22fc71fa470c3bd0136334975d210be32fd86eb872d549578c52656c17056"

sys.path.insert(0, str(ROOT / "src"))

from crosstalk.template_io import (  # noqa: E402 -- Project source precedes analysis environments.
    digest,
    immutable,
    selected,
    sha256,
)
from crosstalk.template_manifest import parse_manifest  # noqa: E402
from crosstalk.template_projection import generate_projection  # noqa: E402
from crosstalk.template_records import (  # noqa: E402
    Binding,
    ManifestSelection,
    ProjectionError,
    ProjectionRequest,
)


def release_selection() -> ManifestSelection:
    """Materialize only the verified inputs listed in the published release manifest."""
    manifest_binding = Binding(RELEASE_MANIFEST, digest(RELEASE_MANIFEST_SHA))
    manifest = parse_manifest(selected(ROOT, manifest_binding))
    kit_binding = Binding(RELEASE_KIT, digest(RELEASE_KIT_SHA))
    artifacts = (
        manifest.inventory,
        *manifest.graphical_abstracts,
        *manifest.figures,
        *manifest.receipts,
    )
    with ZipFile(BytesIO(selected(ROOT, kit_binding))) as kit:
        for artifact in artifacts:
            raw = kit.read(artifact.path)
            if sha256(raw) != artifact.sha256:
                msg = f"Release input checksum differs for {artifact.path}"
                raise ProjectionError(msg)
            _ = immutable(ROOT, artifact.path, raw)
    return ManifestSelection(ROOT / manifest_binding.path, manifest_binding.sha256)


def explicit_selection() -> ManifestSelection:
    """Bind a caller-supplied manifest to its independently reviewed digest."""
    path = os.environ.get("CROSSTALK_TEMPLATE_MANIFEST")
    expected = os.environ.get("CROSSTALK_TEMPLATE_MANIFEST_SHA256")
    if not path or not expected:
        raise ProjectionError(
            "explicit manifest path and independently supplied SHA-256 are required"
        )
    return ManifestSelection(Path(path), digest(expected))


def main() -> None:
    """Hydrate a selected manuscript for the pinned renderer."""
    parser = ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "--release", action="store_true", help="Use the bundled study edition 0.1.0 inputs."
    )
    args = parser.parse_args()
    selection = release_selection() if args.release else explicit_selection()
    run = generate_projection(ProjectionRequest(ROOT, selection))
    _ = sys.stdout.write(
        f"Native Template inputs: projection={run.projection_sha256} "
        + f"source_rows={run.inventory_rows} body_figures={run.body_figures}; "
        + "PDF rendering pending\n"
    )


if __name__ == "__main__":
    main()
