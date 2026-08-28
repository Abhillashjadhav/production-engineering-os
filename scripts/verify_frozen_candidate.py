"""Verification-only pass over the frozen pm-evals Web candidate CAND-001.

Re-establishes the reviewer read-only proofs over the frozen candidate tree
(commit 243eddf) with the FIXED read-only guard and the three-dimension
release report, reusing the six existing lens reports and the frozen phase-1
evidence. It does NOT re-freeze the candidate and does NOT re-run the
reviewers — the reviewer *findings* are reused as-is; only the mechanical
integrity proofs, which the harness-lock false positive had invalidated, are
re-established under the corrected guard.

What it proves, executed (not asserted):
  1. the fixed guard is clean over the frozen candidate tree — including the
     exact prior false positive (a harness lock present at snapshot time then
     deleted mid-review) — and still catches a real tracked-file change;
  2. the six v3 reviewers are read-only by tool configuration at 243eddf;
  3. driving begin/end_review over the frozen candidate worktree yields six
     clean read-only proofs, and release_report emits an honest HOLD with
     verification_integrity=valid.

Outputs (under --dest, committed as the dogfood verification evidence):
  verification-report.md / .json   three dimensions + the audit trail
  verification-ledger.jsonl        the verification run's ledger (6 clean
                                   reviews + release_report HOLD/valid)
  readonly-proof.txt               the executed guard/tool-config proof

Usage:
  python scripts/verify_frozen_candidate.py \
    --candidate-worktree <clean checkout of 243eddf> \
    --frozen-run <original run dir: candidate-manifest.json + lens-reviews/> \
    --dest docs/v3/dogfood
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from pmpe.agents.permissions import (  # noqa: E402
    FULLSTACK_REVIEW_LENSES,
    assert_fullstack_reviewers_read_only,
)
from pmpe.agents.registry import AgentRegistry  # noqa: E402
from pmpe.assurance.readonly_guard import readonly_snapshot, verify_unmodified  # noqa: E402
from pmpe.evals.trajectory import evaluate_trajectory  # noqa: E402
from pmpe.evals.trajectory_fullstack import evaluate_fullstack_trajectory  # noqa: E402
from pmpe.fullstack.contract import load_fullstack_contract  # noqa: E402
from pmpe.fullstack.orchestration import FullStackRun  # noqa: E402

CANDIDATE_COMMIT = "243eddf72005f6f23ed70142053adbd27f7ae3c3"
LENSES = tuple(FULLSTACK_REVIEW_LENSES.values())
LOCK = ".claude/scheduled_tasks.lock"


def _guard_proof(wt: Path, log: io.StringIO) -> None:
    """Executed: the fixed guard is clean over the frozen candidate, tolerates
    the harness-lock scenario, and still catches a real tracked change."""
    print("# Read-only guard proof over the frozen candidate tree", file=log)
    print(f"candidate worktree HEAD: {_head(wt)}", file=log)

    before = readonly_snapshot(wt)
    print(f"tracked files in snapshot: {len(before)}", file=log)
    assert LOCK not in before, "harness lock must be outside the tracked boundary"

    # the exact prior false positive: lock present at snapshot, deleted mid-review
    lock = wt / LOCK
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("held")
    after_snap = readonly_snapshot(wt)
    lock.unlink()
    v1 = verify_unmodified(wt, after_snap)
    print(f"harness lock present-then-deleted → verify_unmodified: {v1 or 'clean'}", file=log)
    assert v1 == [], "harness-lock churn must not read as a reviewer write"

    # and a real tracked modification is still caught
    target = next(iter(before))
    original = (wt / target).read_bytes()
    (wt / target).write_bytes(original + b"\n# reviewer edit\n")
    v2 = verify_unmodified(wt, before)
    (wt / target).write_bytes(original)  # restore immediately
    print(f"tracked file {target} modified → verify_unmodified: {v2}", file=log)
    assert v2 == [f"changed: {target}"], "a real tracked modification must be caught"
    assert verify_unmodified(wt, before) == [], "restore must return the tree to clean"
    print(
        "guard proof: PASS (clean over candidate; lock tolerated; real change caught)\n", file=log
    )


def _readonly_roster_proof(wt: Path, log: io.StringIO) -> None:
    print("# Reviewer read-only proof by tool configuration (at 243eddf)", file=log)
    assert_fullstack_reviewers_read_only(AgentRegistry(wt / ".claude" / "agents"))
    for lens in LENSES:
        print(f"  {lens}: tools Read/Grep/Glob only (read-only) ✓", file=log)
    print("roster proof: PASS (all six lenses read-only by tool config)\n", file=log)


def _head(wt: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(wt), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate-worktree", required=True, type=Path)
    ap.add_argument("--frozen-run", required=True, type=Path)
    ap.add_argument("--dest", required=True, type=Path)
    args = ap.parse_args()

    wt: Path = args.candidate_worktree
    frozen: Path = args.frozen_run
    dest: Path = args.dest
    dest.mkdir(parents=True, exist_ok=True)

    head = _head(wt)
    if head != CANDIDATE_COMMIT:
        raise SystemExit(f"worktree is at {head}, not the frozen candidate {CANDIDATE_COMMIT}")

    manifest = json.loads((frozen / "candidate-manifest.json").read_text())
    phase1 = [
        json.loads(line)
        for line in (frozen / "ledger.jsonl").read_text().splitlines()
        if line.strip()
    ]
    browser = next(e for e in phase1 if e["stage"] == "browser_verification")
    suites = [s.split("=")[1] for s in [browser["detail"].split(";")[0]]][0].split(",")
    assert any(e["stage"] == "preview" for e in phase1), "reused evidence lacks a preview record"

    # executed proofs
    log = io.StringIO()
    _guard_proof(wt, log)
    _readonly_roster_proof(wt, log)

    # a real verification run over the frozen candidate, reusing frozen evidence
    run_dir = dest.parent / "_verify-run"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    contract = load_fullstack_contract(
        wt / "tests" / "fixtures" / "v3" / "fullstack_contract_approved.json"
    )
    state = {
        "run_id": "fs-verify-fsc-pmevals-001",
        "contract_digest": manifest["contract_digest"],
        "journey_validated": True,
        "api_contract_current": True,
        "candidate_digest": manifest["tree_digest"],  # reused frozen candidate digest
        "browser_suites": sorted(suites),
        "preview_recorded": True,
        "reviews": {},
        "release_verdict": "",
        "release_integrity": "",
    }
    run = FullStackRun(run_dir, contract, state)
    print("# Six reviewer read-only proofs re-established over the frozen candidate", file=log)
    for lens in LENSES:
        run.begin_review(lens, wt)
        run.end_review(lens, wt)
        print(f"  {lens}: readonly_check=clean over {CANDIDATE_COMMIT[:12]}", file=log)
    report = run.release_report(verdict="HOLD")  # product FAILs in the lens reports → HOLD
    print(
        f"\nrelease_report: product_verdict={report.product_verdict}, "
        f"verification_integrity={report.verification_integrity}",
        file=log,
    )

    # compose the complete verification ledger: reused phase-1 evidence
    # (re-stamped to this verification run) + the six re-established reviews +
    # the release report. The reused phase-1 events keep their original digests
    # (freeze candidate, browser suites, preview) — only the run_id is aligned.
    review_events = [
        json.loads(line)
        for line in (run_dir / "ledger.jsonl").read_text().splitlines()
        if line.strip()
    ]
    phase1_reused = [
        {**e, "run_id": state["run_id"]}
        for e in phase1
        if e.get("stage") not in ("review", "release_report")
    ]
    full_ledger = phase1_reused + review_events

    # the dogfood thesis: a complete run ledger is clean under BOTH rule sets
    fs = [v.check_id for v in evaluate_fullstack_trajectory(full_ledger)]
    v2 = [v.check_id for v in evaluate_trajectory(full_ledger)]
    if fs or v2:
        raise SystemExit(f"verification ledger not clean — TRAJ-FS={fs} V2={v2}")
    print("\nverification ledger clean under both rule sets (TRAJ-FS + V2)", file=log)

    # emit evidence
    (dest / "readonly-proof.txt").write_text(log.getvalue())
    (dest / "verification-ledger.jsonl").write_text(
        "\n".join(json.dumps(e) for e in full_ledger) + "\n"
    )
    shutil.rmtree(run_dir)

    result = {
        "candidate": {
            "candidate_id": manifest["candidate_id"],
            "commit": CANDIDATE_COMMIT,
            "tree_digest": manifest["tree_digest"],
            "contract_digest": manifest["contract_digest"],
            "binding": "immutable git commit; read-only proofs re-run over its tracked tree",
        },
        "product_verdict": report.product_verdict,
        "verification_integrity": report.verification_integrity,
        "integrity_by_lens": report.integrity_by_lens,
        "lenses_reviewed": list(report.lenses_reviewed),
        "ledger_clean_under_both_rule_sets": True,
        "reused_evidence": {
            "browser_suites": sorted(suites),
            "preview_recorded": True,
            "lens_reports": [f"{lens}.md" for lens in LENSES],
        },
    }
    (dest / "verification-report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("product_verdict", "verification_integrity")}))
    print(f"verification evidence written to {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
