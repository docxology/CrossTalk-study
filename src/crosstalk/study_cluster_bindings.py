"""Project-local provenance bindings for exploratory cluster inputs."""

from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import Field, model_validator

from crosstalk.study_language_records import Digest, Record, StudyError


class ClusterBinding(Record):
    """A caller-admitted retained artifact; this pure layer performs no filesystem admission."""

    path: str = Field(min_length=1, max_length=1200)
    sha256: Digest

    @model_validator(mode="after")
    def local(self) -> ClusterBinding:
        """Reject traversal or absolute locators in relocatable research provenance."""
        path = PurePosixPath(self.path)
        if (
            path.is_absolute()
            or not path.parts
            or ".." in path.parts
            or "\\" in self.path
            or path.as_posix() != self.path
        ):
            raise StudyError("cluster provenance requires a project-local POSIX artifact")
        return self
