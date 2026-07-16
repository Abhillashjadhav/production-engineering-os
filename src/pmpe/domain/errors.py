"""Typed error hierarchy for the pipeline."""

from __future__ import annotations


class PmpeError(Exception):
    """Base class for all pipeline errors."""


class SpecError(PmpeError):
    """The input specification is malformed or violates the schema.

    ``issues`` carries field-level messages suitable for showing a PM.
    """

    def __init__(self, message: str, issues: list[str] | None = None) -> None:
        self.issues = issues or []
        detail = message if not self.issues else message + "\n- " + "\n- ".join(self.issues)
        super().__init__(detail)


class ConfigError(PmpeError):
    """The pipeline configuration is invalid."""


class StepFailure(PmpeError):  # noqa: N818 — named for what it represents
    """A workflow step failed in a way the pipeline cannot recover from."""

    def __init__(self, step: str, message: str) -> None:
        self.step = step
        super().__init__(f"step '{step}' failed: {message}")
