set -euo pipefail
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
