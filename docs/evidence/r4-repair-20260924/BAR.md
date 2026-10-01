# BAR — historical replay checker

1. Does this already exist? **Yes — restructure**: extend the existing `check_replay_complete.py`; no second verdict path.
2. Approved criterion/reproduced blocker? **Yes**: R4 R-02/R-03 identify accepted exit 137, fake inventories, swapped stdout and stripped assertions under `-O`.
3. Existing caller/test behavior changes? **Yes**: same checker path, dedicated `repair/r4-peos-proof` branch. Semantic verification now requires explicit packet/source roots; structural-only success is removed.
4. Automated failing check first? **Yes**: committed subprocess mutation tests run on the old checker before implementation.
5. Independently revertible? **Yes**: checker/tests/evidence form one bounded unit; frozen runner and v1 artifacts remain unchanged.
6. Unrequested setting/dependency/surface? **No**: explicit source inputs are required to validate the reported evidence; no dependency or runtime product feature added.
