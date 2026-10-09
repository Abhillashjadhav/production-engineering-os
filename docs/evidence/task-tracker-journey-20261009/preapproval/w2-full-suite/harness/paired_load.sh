#!/bin/bash
# usage: paired_load.sh <hogs> <count> <label-suffix> <pytest target>
# Runs repeat.sh for the ORIGINAL clone (peos) and the PATCHED clone (peos-fix) at the same
# time, under <hogs> busy-loop CPU hogs, so both variants see identical contention.
W=/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w2
hogs=$1; n=$2; suffix=$3; target=$4
pids=()
for i in $(seq 1 $hogs); do timeout 7000 python3 -c 'while True: pass' & pids+=($!); done
echo "hogs=$hogs started $(date -u +%T) load=$(cat /proc/loadavg)"
$W/harness/repeat.sh c-orig-$suffix $n $W/peos $W/peos/.venv/bin/python $target > /dev/null 2>&1 &
a=$!
$W/harness/repeat.sh c-fix-$suffix $n $W/peos-fix $W/peos-fix/.venv/bin/python $target > /dev/null 2>&1 &
b=$!
wait $a $b
for p in "${pids[@]}"; do kill $p 2>/dev/null; done; wait 2>/dev/null
echo "done $(date -u +%T) load=$(cat /proc/loadavg)"
tail -1 $W/logs/repro/c-orig-$suffix/SUMMARY.txt
tail -1 $W/logs/repro/c-fix-$suffix/SUMMARY.txt
