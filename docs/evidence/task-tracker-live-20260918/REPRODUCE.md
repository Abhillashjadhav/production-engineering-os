# Reproduce the approved task tracker

This reproduces the retained, model-generated product and its approved user
journey. Live generation was demonstrated separately in `live/`; this replay
does not invoke a model. The original Phase 5 does not require a second build.

Prerequisites: Linux, Git, Python 3.12 with `venv`/pip, `prlimit` from util-linux,
and access to GitHub and the configured Python package index. This run uses the
owner-approved container fallback. It is not a real-sandbox or headless-generation
claim. No new account, paid API key or service is required.

Use a new directory. These exact published commits include the frozen approval,
the corrected entry and the generated candidate. Do not substitute `main` or
regenerate the approval packet. Both changes are still on PR branches.

```bash
mkdir task-tracker-reproduction
cd task-tracker-reproduction
git clone --single-branch --branch feat/contract-file-run --no-tags https://github.com/Abhillashjadhav/production-engineering-os.git peos
git -C peos checkout --detach 02959731e06d977e9ed61cfd15c962e5ebb85ee5
git clone --single-branch --branch docs/task-tracker-acceptance --no-tags https://github.com/Abhillashjadhav/PM-agent-OS.git pmos
git -C pmos checkout --detach 9d55bf650d6586d90a0028241b468559349487c3
cd peos
python3 --version
command -v prlimit
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python examples/barebones/contract-file.py verify \
  --packet ../pmos/reviews/task-tracker-v1 \
  --root PM-agent-OS=../pmos --root production-engineering-os=. \
  --freeze-digest sha256:1dd281e55cc20ce1861e3bed55799617191f38c5cc4e2322c7e463ef9a6e37f2 \
  --candidate docs/evidence/task-tracker-live-20260918/live/candidate \
  --output ../verification --authorized-host-fallback
cd ..
cp -R peos/docs/evidence/task-tracker-live-20260918/live/candidate candidate
mkdir journey
cp peos/docs/evidence/task-tracker-live-20260918/clean-install/journey.py journey/journey.py
peos/.venv/bin/python journey/journey.py "$PWD"
```

Expected: verification exits zero with all 14 criteria PASS and no findings;
the unchanged journey script exits zero after eight sequential commands. It
checks blank-title rejection, ID continuity, duplicate creation, completion,
repeated completion, and open/completed/all filtering across process restarts.
AC-013 independently runs ten strictly sequential creates, each process exiting
before the next starts. No parallel writers are tested.

Evidence is written to `verification/` and `journey/`. The temporary journey store
is intentionally disposable. Every authoritative verification process and every
journey command has before/after digest checks. Any mismatch fails the command;
never refresh hashes to make a changed artifact pass. A repeated verification
needs a new output directory. Installation resolves the declared dependencies;
this does not promise byte-identical dependency resolution on future dates.

For personal use after verification, from `task-tracker-reproduction`:

```bash
peos/.venv/bin/python candidate/product.py --store ./my-tasks.json create "Buy milk"
peos/.venv/bin/python candidate/product.py --store ./my-tasks.json complete 1
peos/.venv/bin/python candidate/product.py --store ./my-tasks.json list --status completed
```

Those launch examples assume a fresh `my-tasks.json`. Personal CLI use is not an
authoritative check run. Creation is not idempotent: repeating create makes a new
task. Completion is idempotent. Concurrent creation and crash/power-loss durability
are outside the approved scope.

## Exact environment exception

The owner closed Bubblewrap retries after user-namespace denial. Do not retry it
for this run. The fallback lacks extra user, PID, mount, IPC, UTS, cgroup and
network namespaces, read-only runtime/candidate mounts and private tmpfs/proc.
It retains every acceptance and digest check, path/output checks, timeouts and
`prlimit --as=1073741824 --cpu=11 --fsize=67108864 --nofile=256 --nproc=128`.
The verification entry has a 10-second action timeout; journey CLI commands have
a 2-second timeout. Root can alter evidence or restore transient changes between
hashes. Approval receipts remain forgeable. These are stated limitations, not
security guarantees or product-readiness claims.

The real-sandbox leg remains **BLOCKED_BY_ENVIRONMENT**. There is no unapproved
feature work, new product rule, or approval-forgery repair hidden in this replay.
