#!/bin/bash
# Runs a command once per profile, with GARMIN_DATA_DIR pointing at each one.
# This is how the daily sync serves the whole household instead of only the
# first person who registered.
set -u
root="${GARMIN_DATA_DIR_ROOT:-/data}"

python3 -c "import sys; sys.path.insert(0,'/opt/coach'); import profiles; profiles.migrate()" 2>/dev/null || true

names=$(ls -1 "$root/profiles" 2>/dev/null || true)
if [ -z "$names" ]; then
  echo "No profiles in $root/profiles. Set the first one up on the web page."
  exit 0
fi

failures=0
for name in $names; do
  [ -d "$root/profiles/$name" ] || continue
  echo "=== $name ==="
  GARMIN_DATA_DIR="$root/profiles/$name" "$@" || { echo "$name: failed"; failures=$((failures+1)); }
done
exit $((failures > 0))
