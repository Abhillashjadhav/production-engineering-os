#!/bin/bash
# usage: natural.sh <label> <runner-variant> <iterations> <parallel> <hogs>
# Real, unmodified canonical app + production runner text (variant: diag = original runner
# plus one stderr line; fixed-diag = proposed one-line fix plus the same stderr line),
# exact production subprocess invocation, under <hogs> busy-loop CPU hogs.
W=/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w2
label=$1; variant=$2; n=$3; par=$4; hogs=$5
mkdir -p $W/logs/natural
pids=()
for i in $(seq 1 $hogs); do timeout 3000 python3 -c 'while True: pass' & pids+=($!); done
echo "# $label variant=$variant n=$n parallel=$par hogs=$hogs start=$(date -u +%T) load=$(cat /proc/loadavg)" > $W/logs/natural/$label.log
$W/peos/.venv/bin/python $W/harness/proof_harness.py --runner $variant --iterations $n --parallel $par \
   --jsonl $W/logs/natural/$label.jsonl >> $W/logs/natural/$label.log 2>&1
rc=$?
for p in "${pids[@]}"; do kill $p 2>/dev/null; done; wait 2>/dev/null
echo "# rc=$rc end=$(date -u +%T) load=$(cat /proc/loadavg)" >> $W/logs/natural/$label.log
grep -E "^SUMMARY" $W/logs/natural/$label.log
grep -c "^FAIL" $W/logs/natural/$label.log
