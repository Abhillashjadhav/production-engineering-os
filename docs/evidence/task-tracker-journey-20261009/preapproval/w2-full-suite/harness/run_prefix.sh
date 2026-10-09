#!/bin/bash
# usage: run_prefix.sh <label> <clone> <python>
# Condition 2(d): run the 68 unit modules that precede test_support_package_v1.py in
# collection order, then that module, in ONE pytest process (documented flags + -v
# and --durations for timing), with per-line UTC timestamps and a 2 s load/thread sampler.
W=/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w2
label=$1; clone=$2; py=$3
mkdir -p $W/logs/repro/$label
log=$W/logs/repro/$label/pytest.log
cd $clone
$py -m pytest $(cat $W/logs/d-prefix-modules.txt) -o addopts="" -rs -p no:cacheprovider -v --durations=15 \
  > >(python3 -u -c "import sys,datetime
for l in sys.stdin: sys.stdout.write(datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S ')+l)" > $log) 2>&1 &
pid=$!
bash $W/harness/sampler.sh $pid $W/logs/repro/$label/sampler.txt &
wait $pid; rc=$?
sleep 1
echo "EXIT=$rc" >> $log
echo "$label EXIT=$rc $(grep -E '=+ .*(passed|failed|error).* in ' $log | tail -1)"
