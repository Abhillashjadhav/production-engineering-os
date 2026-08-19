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
    assert len(list(output.glob("versions/*/visible/cases.json"))) == 1
    assert len(list(output.glob("versions/*/eval-only/oracles.json"))) == 1


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
    report_path = next(output.glob("reports/*/workflow-report.json"))
    report = json.loads(report_path.read_text())
    assert report["selected_action"] == "refund"
    assert report["evidence_complete"] is True


def test_support_demo_maps_unknown_case_to_malformed_input(tmp_path: Path) -> None:
    corpus = write_support_corpus(tmp_path / "corpus", seed=110)

    result = main(
        [
            "support-demo",
            "run",
            "--cases",
            str(corpus.visible_path),
            "--case-id",
            "SUP-UNKNOWN",
            "--output",
            str(tmp_path / "result"),
        ]
    )

    assert result == 2


def test_support_demo_maps_malformed_corpus_to_input_exit_code(tmp_path: Path) -> None:
    malformed = tmp_path / "cases.json"
    malformed.write_text("{not-json")

    result = main(
        [
            "support-demo",
            "run",
            "--cases",
            str(malformed),
            "--output",
            str(tmp_path / "result"),
        ]
    )

    assert result == 2


def test_support_demo_maps_malformed_oracle_scalar_to_input_exit_code(tmp_path: Path) -> None:
    corpus = write_support_corpus(tmp_path / "corpus", seed=110)
    payload = json.loads(corpus.oracle_path.read_text())
    payload["oracles"][0]["rationale_code"] = 1
    corpus.oracle_path.write_text(json.dumps(payload))

    result = main(
        [
            "support-demo",
            "evaluate",
            "--cases",
            str(corpus.visible_path),
            "--oracles",
            str(corpus.oracle_path),
            "--output",
            str(tmp_path / "evaluation.json"),
        ]
    )

    assert result == 2


def test_support_demo_returns_human_gate_exit_code(tmp_path: Path) -> None:
    corpus = write_support_corpus(tmp_path / "corpus", seed=110)
    case = next(
        item
        for item in load_visible_cases(corpus.visible_path)
        if any(policy.action == "escalate" for policy in item.policies)
    )

    result = main(
        [
            "support-demo",
            "run",
            "--cases",
            str(corpus.visible_path),
            "--case-id",
            case.case_id,
            "--output",
            str(tmp_path / "result"),
        ]
    )

    assert result == 3


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


def test_support_demo_rejects_selectively_reduced_held_out_corpus(tmp_path: Path) -> None:
    corpus = write_support_corpus(tmp_path / "corpus", seed=110)
    payload = json.loads(corpus.visible_path.read_text())
    payload["cases"] = [next(item for item in payload["cases"] if item["split"] == "held_out")]
    corpus.visible_path.write_text(json.dumps(payload))

    result = main(
        [
            "support-demo",
            "evaluate",
            "--cases",
            str(corpus.visible_path),
            "--oracles",
            str(corpus.oracle_path),
            "--output",
            str(tmp_path / "evaluation.json"),
        ]
    )

    assert result == 2
