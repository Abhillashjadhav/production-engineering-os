# Real behavior-drift evidence — 2026-08-27

Issue: #146
Result: **PASS**

This directory publishes the complete, unmodified archive produced by the
ChatGPT-authenticated Linux/Lima matrix at source commit
`4df722756fa1e2b6ed8ebc2a702d87e8f6e4e809`.

## What this proves

- Seven real Codex CLI provider runs completed: three repeats of the tiny E1
  contract, one planted prompt-profile change, and three repeats of the
  multi-criterion readiness contract.
- All seven verified ledgers end in `RELEASE_READY` with cause `PASS`, a valid
  `fixture-human` approval receipt, and a sealed candidate.
- Every within-contract comparison recompiles to the same plan digest.
- The planted `drift-eval-v2` run changed the sealed behavior exactly as
  requested, and the comparison detected and attributed the change only to
  `prompt_version`.
- The two different repository-owned contracts are correctly classified as
  `NOT_COMPARABLE` with cause `CONTRACT_CHANGED`; their separate successful
  runs are bounded contract/criterion-transfer evidence.

One ordinary E1 repeat produced different accepted output with unchanged
provider configuration. The comparator records this as
`UNATTRIBUTED_BEHAVIOR_DRIFT`; it is visible rather than erased. This does not
invalidate E5: the compiled plan remained repeatable, the candidate remained
sealed and release-ready, and the complete evidence chain verified. Real-model
candidate bytes are deliberately not required to be identical.

## What this does not prove

This matrix does not prove arbitrary external product contracts, a different
product type, production deployment, hosted multi-tenant isolation, or general
platform readiness. Provider metadata is adapter-declared provenance rather
than an independent provider attestation.

## Bound identities

| Item | Verified value |
|---|---|
| Source commit | `4df722756fa1e2b6ed8ebc2a702d87e8f6e4e809` |
| Authentication | ChatGPT subscription; `OPENAI_API_KEY` and `CODEX_API_KEY` removed |
| Codex CLI | `codex-cli 0.149.1` |
| Python | `3.12.14` |
| Provider digest | `sha256:98efcf27edaa6bf0ca4c8b3b45790df81b63d2bded5f8f6f381504c4e9871427` |
| Git archive digest | `sha256:32840540763ccd9d910b71f361c5907fad7247abf78c48eea128fb754a7c33f1` |
| Source snapshot tree digest | `sha256:a0b92d283aeeda141ca43df3dda98f9617233e0e67cfbc6c58dd00a9e25b1adb` |
| Published archive digest | `sha256:877bf87b6fdfb305e28ba68468f5f8f5d1c03ca65fcb51351ae63f32df8f32c1` |

## Independent verification

The uploaded archive was checked independently from the generating VM:

- no absolute paths, parent traversal, symbolic links, or hard links;
- all `831/831` files in the internal `SHA256SUMS` manifest matched;
- the captured source content matched `git archive` for the recorded commit;
- Git archive, provider, and source-tree digests reproduced exactly;
- `pmpe barebones status` and `evidence` reverified all seven ledgers;
- all six `pmpe barebones compare` outputs reproduced byte-for-byte, including
  the expected exit code `3` for the cross-contract comparison;
- sealed-file inspection reproduced the planted top-level assignment
  `PMPE_PROMPT_PROFILE = "drift-eval-v2"`.

Verify the complete archive before extraction:

```bash
sha256sum -c SHA256SUMS
```
The source snapshot is intentionally read-only. GNU tar users can preserve the
archive safely by pre-creating its directories before extraction:

```bash
archive=pmpe-real-drift-20260827T141651Z.tgz
destination=extracted
mkdir -p "$destination"
tar -tzf "$archive" | awk '/\/$/' | while IFS= read -r directory; do
  mkdir -p "$destination/$directory"
done
tar --no-overwrite-dir -xzf "$archive" -C "$destination"
cd "$destination/pmpe-real-drift-20260827T141651Z"
sha256sum -c SHA256SUMS
```
