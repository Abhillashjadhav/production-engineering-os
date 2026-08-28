# Real-provider E1 evidence — 2026-08-26

This directory publishes the complete evidence chain for run
`codex-e1-live-20260826T100659Z`. The approved E1 health contract completed the
frozen bare-bones path using Codex CLI 0.149.1 authenticated through a ChatGPT
subscription. No API key was used and the run reported no per-run API cost.

## Terminal result

| Field | Recorded value |
| --- | --- |
| State / cause | `RELEASE_READY` / `PASS` |
| Exit code | `0` |
| Model | `gpt-5.6-sol`, reasoning effort `xhigh` |
| Attempts / model calls | `1` / `2` |
| Tokens | `23,504` input / `90` output |
| Elapsed time | `16,052 ms` |
| Approval | `VERIFIED`, authority `fixture-human` |
| Criteria | `1` structured / `0` human |
| Evidence | `5` events / `8` referenced blobs / integrity `PASS` |
| Workspace | `MATCH`, release eligible |
| Head event digest | `sha256:8c8da110bfc89c6cd0095c798817383e0328743a9b0d3da9739ba6bf14655b69` |
| Candidate digest | `sha256:4a0888572b4b546aeb1c6cff09532fb17bdaa587a0d03b152dce4f4e3a2ee4d0` |

## Published files

- `candidate/product.py` is the exact sealed candidate.
- `evidence/.pmpe/runs/.../events.jsonl` is the exact five-event ledger.
- `evidence/.pmpe/blobs/` contains all eight referenced content-addressed blobs.
- `run.log` is the exact captured terminal transcript.
- `SHA256SUMS` independently binds the published file bytes.

Run `sha256sum -c SHA256SUMS` from this directory to verify the file manifest.
The repository test suite also opens this ledger with the production
`EvidenceLedger` verifier and checks the recorded terminal state and candidate
digest.

## Claim boundary

This is evidence for one tiny contract and one successful real-provider run. It
does not prove repeated behavior, transfer to materially different contracts,
arbitrary application generation, deployment, or platform readiness.
