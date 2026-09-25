"""Verify additive C7-01 provenance without importing or executing product code."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = "a56c1c4671c34dd9748c30dd10cd1d0dcd6ecfc0"
REPOSITORY = "Abhillashjadhav/production-engineering-os"
CLAIMS = {
    "combined_tests_and_docs_head": "733a409d5b0a72f7ad0550db974f70623e259992",
    "implementation_source_commit": "68ae80fbe85332551b36f2a0b6dfe24d7ba1bc3d",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def object_id(revision: str) -> str:
    return git("rev-parse", revision).decode().strip()


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def main() -> None:
    map_path = HERE.parent / "provenance-map.json"
    require(map_path.is_file(), "C7-01 direct provenance map is absent")
    mapping = json.loads(map_path.read_text())
    require(mapping["repository"] == REPOSITORY, "wrong repository")
    require(mapping["classification"] == "EXACT_TREE_EQUIVALENCE_ONLY", "overstated proof")
    require(set(mapping["claims"]) == set(CLAIMS), "historical claim set changed")

    source = mapping["original_claim_file"]
    blob_ref = source["local_commit"] + ":" + source["path"]
    original_bytes = git("show", blob_ref)
    require(object_id(blob_ref) == source["git_blob"], "historical blob changed")
    require(digest(original_bytes) == source["sha256"], "historical bytes changed")
    original = json.loads(original_bytes)
    require(
        all(original[field] == value for field, value in CLAIMS.items()),
        "original claim identities changed",
    )

    public_path = HERE / "public-commits.json"
    require(digest(public_path.read_bytes()) == mapping["public_metadata_sha256"], "public metadata changed")
    public = json.loads(public_path.read_text())
    require(public["method"] == "GitHub Git-data API GET; relevant-field projection", "unidentified evidence")
    for field, expected_local in CLAIMS.items():
        claim = mapping["claims"][field]
        require(claim["local"] == expected_local, "wrong local alias")
        require(object_id(expected_local + "^{tree}") == claim["tree"], "wrong local tree")
        record = public["commits"][claim["public"]]
        require(record["sha"] == claim["public"], "wrong public commit")
        require(record["tree"] == claim["tree"], "public/local tree mismatch")
        require(
            record["source_url"] == f"https://api.github.com/repos/{REPOSITORY}/git/commits/{claim['public']}",
            "metadata is not pinned to the public commit",
        )

    chain = mapping["existing_publication_chain"]
    publication_ref = BASE + ":" + chain["path"]
    publication_bytes = git("show", publication_ref)
    require(digest(publication_bytes) == chain["sha256"], "prior publication record changed")
    publication = json.loads(publication_bytes)
    entries = publication["peos_migration_commits"]
    prior = next(entry for entry in entries if entry["local"] == chain["local"])
    claim = mapping["claims"]["combined_tests_and_docs_head"]
    require(prior["remote"] == claim["public"], "existing public alias differs")
    require(prior["tree"] == claim["tree"], "existing publication tree differs")
    require(object_id(chain["local"] + "^{tree}") == claim["tree"], "replayed local tree differs")

    delta = git("diff", "--name-only", CLAIMS["implementation_source_commit"], CLAIMS["combined_tests_and_docs_head"]).decode().splitlines()
    require(delta == mapping["historical_delta_paths"], "historical tree delta differs")
    for subtree, expected in mapping["unchanged_subtrees"].items():
        for local in CLAIMS.values():
            require(object_id(local + ":" + subtree) == expected, "source subtree differs")
    changed = git("diff", "--name-only", BASE, "--").decode().splitlines()
    require(
        all(path.startswith("docs/evidence/r4-parallel-20260925/") for path in changed),
        "workstream changed material outside its evidence directory",
    )
    require(mapping["new_test_execution"] is False, "mapping must not claim new product tests")
    require(mapping["approval_or_release_proof"] is False, "mapping must not claim approval or release")
    print(json.dumps({"status": "PASS", "verified_historical_mappings": 2, "historical_claim_blob_preserved": True, "product_code_executed": False}, indent=2))


if __name__ == "__main__":
    main()
