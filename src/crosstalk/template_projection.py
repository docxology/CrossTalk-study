"""Hydrate pinned precomputed study inputs for the actual docxology/Template Stage 03 renderer."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from crosstalk.template_inventory import inventory_table, parse_inventory
from crosstalk.template_io import immutable, physical, project_path, read_file, selected, sha256
from crosstalk.template_manifest import parse_manifest
from crosstalk.template_publication import (
    Document,
    bindings_csv,
    projection_lock,
    publish_generated_file,
    publish_manuscript,
)
from crosstalk.template_records import (
    Artifact,
    Binding,
    Digest,
    Manifest,
    ProjectionError,
    ProjectionRequest,
    ProjectionRun,
)
from crosstalk.template_text import (
    Figure,
    Target,
    TokenValue,
    body_figures,
    graphical_frontmatter,
    substitute,
)

MANUSCRIPT_DIR: Final = "docs/manuscript"
IMPLEMENTATION_FILES: Final = (
    "src/crosstalk/__init__.py",
    "src/crosstalk/template_records.py",
    "src/crosstalk/template_io.py",
    "src/crosstalk/template_manifest.py",
    "src/crosstalk/template_inventory.py",
    "src/crosstalk/template_text.py",
    "src/crosstalk/template_publication.py",
    "src/crosstalk/template_projection.py",
    "scripts/z_generate_manuscript_variables.py",
)
REQUIRED_SOURCES: Final = {
    "config.yaml",
    "preamble.md",
    "00_abstract.md",
    "80_evidence_figures.md",
    "90_appendix_inventory.md",
}
MAX_MANUSCRIPT_ENTRIES: Final = 4096
MAX_MANUSCRIPT_FILES: Final = 512
MAX_MANUSCRIPT_FILE_BYTES: Final = 16 * 1024 * 1024
MAX_MANUSCRIPT_BYTES: Final = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class LoadedArtifact:
    """Already checked original bytes are retained until the projection's final source recheck."""

    artifact: Artifact
    raw: bytes


def _source_documents(root: Path) -> tuple[Document, ...]:
    """Select real authored sections, preamble/config and every bibliography; never dossier JSON."""
    source = project_path(root, MANUSCRIPT_DIR)
    paths: list[Path] = []
    size = 0
    with os.scandir(source) as entries:
        for index, entry in enumerate(entries, 1):
            if index > MAX_MANUSCRIPT_ENTRIES:
                raise ProjectionError("native manuscript directory exceeds its entry bound")
            name = entry.name
            if not (
                name in {"config.yaml", "preamble.md"}
                or Path(name).suffix == ".bib"
                or re.fullmatch(r"(?:[0-9]{2}|S[0-9]{2})[_-].+\.md", name)
            ):
                continue
            paths.append(source / name)
            file_size = entry.stat(follow_symlinks=False).st_size
            size += file_size
            if len(paths) > MAX_MANUSCRIPT_FILES:
                raise ProjectionError("native manuscript exceeds its selected file bound")
            if file_size > MAX_MANUSCRIPT_FILE_BYTES or size > MAX_MANUSCRIPT_BYTES:
                raise ProjectionError("native manuscript exceeds its source byte bound")
    if not {path.name for path in paths}.issuperset(REQUIRED_SOURCES):
        raise ProjectionError("required native manuscript sources are absent")
    documents: list[Document] = []
    remaining = MAX_MANUSCRIPT_BYTES
    for path in sorted(paths):
        raw = read_file(path, min(MAX_MANUSCRIPT_FILE_BYTES, remaining))
        remaining -= len(raw)
        documents.append(Document(path.name, raw))
    return tuple(documents)


def _load(root: Path, manifest: Manifest) -> tuple[LoadedArtifact, ...]:
    """Each declared input is hashed; receipt contents are not reinterpreted as scientific truth."""
    loaded: list[LoadedArtifact] = []
    expected: dict[str, Digest] = {}
    total = 0
    for artifact in (
        manifest.inventory,
        *manifest.graphical_abstracts,
        *manifest.figures,
        *manifest.receipts,
    ):
        if artifact.path in expected and expected[artifact.path] != artifact.sha256:
            raise ProjectionError("one artifact path has conflicting expected digests")
        expected[artifact.path] = artifact.sha256
        raw = selected(root, Binding(artifact.path, artifact.sha256))
        total += len(raw)
        if total > 512 * 1024 * 1024:
            raise ProjectionError("selected projection inputs exceed 512 MiB")
        loaded.append(LoadedArtifact(artifact, raw))
    return tuple(loaded)


def _figure_paths(loaded: tuple[LoadedArtifact, ...], manifest_sha: Digest) -> tuple[Figure, ...]:
    """Plan the immutable paths without publishing a partial projection."""
    figures: list[Figure] = []
    for row in loaded:
        if row.artifact.path.startswith("output/figures/"):
            suffix = Path(row.artifact.path).suffix.lower()
            name = row.artifact.key + suffix
            relative = "output/figures/template-study/" + manifest_sha + "/" + name
            figures.append(Figure(row.artifact, "../" + relative.removeprefix("output/")))
    return tuple(figures)


def _publish_figure_registry(root: Path, figures: tuple[Figure, ...]) -> Binding:
    """Expose the selected figure labels and text to Template's validation."""
    registry = {
        "fig:" + figure.source.key: {
            "filename": figure.path.removeprefix("../figures/"),
            "caption": figure.source.caption,
            "alt_text": figure.source.alt,
            "generated_by": "scripts/z_generate_manuscript_variables.py",
        }
        for figure in figures
    }
    raw = (json.dumps(registry, indent=2, ensure_ascii=False) + "\n").encode()
    return publish_generated_file(root, "output/figures/figure_registry.json", raw)


