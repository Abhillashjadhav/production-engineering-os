from __future__ import annotations

import json
from pathlib import Path

from pmpe.cli import main
from pmpe.evals.support_corpus import write_support_corpus
from pmpe.workflows.support import load_visible_cases


def test_support_demo_generates_separated_visible_and_oracle_artifacts(
    tmp_path: Path,
) -> None:
    output = tmp_path / "generated"

    result = main(["support-demo", "generate", "--seed", "110", "--output", str(output)])

    assert result == 0
    assert (output / "visible" / "cases.json").exists()
    assert (output / "eval-only" / "oracles.json").exists()


def test_support_demo_runs_one_visible_case_without_oracle_input(
    tmp_path: Path, capsys: object
) -> None:
    corpus = write_support_corpus(tmp_path / "corpus", seed=110)
    case_id = load_visible_cases(corpus.visible_path)[0].case_id
    output = tmp_path / "result"

    result = main(
        [
            "support-demo",
            "run",
            "--cases",
            str(corpus.visible_path),
            "--case-id",
            case_id,
            "--output",
            str(output),
        ]
    )

    assert result == 0
    report = json.loads((output / "workflow-report.json").read_text())
    assert report["selected_action"] == "refund"
    assert report["evidence_complete"] is True


def test_support_demo_scores_held_out_cases_in_eval_mode(tmp_path: Path) -> None:
    corpus = write_support_corpus(tmp_path / "corpus", seed=110)
    output = tmp_path / "evaluation.json"

    result = main(
        [
            "support-demo",
            "evaluate",
            "--cases",
            str(corpus.visible_path),
            "--oracles",
            str(corpus.oracle_path),
            "--output",
            str(output),
        ]
    )

    assert result == 0
    evaluation = json.loads(output.read_text())
    assert evaluation["held_out_cases"] >= 10
    assert evaluation["exact_outcome_accuracy"] == 1.0
    assert evaluation["evidence_completeness"] == 1.0
    assert evaluation["unsupported_autonomous_actions"] == 0
