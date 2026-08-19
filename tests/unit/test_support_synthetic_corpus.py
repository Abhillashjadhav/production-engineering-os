from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import pmpe.evals.support_corpus as support_corpus_module
from pmpe.evals.support_corpus import (
    CorpusValidationError,
    HiddenOracle,
    SupportCorpus,
    generate_support_corpus,
    validate_support_corpus,
    write_support_corpus,
)
from pmpe.workflows.support import SupportCase, load_visible_cases


def test_generator_produces_held_out_decision_coverage() -> None:
    corpus = generate_support_corpus(seed=110)

    assert len(corpus.visible_cases) >= 30
    assert len(corpus.visible_cases) == len(corpus.hidden_oracles)
    assert {case.split for case in corpus.visible_cases} == {"development", "held_out"}
    assert {oracle.expected_outcome for oracle in corpus.hidden_oracles} == {
        "refund",
        "replacement",
        "escalate",
        "request_evidence",
        "reject",
    }
    assert sum(case.split == "held_out" for case in corpus.visible_cases) >= 10
    assert all(
        not any(
            label in case.case_id.casefold()
            for label in ("refund", "replacement", "missing", "contradiction", "unsupported")
        )
        for case in corpus.visible_cases
    )


def test_held_out_templates_do_not_reuse_development_rule_ids() -> None:
    corpus = generate_support_corpus(seed=110)
    development_rules = {
        rule.rule_id
        for case in corpus.visible_cases
        if case.split == "development"
        for rule in case.policies
    }
    held_out_rules = {
        rule.rule_id
        for case in corpus.visible_cases
        if case.split == "held_out"
        for rule in case.policies
    }

    assert development_rules.isdisjoint(held_out_rules)


def test_held_out_conflict_establishes_both_policy_predicates() -> None:
    corpus = generate_support_corpus(seed=110)
    conflict = next(
        case
        for case in corpus.visible_cases
        if case.split == "held_out" and len(case.policies) == 2
    )

    visible_text = " ".join(item.text for item in conflict.facts).casefold()
    assert "unused" in visible_text
    assert "clearance" in visible_text


def test_generation_and_written_artifacts_are_byte_deterministic(tmp_path: Path) -> None:
    first = write_support_corpus(tmp_path / "first", seed=41)
    second = write_support_corpus(tmp_path / "second", seed=41)

    assert first.visible_path.read_bytes() == second.visible_path.read_bytes()
    assert first.oracle_path.read_bytes() == second.oracle_path.read_bytes()
    assert generate_support_corpus(seed=41) == generate_support_corpus(seed=41)
    assert generate_support_corpus(seed=41) != generate_support_corpus(seed=42)


def test_writer_rolls_back_visible_artifact_if_oracle_publish_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = write_support_corpus(tmp_path, seed=41)
    previous_visible = paths.visible_path.read_bytes()
    previous_oracle = paths.oracle_path.read_bytes()
    real_write = support_corpus_module._write_atomic

    def fail_oracle(path: Path, payload: bytes) -> None:
        if path == paths.oracle_path:
            raise OSError("simulated oracle publish failure")
        real_write(path, payload)

    monkeypatch.setattr(support_corpus_module, "_write_atomic", fail_oracle)

    with pytest.raises(OSError, match="simulated"):
        write_support_corpus(tmp_path, seed=42)

    assert paths.visible_path.read_bytes() == previous_visible
    assert paths.oracle_path.read_bytes() == previous_oracle


def test_visible_loader_cannot_observe_hidden_oracle_fields(tmp_path: Path) -> None:
    paths = write_support_corpus(tmp_path, seed=7)
    visible_bytes = paths.visible_path.read_bytes()
    visible_payload = json.loads(visible_bytes)
    loaded = load_visible_cases(paths.visible_path)

    forbidden = {"expected_outcome", "required_fact_ids", "required_rule_ids", "rationale_code"}
    assert len(loaded) >= 30
    assert all(isinstance(case, SupportCase) for case in loaded)
    assert forbidden.isdisjoint(visible_payload)
    assert all(forbidden.isdisjoint(item) for item in visible_payload["cases"])
    assert paths.oracle_path.parent.name == "eval-only"
    assert paths.oracle_path not in paths.visible_path.parents


