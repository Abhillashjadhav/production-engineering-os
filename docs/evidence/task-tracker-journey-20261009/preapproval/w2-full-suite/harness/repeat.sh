#!/bin/bash
# usage: repeat.sh <label> <count> <clone> <python> <pytest targets...>
# Runs pytest <count> times exactly like the documented invocation (+ --durations=5 for timing),
# one raw log per iteration, one summary line per iteration.
W=/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w2
label=$1; n=$2; clone=$3; py=$4; shift 4
mkdir -p $W/logs/repro/$label
sum=$W/logs/repro/$label/SUMMARY.txt; : > $sum
for i in $(seq 1 $n); do
  log=$W/logs/repro/$label/run-$(printf %02d $i).log
  start=$(date -u +%T); la=$(cut -d' ' -f1 /proc/loadavg)
  ( cd $clone && $py -m pytest "$@" -o addopts="" -rs -p no:cacheprovider --durations=5 ) > $log 2>&1
  rc=$?
  line=$(grep -E '^=+ .*(passed|failed|error).* in ' $log | tail -1 | sed 's/=//g')
  err=$(grep -E '^E +.*Error' $log | head -1 | sed 's/^E *//')
  echo "$label run=$i start=$start load1=$la rc=$rc ::$line :: $err" | tee -a $sum
done
echo "TOTAL $label: runs=$n failing_runs=$(grep -vc 'rc=0 ' $sum)" | tee -a $sum
