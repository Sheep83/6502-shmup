#!/bin/bash
# Run a tier of suites, collect every verdict, fail at the end if any failed.
# Launches no emulator itself; each suite owns and reaps its own VICE PIDs.
tier="$1"; shift
pass=0; fail=0; failed=()
start=$(date +%s)
for t in "$@"; do
  s=$(date +%s)
  out=$(python3 "tests/test_$t.py" 2>&1)
  e=$(date +%s)
  if grep -q '=== ALL PASS ===' <<<"$out"; then
    printf '  ok   %-22s %4ss\n' "$t" "$((e-s))"; pass=$((pass+1))
  else
    n=$(grep -oE '^=== [0-9]+ FAILURES' <<<"$out" | grep -oE '[0-9]+' | head -1)
    printf '  FAIL %-22s %4ss  %s\n' "$t" "$((e-s))" "${n:-error}"
    grep -E '^  FAIL' <<<"$out" | head -3 | sed 's/^/         /'
    fail=$((fail+1)); failed+=("$t")
  fi
done
end=$(date +%s)
echo "--------------------------------------------------------------"
printf '%s: %d passed, %d failed, %ds total\n' "$tier" "$pass" "$fail" "$((end-start))"
[ "$fail" -gt 0 ] && { echo "failed: ${failed[*]}"; exit 1; }
exit 0
