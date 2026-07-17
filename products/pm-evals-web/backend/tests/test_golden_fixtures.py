"""The frontend's golden comparison fixtures are REAL engine output, pinned
byte-for-byte: hand-editing a golden file (or engine drift) fails here first,
so the dashboard's component tests can never render an invented comparison."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts" / "export_golden_comparisons.py"
FRONTEND_FIXTURES = BACKEND.parent / "frontend" / "tests" / "fixtures"

GOLDEN_NAMES = (
    "comparison_improved.json",
    "comparison_regression.json",
    "comparison_insufficient.json",
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_golden_comparisons", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_golden_comparisons_are_committed_and_current() -> None:
    fresh = _load_script().golden_comparisons()
    assert sorted(fresh) == sorted(GOLDEN_NAMES)
    for name, expected in fresh.items():
        committed = (FRONTEND_FIXTURES / name).read_text()
        assert committed == expected, (
            f"{name} does not match the engine's output — regenerate with "
            "scripts/export_golden_comparisons.py and re-review"
        )


def test_goldens_cover_all_three_verdicts() -> None:
    """The dashboard must be tested against every verdict the engine can
    return — a golden set that silently loses a verdict weakens PR 8's
    component tests without failing them."""
    import json

    verdicts = {
        json.loads((FRONTEND_FIXTURES / name).read_text())["verdict"] for name in GOLDEN_NAMES
    }
    assert verdicts == {"PROCEED", "HOLD", "INSUFFICIENT_EVIDENCE"}
