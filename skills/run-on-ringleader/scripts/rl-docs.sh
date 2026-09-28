#!/usr/bin/env bash
# Dump `rl docs` to a file and print a heading index, so an agent can read slices instead of
# pulling ~1.2 MB into its context.
#
#   scripts/rl-docs.sh [outfile]        # default: /tmp/rl-docs.txt
#   scripts/rl-docs.sh - <pattern>      # index only the headings matching a pattern
#
# Then read a slice:
#   sed -n '<start>,<end>p' <outfile>
#   grep -n 'defaultLocalBinding' <outfile>
#
# The index skips fenced code blocks, because `rl docs` is full of shell snippets whose comment
# lines start with '#' and would otherwise flood the index with fake headings.
set -euo pipefail

out="${1:-/tmp/rl-docs.txt}"
filter="${2:-}"
rl="${RL:-rl}"

if [[ "$out" == "-" ]]; then
  out=/tmp/rl-docs.txt
fi

"$rl" docs > "$out"

bytes=$(wc -c < "$out" | tr -d ' ')
lines=$(wc -l < "$out" | tr -d ' ')
echo "wrote $out (${bytes} bytes, ${lines} lines) — read slices, never the whole file"
echo

index=$(awk '
  /^```/ { fence = !fence; next }
  !fence && /^#{1,3} / { printf "%6d  %s\n", NR, $0 }
' "$out")

if [[ -n "$filter" ]]; then
  echo "── headings matching /$filter/ ──"
  echo "$index" | grep -i -- "$filter" || echo "(no match)"
else
  echo "── heading index (line  heading) ──"
  echo "$index"
fi
