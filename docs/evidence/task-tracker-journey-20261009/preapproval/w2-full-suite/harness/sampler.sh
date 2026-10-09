#!/bin/bash
# usage: sampler.sh <pid> <outfile>
# Every 2 s: UTC time, 1-min load, threads of <pid>, number of live descendants of <pid>,
# and the newest pytest test id line in the log is not needed (timestamps are joined later).
pid=$1; out=$2
echo "# time load1 threads descendants" > "$out"
while kill -0 "$pid" 2>/dev/null; do
  threads=$(awk '/^Threads:/{print $2}' /proc/$pid/status 2>/dev/null)
  # count descendants by walking /proc (PPid chains)
  desc=$(awk -v root="$pid" '
    FNR==1 { file=FILENAME }
    /^PPid:/ { split(file, a, "/"); ppid[a[3]]=$2 }
    END {
      n=0
      for (p in ppid) { q=p; hops=0
        while (q in ppid && hops < 64) { q=ppid[q]; hops++; if (q==root) { n++; break } } }
      print n }' /proc/[0-9]*/status 2>/dev/null)
  echo "$(date -u +%T) $(cut -d' ' -f1 /proc/loadavg) ${threads:-NA} ${desc:-NA}" >> "$out"
  sleep 2
done
echo "# pid $pid exited $(date -u +%T)" >> "$out"
