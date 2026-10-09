import json
from pathlib import Path
W = Path("/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w1")
d = json.loads((W / "manifest-diff.json").read_text())
d["digests"] = {
 "active": {"raw": "sha256:bb7bc83e5270cc29cadfc8b30608d73f85c271f77bba4c024fa3c659f3363f59", "canonical": "sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2", "newlines": 1},
 "candidate (B)": {"raw": "sha256:6cc523b7355d9c89dfe10fed887ad54804ab9e5b4449b09115b7a85b1b518ef0", "canonical": "sha256:82f6365cd895892c4cb9fadd279f82e2755cc62bed2c60d95f49233d4c1c7f42", "lines": 1150,
                   "present_at": ["PMOS cafe8b4 reviews/task-tracker-v1/refreeze-candidate-20261009/freeze-manifest.candidate.json", "PEOS 4b1558f docs/evidence/task-tracker-completion-20261009/stage-a/freeze-manifest.candidate.json", "both real working trees"],
                   "absent_at": ["PMOS 0652843 (same path holds candidate A)", "PEOS e8a929d (stage-a/ does not exist)"]},
 "candidateA (earlier)": {"raw": "sha256:d27e42a17c7624be8c5c6f29f28afbb10636eb4e420d93efb01a59062293eb17", "canonical": "sha256:20e67cca5a1745cf5d7244019a1ccdebf3b9d4e29cc69fbaf016f2f469f6a4c0", "lines": 1146, "trailing_newline": False,
                   "present_at": ["PMOS 0652843 reviews/task-tracker-v1/refreeze-candidate-20261009/freeze-manifest.candidate.json", "PEOS e8a929d and 4b1558f docs/evidence/task-tracker-completion-20261009/refreeze-candidate/freeze-manifest.candidate.json"]},
}
d["observations"] = [
 "PROTECTED-FIELD DIFFERENCE: previous_review_bundle_digest active sha256:4eaa1d95... (= PMOS 00ccd29 review-bundle.sha256, the amended PROPOSED_NOT_APPROVED bundle that preceded the owner's confirmation) -> candidate sha256:fbfe7363... (= review_bundle_digest itself, so previous == current). Not listed among the changes in refreeze-candidate-20261009/README.md or stage-a/APPROVAL-REQUEST.md.",
 "review_bundle_digest is unchanged (fbfe7363...) in the candidate, but the review-manifest.json it names (bound artifact, raw sha256:f3ad347c...) still lists the OLD frozen digests of the five drifted files; the candidate's artifact list carries the new ones. The review manifest's own future_source_rule says to regenerate it when bound source changes.",
 "recorded_at is identical (2026-09-18T15:22:13.171142+00:00) in the candidate; agreement_before_recording, approved_contract_digest, authority_limit, owner, plan_digest, review_bundle_digest identical.",
 "Artifact list: same 218 (repository, path) pairs in the same order; 213 records identical; 5 records differ only in sha256 (indices 7, 32, 35, 50, 86).",
 "Candidate A vs candidate B: identical artifact records; differ only in approval_context text and refreeze_basis shape ('current' -> 'baseline' keys, added baseline commit map)."
]
(W / "manifest-diff.json").write_text(json.dumps(d, indent=2, ensure_ascii=False))
print("ok")
