"""Text-only regression for the process source guard's existing architecture gate."""

from pathlib import Path

from scripts.ci.evaluate_security_profile import _observed_architecture_edges


def test_process_source_guard_has_no_unresolved_architecture_edge(tmp_path: Path) -> None:
    """Scan the real guard source without importing or executing its contents."""
    root = Path(__file__).resolve().parents[2]
    relative_source = Path("src/pmpe/process_sources.py")
    target = tmp_path / relative_source
    target.parent.mkdir(parents=True)
    target.write_bytes((root / relative_source).read_bytes())

    edges = _observed_architecture_edges(tmp_path)

    assert ("core", "unresolved_dynamic") not in edges, edges
