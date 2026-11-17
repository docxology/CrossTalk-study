"""Method upgrades cannot revive stale index flags with otherwise unchanged source bytes."""

from __future__ import annotations

import importlib.util
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

import crosstalk.index_implementation as source
from crosstalk.corpus_index import build_corpus_index
from crosstalk.extract import extract_corpus
from crosstalk.index_implementation import (
    INDEX_IMPLEMENTATION_FILES,
    index_implementation_sha256,
)
from crosstalk.index_read import read_corpus_index
from crosstalk.models import AcquisitionError
from crosstalk.records import write_records
from crosstalk.text_index import build_text_index
from tests.test_corpus_index import catalog_at, register_pdf


@pytest.fixture
def method_project(tmp_path: Path) -> Path:
    ids = catalog_at(tmp_path)
    issue = register_pdf(tmp_path, ids[0])
    write_records(tmp_path / "data/manifest/issues.jsonl", (issue,))
    _ = extract_corpus(tmp_path)
    _ = build_corpus_index(tmp_path)
    return tmp_path


def test_preupgrade_summary_cannot_default_into_current_method(method_project: Path) -> None:
    # Given otherwise current index bytes whose receipt predates implementation binding.
    path = method_project / "data/processed/index/index-summary.jsonl"
    value = json.loads(path.read_text())
    del value["implementation_sha256"]
    _ = path.write_text(json.dumps(value))
    # When a consumer asks for current verified rows.
    with pytest.raises(ValidationError):
        read_corpus_index(method_project)
    # Then a missing historical method identity does not inherit a current default.


def test_old_method_identity_cannot_reuse_source_matched_cache(method_project: Path) -> None:
    # Given source-matched payloads but a receipt produced under another implementation.
    path = method_project / "data/processed/index/index-summary.jsonl"
    value = json.loads(path.read_text())
    value["implementation_sha256"] = "0" * 64
    _ = path.write_text(json.dumps(value))
    # When reading the old observations under the installed method.
    with pytest.raises(AcquisitionError, match="implementation changed"):
        read_corpus_index(method_project)
    # Then old manifest/duplicate eligibility flags cannot escape as current facts.


def test_same_method_preserves_valid_text_cache(method_project: Path) -> None:
    # Given valid index/text caches under the current implementation.
    first = build_text_index(method_project)
    database = method_project / first.database_path
    before = database.read_bytes(), database.stat().st_mtime_ns
    # When metadata is rebuilt under the same method and the text cache is requested again.
    summary = build_corpus_index(method_project)
    second = build_text_index(method_project)
    # Then method binding permits unchanged verified data to retain its cache identity.
    assert summary.implementation_sha256 == index_implementation_sha256()
    assert second == first
    assert (database.read_bytes(), database.stat().st_mtime_ns) == before


def test_shared_identity_dependency_changes_the_method_digest(tmp_path: Path) -> None:
    # Given an independent physical copy of the actual implementation and dependencies.
    code = tmp_path / "method"
    code.mkdir()
    for filename in INDEX_IMPLEMENTATION_FILES:
        shutil.copyfile(Path(source.__file__).with_name(filename), code / filename)
    specification = importlib.util.spec_from_file_location(
        "copied_index_method", code / "index_implementation.py"
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    method = TypeAdapter(Callable[[], str]).validate_python(
        getattr(module, "index_implementation_sha256")  # noqa: B009 -- Dynamic module boundary.
    )
    before = method()
    identity = code / "index_identity.py"
    _ = identity.write_bytes(
        identity.read_bytes() + b"\n# A changed publication identity method.\n"
    )
    # When the copied implementation fingerprints its actual dependency bytes.
    after = method()
    # Then shared identity rules participate in the method identity, beyond the row payload.
    assert after != before