def test_validator_rejects_oracle_leakage_into_visible_payload(tmp_path: Path) -> None:
    paths = write_support_corpus(tmp_path, seed=8)
    payload = json.loads(paths.visible_path.read_text())
    payload["cases"][0]["expected_outcome"] = "refund"
    paths.visible_path.write_text(json.dumps(payload))

    with pytest.raises(CorpusValidationError, match="hidden oracle field"):
        load_visible_cases(paths.visible_path)


def test_visible_loader_bounds_recursive_payloads(tmp_path: Path) -> None:
    paths = write_support_corpus(tmp_path, seed=8)
    nested: object = "leaf"
    for _ in range(70):
        nested = [nested]
    payload = json.loads(paths.visible_path.read_text())
    payload["extra"] = nested
    paths.visible_path.write_text(json.dumps(payload))

    with pytest.raises(CorpusValidationError, match="nesting or size"):
        load_visible_cases(paths.visible_path)


def test_visible_loader_normalizes_decoder_recursion(tmp_path: Path) -> None:
    path = tmp_path / "deep.json"
    path.write_text("[" * 10_000 + "0" + "]" * 10_000)

    with pytest.raises(CorpusValidationError, match="unreadable"):
        load_visible_cases(path)


def test_visible_loader_rejects_scalar_product_constraints(tmp_path: Path) -> None:
    paths = write_support_corpus(tmp_path, seed=8)
    payload = json.loads(paths.visible_path.read_text())
    payload["cases"][0]["product_constraints"] = "refund"
    paths.visible_path.write_text(json.dumps(payload))

    with pytest.raises(CorpusValidationError, match="constraints must be an array"):
        load_visible_cases(paths.visible_path)


def test_visible_loader_normalizes_unpaired_unicode_surrogate(tmp_path: Path) -> None:
    paths = write_support_corpus(tmp_path, seed=8)
    payload = json.loads(paths.visible_path.read_text())
    payload["cases"][0]["ticket_text"] = "\ud800"
    paths.visible_path.write_text(json.dumps(payload))

    with pytest.raises(CorpusValidationError, match="malformed"):
        load_visible_cases(paths.visible_path)


def test_validator_rejects_oracle_references_not_present_in_visible_case() -> None:
    corpus = generate_support_corpus(seed=9)
    first = corpus.hidden_oracles[0]
    invalid = replace(first, required_rule_ids=("POLICY-NOT-VISIBLE",))
    mutated = SupportCorpus(corpus.visible_cases, (invalid, *corpus.hidden_oracles[1:]))

    with pytest.raises(CorpusValidationError, match="rationale and evidence"):
        validate_support_corpus(mutated)


def test_validator_rejects_empty_oracle_evidence_bindings() -> None:
    corpus = generate_support_corpus(seed=9)
    first = corpus.hidden_oracles[0]
    invalid = replace(first, required_fact_ids=(), required_rule_ids=())
    mutated = SupportCorpus(corpus.visible_cases, (invalid, *corpus.hidden_oracles[1:]))

    with pytest.raises(CorpusValidationError, match="rationale and evidence"):
        validate_support_corpus(mutated)


def test_validator_rejects_partial_conflict_evidence_or_wrong_outcome() -> None:
    corpus = generate_support_corpus(seed=9)
    index = next(
        index
        for index, item in enumerate(corpus.hidden_oracles)
        if item.rationale_code.endswith("equal-priority-conflict")
    )
    conflict = corpus.hidden_oracles[index]
    partial = replace(
        conflict,
        required_fact_ids=conflict.required_fact_ids[:1],
        required_rule_ids=conflict.required_rule_ids[:1],
    )
    wrong = replace(conflict, expected_outcome="refund")

    for invalid, message in ((partial, "evidence is incomplete"), (wrong, "rationale")):
        oracles = list(corpus.hidden_oracles)
        oracles[index] = invalid
        with pytest.raises(CorpusValidationError, match=message):
            validate_support_corpus(SupportCorpus(corpus.visible_cases, tuple(oracles)))