def _hydrate(
    sources: tuple[Document, ...], values: tuple[TokenValue, ...], frontmatter: str
) -> tuple[Document, ...]:
    """Project-resolved config survives Template's refresh; the static preamble has no tokens."""
    documents: list[Document] = []
    for source in sources:
        text = source.raw.decode("utf-8")
        if source.name == "config.yaml":
            text = "# Project-resolved config\n" + substitute(text, values, Target.YAML)
        elif source.name.endswith(".md") and source.name != "preamble.md":
            text = substitute(text, values, Target.MARKDOWN)
        elif source.name == "preamble.md" and "{{" in text:
            raise ProjectionError("preamble must be static because native Template refreshes it")
        documents.append(Document(source.name, text.encode()))
    documents.append(Document("_crosstalk_frontmatter.inc", frontmatter.encode()))
    return tuple(documents)


def _recheck(request: ProjectionRequest, bindings: tuple[Binding, ...]) -> None:
    """Publication cannot silently adopt a changed original, code file or selected manifest."""
    for binding in bindings:
        _ = selected(request.root, binding)
    if sha256(read_file(request.selection.path, 16 * 1024 * 1024)) != request.selection.sha256:
        raise ProjectionError("original manifest changed during projection")


def _projection(request: ProjectionRequest) -> ProjectionRun:
    root = request.root
    manifest_raw = read_file(request.selection.path, 16 * 1024 * 1024)
    if sha256(manifest_raw) != request.selection.sha256:
        raise ProjectionError("manifest differs from the independently supplied expected digest")
    manifest = parse_manifest(manifest_raw)
    loaded = _load(root, manifest)
    sources = _source_documents(root)
    inputs = tuple(Binding(row.artifact.path, row.artifact.sha256) for row in loaded)
    inputs += tuple(Binding(f"{MANUSCRIPT_DIR}/{row.name}", sha256(row.raw)) for row in sources)
    inputs += tuple(
        Binding(path, sha256(read_file(project_path(root, path)))) for path in IMPLEMENTATION_FILES
    )
    framed = "".join(
        row.path + "\0" + row.sha256 + "\n" for row in sorted(inputs, key=lambda b: b.path)
    )
    projection_sha = sha256((request.selection.sha256 + "\n" + framed).encode())
    prefix = "output/data/template-study/" + request.selection.sha256
    inventory_raw = loaded[0].raw
    inventory = parse_inventory(inventory_raw)
    inventory_path = prefix + "/inventory.csv"
    figures = _figure_paths(loaded, request.selection.sha256)
    gas = tuple(figure for figure in figures if figure.source in manifest.graphical_abstracts)
    body = tuple(figure for figure in figures if figure.source in manifest.figures)
    values = tuple(TokenValue(row.key, row.value) for row in manifest.variables)
    values += (
        TokenValue("GA01_PATH", gas[0].path),
        TokenValue("GA01_ALT", gas[0].source.alt),
        TokenValue("BODY_FIGURES", body_figures(body), structural=True),
        TokenValue("INVENTORY_TABLE", inventory_table(inventory, inventory_path), structural=True),
    )
    documents = _hydrate(sources, values, graphical_frontmatter(gas))
    documents += (Document("_template_source_bindings.csv", bindings_csv(inputs)),)
    variables = {row.key: row.value for row in values if not row.structural}
    variable_bytes = (json.dumps(variables, indent=2, ensure_ascii=False) + "\n").encode()
    _recheck(request, inputs)
    manifest_copy = immutable(root, prefix + "/input-manifest.csv", manifest_raw)
    inventory_copy = immutable(root, inventory_path, inventory_raw)
    raw_by_path = {row.artifact.path: row.raw for row in loaded}
    figure_copies = tuple(
        immutable(
            root, "output/" + figure.path.removeprefix("../"), raw_by_path[figure.source.path]
        )
        for figure in figures
    )
    outputs = publish_manuscript(root, documents)
    outputs += (
        publish_generated_file(root, "output/data/manuscript_variables.json", variable_bytes),
        manifest_copy,
        inventory_copy,
    )
    outputs += figure_copies
    outputs += (_publish_figure_registry(root, figures),)
    _recheck(request, inputs)
    record = {
        "schema_version": 1,
        "manifest_sha256": request.selection.sha256,
        "projection_sha256": projection_sha,
        "runtime": sys.version.split()[0],
        "inventory_rows": len(inventory),
        "body_figures": len(body),
        "graphical_abstracts": 4,
        "native_renderer": "docxology/template Stage 03",
        "physical_pages_one_to_four_verified": False,
        "semantic_or_historical_completeness_inferred": False,
        "inputs": [{"path": row.path, "sha256": row.sha256} for row in inputs],
        "outputs": [{"path": row.path, "sha256": row.sha256} for row in outputs],
    }
    version = ".".join(map(str, sys.version_info[:3]))
    receipt = immutable(
        root,
        "output/reports/template-projection/" + projection_sha + "-py" + version + ".json",
        (json.dumps(record, indent=2) + "\n").encode(),
    )
    return ProjectionRun(
        request.selection.sha256,
        projection_sha,
        len(inventory),
        len(body),
        inputs,
        (*outputs, receipt),
    )


def generate_projection(request: ProjectionRequest) -> ProjectionRun:
    """Format exact precomputed inputs; caller supplies real admission and a source-code freeze."""
    physical(request.root)
    if not request.root.is_dir():
        raise ProjectionError("selected project root is unavailable")
    with projection_lock(request.root):
        return _projection(request)
