#!/bin/bash
# usage: run_condition.sh <name> <clone-dir> <venv-python> <control-json|none> <pytest args...>
W=/tmp/claude-0/-home-user/fe31551b-cc2b-5bfa-8931-d484034d32b5/scratchpad/w2
name=$1; clone=$2; py=$3; control=$4; shift 4
rm -f $W/demo-control.json
[ "$control" != none ] && echo "$control" > $W/demo-control.json
log=$W/logs/$name.log
{ echo "# condition=$name clone=$clone python=$py control=$control"; echo "# support_package.py sha256=$(sha256sum $clone/src/pmpe/support_package.py | cut -c1-64)"; echo "# start=$(date -u +%FT%TZ) loadavg=$(cat /proc/loadavg)"; } > $log
( cd $clone && $py -m pytest "$@" -o addopts="" -rs -p no:cacheprovider --durations=3 ) >> $log 2>&1
rc=$?
echo "# EXIT=$rc end=$(date -u +%FT%TZ)" >> $log
rm -f $W/demo-control.json
echo "$name: EXIT=$rc $(grep -E '^=+ .*(passed|failed|error).* in ' $log | tail -1) $(grep -E '^E +.*PackageContractError' $log | head -1 | sed 's/^E *//')"