def test_validator_rejects_coordinated_rationale_and_outcome_rewrite() -> None:
    corpus = generate_support_corpus(seed=9)
    first = replace(
        corpus.hidden_oracles[0],
        expected_outcome="reject",
        rationale_code="unsupported-action",
    )

    with pytest.raises(CorpusValidationError, match="rationale and evidence"):
        validate_support_corpus(
            SupportCorpus(corpus.visible_cases, (first, *corpus.hidden_oracles[1:]))
        )


def test_validator_rejects_trivial_all_escalate_oracle() -> None:
    corpus = generate_support_corpus(seed=10)
    trivial = tuple(
        HiddenOracle(
            case_id=item.case_id,
            split=item.split,
            expected_outcome="escalate",
            required_fact_ids=item.required_fact_ids,
            required_rule_ids=item.required_rule_ids,
            rationale_code="manual-review",
        )
        for item in corpus.hidden_oracles
    )

    with pytest.raises(CorpusValidationError, match="outcome diversity"):
        validate_support_corpus(SupportCorpus(corpus.visible_cases, trivial))


def test_validator_rejects_all_escalate_held_out_partition() -> None:
    corpus = generate_support_corpus(seed=10)
    split_by_id = {item.case_id: item.split for item in corpus.visible_cases}
    mutated = tuple(
        replace(item, expected_outcome="escalate")
        if split_by_id[item.case_id] == "held_out"
        else item
        for item in corpus.hidden_oracles
    )

    with pytest.raises(CorpusValidationError, match="held-out outcome diversity"):
        validate_support_corpus(SupportCorpus(corpus.visible_cases, mutated))


def test_validator_rejects_duplicate_or_mismatched_cases() -> None:
    corpus = generate_support_corpus(seed=11)

    with pytest.raises(CorpusValidationError, match="duplicate case"):
        validate_support_corpus(
            SupportCorpus((corpus.visible_cases[0], *corpus.visible_cases), corpus.hidden_oracles)
        )
    with pytest.raises(CorpusValidationError, match="one oracle"):
        validate_support_corpus(SupportCorpus(corpus.visible_cases, corpus.hidden_oracles[1:]))


def test_validator_rejects_visible_partition_relabeling() -> None:
    corpus = generate_support_corpus(seed=11)
    held_out_index = next(
        index for index, item in enumerate(corpus.visible_cases) if item.split == "held_out"
    )
    visible = list(corpus.visible_cases)
    visible[held_out_index] = replace(visible[held_out_index], split="development")

    with pytest.raises(CorpusValidationError, match="hidden oracle is malformed"):
        validate_support_corpus(SupportCorpus(tuple(visible), corpus.hidden_oracles))


def test_validator_rejects_undersized_held_out_partition() -> None:
    corpus = generate_support_corpus(seed=11)
    held_out_ids = [item.case_id for item in corpus.visible_cases if item.split == "held_out"]
    retained = set(held_out_ids[:4])
    visible = tuple(
        replace(item, split="development")
        if item.split == "held_out" and item.case_id not in retained
        else item
        for item in corpus.visible_cases
    )
    oracles = tuple(
        replace(item, split="development")
        if item.split == "held_out" and item.case_id not in retained
        else item
        for item in corpus.hidden_oracles
    )

    with pytest.raises(CorpusValidationError, match="partition coverage"):
        validate_support_corpus(SupportCorpus(visible, oracles))


def test_every_oracle_is_grounded_in_visible_facts_and_rules() -> None:
    corpus = generate_support_corpus(seed=12)
    validate_support_corpus(corpus)
    visible = {case.case_id: case for case in corpus.visible_cases}

    for oracle in corpus.hidden_oracles:
        case = visible[oracle.case_id]
        assert set(oracle.required_fact_ids) <= {fact.fact_id for fact in case.facts}
        assert set(oracle.required_rule_ids) <= {rule.rule_id for rule in case.policies}
        assert oracle.rationale_code
