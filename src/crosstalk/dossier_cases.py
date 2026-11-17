"""Admit optional curated cases into one coherent dossier source observation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from crosstalk.case_records import CaseError
from crosstalk.case_validation import recheck_cases, validate_case_ledger
from crosstalk.dossier_records import SourceBinding

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from crosstalk.case_records import ValidatedCases


@dataclass(frozen=True, slots=True)
class DossierCases:
    """Current case admission and its complete immutable ledger/native input set."""

    validation: ValidatedCases | None
    bindings: tuple[SourceBinding, ...]

    def recheck(self, root: Path) -> None:
        """Recheck the ledger, native bindings and current producer before publication."""
        if self.validation is not None:
            recheck_cases(root, self.validation)


def case_evidence(
    root: Path,
    relative: Literal["manuscript/case-readings.json"] | None,
    observed: Mapping[Path, str],
) -> DossierCases:
    """Refuse configured case failures and conflicts with an earlier dossier observation."""
    if relative is None:
        return DossierCases(None, ())
    result = validate_case_ledger(root, root / relative)
    bindings = (
        SourceBinding(path=relative, sha256=result.ledger_sha256),
        *(SourceBinding(path=row.path, sha256=row.sha256) for row in result.native_bindings),
    )
    for binding in bindings:
        existing = observed.get(root / binding.path)
        if existing is not None and existing != binding.sha256:
            raise CaseError("case source differs from the earlier dossier observation")
    return DossierCases(result, bindings)
