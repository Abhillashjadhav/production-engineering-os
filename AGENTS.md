# Repository operating instructions

Follow the existing `CLAUDE.md` instructions as well as this owner-supplied gate.

## The BAR Gate

Before starting any unit of work, write `BAR.md` answering these six questions yes or no, each with one line of evidence. An answer marked **stop** halts that unit of work until it is restructured — it does not halt the run.

1. **Does this already exist in either repository?** Yes → stop. Reuse or extend the existing path instead of adding a parallel one.
2. **Can I point to the approved contract criterion or the reproduced blocker that requires this?** No → stop. It is speculative work.
3. **Does this change behaviour that already has a caller or a test?** Yes → it is not additive. List what may break, and give it its own branch and its own BAR entry.
4. **Is there an automated check that fails before this change and passes after it?** No → stop. Write the failing check first.
5. **Can this be reverted as a single unit without touching other work?** No → stop. Split it until each piece can.
6. **Does this add a setting, a dependency, or an extension surface that no approved criterion asked for?** Yes → stop. Remove the addition, or raise it as a decision and wait.
