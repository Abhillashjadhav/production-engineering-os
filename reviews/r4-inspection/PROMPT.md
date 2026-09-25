# R4 inspection packet

Extend the existing retained reader and CLI for N2/N3/N5, C4-F1/F2/F4, and
F-C3-2/3/4. Validate contract/receipt/plan identity before accepting an ungated
release; require one coherent latest verification attempt; reject contradictory
duplicate gate events, unknown intervening events, and missing starts; reverify
recorded approval authority against the retained receipt. Report RELEASE_READY
only for the matching terminal event, and distinguish independently supplied
expected heads from unanchored self-consistency.

Coordinate N1 process-evidence re-derivation through the same self-contained pure
helper supplied by the process worker. Keep this branch independently importable.
Keep mutations and positive controls offline. Record exact commands and exits;
do not change frozen inputs, scanners, policy, allowlists, models, or authority.

Source report: `upload/Pasted markdown(20260924-162913).md`.
Shared outcome contract: `r4-20260924/peos-proof/docs/evidence/r4-repair-20260924/WORK_CONTRACT.md`.
The unsigned self-consistent rewrite limitation remains explicit.
