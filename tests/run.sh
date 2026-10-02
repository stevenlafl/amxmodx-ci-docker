#!/bin/bash
# Tests compile.sh and lint.sh in an image: tests/run.sh <image>
IMAGE=${1:?usage: tests/run.sh <image>}
FIX=$(cd "$(dirname "$0")/fixtures" && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
pass=0 fail=0

# run <dir> <entrypoint> <args...>: runs in a fresh copy, sets $rc and $out
run() {
  local dir=$1 entry=$2; shift 2
  out=$(docker run --rm --user "$(id -u):$(id -g)" -v "$dir":/app -w /app --entrypoint "$entry" "$IMAGE" "$@" 2>&1)
  rc=$?
}
fresh() { rm -rf "$WORK/case"; mkdir -p "$WORK/case"; cp -a "$1"/. "$WORK/case/"; echo "$WORK/case"; }
check() {
  if eval "$2"; then pass=$((pass + 1)); echo "ok   $1"
  else fail=$((fail + 1)); echo "FAIL $1"; echo "$out" | sed 's/^/     | /' | tail -15; fi
}
outputs() { (cd "$1/compiled" 2>/dev/null && ls | sort | tr '\n' ' '); }

# compile.sh, no arguments: every *.sma in the current folder, always exit 0
d=$(fresh "$FIX/flat"); run "$d" compile.sh
check "no args compiles the folder" '[ $rc = 0 ] && [ "$(outputs "$d")" = "a copy.amxx a.amxx " ]'
check "no args keeps file order" '[ "$(echo "$out" | grep ^Compiling | tr "\n" "|")" = "Compiling a copy.sma ...|Compiling a.sma ...|" ]'
d=$(fresh "$FIX/flat"); cp "$FIX/broken.sma" "$d/"; run "$d" compile.sh
check "no args exits 0 even when a plugin fails" '[ $rc = 0 ] && [ "$(outputs "$d")" = "a copy.amxx a.amxx " ]'

# compile.sh with one file
d=$(fresh "$FIX/flat"); run "$d" compile.sh a.sma
check "single file" '[ $rc = 0 ] && [ "$(outputs "$d")" = "a.amxx " ]'
d=$(fresh "$FIX/flat"); cp "$FIX/broken.sma" "$d/"; run "$d" compile.sh broken.sma
check "single broken file exits 1 with no output" '[ $rc = 1 ] && [ -z "$(outputs "$d")" ]'
d=$(fresh "$FIX/flat"); cp "$FIX/broken.sma" "$d/"; mkdir -p "$d/compiled"; echo old > "$d/compiled/broken.amxx"; run "$d" compile.sh broken.sma
check "failed compile leaves an older output alone" '[ $rc = 1 ] && [ "$(cat "$d/compiled/broken.amxx")" = old ]'
d=$(fresh "$FIX/flat"); run "$d" compile.sh a.sma -ocustom.amxx
check "custom -o keeps the original behavior" '[ $rc = 0 ] && [ "$(outputs "$d")" = "custom.amxx " ]'

# compile.sh with directories and files
d=$(fresh "$FIX/tree"); run "$d" compile.sh base extra
check "directories, include folder found under base" '[ $rc = 0 ] && [ "$(outputs "$d")" = "idle.amxx provider.amxx user.amxx " ] && echo "$out" | grep -qx "3 compiled, 0 failed"'
d=$(fresh "$FIX/tree"); cp "$FIX/broken.sma" "$d/extra/"; run "$d" compile.sh base extra
check "directories with a broken plugin" '[ $rc = 1 ] && [ "$(outputs "$d")" = "idle.amxx provider.amxx user.amxx " ] && echo "$out" | grep -qx "3 compiled, 1 failed" && echo "$out" | grep -qx "  extra/broken.sma"'
d=$(fresh "$FIX/tree"); run "$d" compile.sh base/scripting/include extra/user/scripting/user.sma
check "file argument uses include folders from other arguments" '[ $rc = 0 ] && [ "$(outputs "$d")" = "user.amxx " ]'
d=$(fresh "$FIX/tree"); out=$(docker run --rm --user "$(id -u):$(id -g)" -e JOBS=1 -v "$d":/app --entrypoint compile.sh "$IMAGE" base extra 2>&1); rc=$?
check "JOBS=1" '[ $rc = 0 ] && [ "$(outputs "$d")" = "idle.amxx provider.amxx user.amxx " ]'

# lint.sh
d=$(fresh "$FIX/tree"); run "$d" lint.sh base extra
check "lint finds an include that only adds a requirement" '[ $rc = 0 ] && echo "$out" | grep -q "idle.sma:2: <mylib> is only a load-time requirement: ?rl_mylib"'
check "lint finds a native nothing calls" 'echo "$out" | grep -q "mylib_unused (registered by provider)"'
check "lint resolves requirements to the providing plugin" 'echo "$out" | grep -q "user needs mylib (plugin: provider)"'
d=$(fresh "$FIX/tree"); run "$d" lint.sh --strict --plugins-ini plugins-without-provider.ini base extra
check "lint --strict fails when a plugins.ini lacks a provider" '[ $rc = 1 ] && echo "$out" | grep -q "user is enabled but needs mylib, provided by provider, which is not enabled"'
d=$(fresh "$FIX/tree"); run "$d" lint.sh --strict --plugins-ini plugins.ini base extra
check "lint --strict passes with a complete plugins.ini" '[ $rc = 0 ]'

# Every game mod's stock includes are present and compile
d=$(fresh "$FIX/stock"); run "$d" compile.sh .
check "stock includes for every mod compile" '[ $rc = 0 ] && echo "$out" | grep -qx "7 compiled, 0 failed"'

echo "$pass passed, $fail failed"
[ $fail = 0 ]
