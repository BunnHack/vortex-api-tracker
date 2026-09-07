#!/usr/bin/env bash
# End-to-end API tracker run: fetch -> extract -> analyze -> diff -> commit -> push.
# A snapshot file is only archived when the API actually changed; no-change runs
# produce nothing new in git, so the repo does not bloat.
# On CI (GH_TOKEN set) changes are committed and pushed back to origin.
set -euo pipefail
cd "$(dirname "$0")/.."

BIN=bin
SNAP=snapshots
REPORT=reports
mkdir -p "$SNAP" "$REPORT"

# ensure a git identity exists so commits work (harmless if already configured)
if ! git config user.name >/dev/null 2>&1; then
    git config user.name "vortex-bot"
fi
if ! git config user.email >/dev/null 2>&1; then
    git config user.email "vortex-bot@users.noreply.github.com"
fi

echo "== [1/4] fetch + extract studio =="
python3 "$BIN/fetch.py"

echo "== [2/4] analyze registry =="
python3 "$BIN/extract_registry.py" studio.exe > studio_snapshot.json

# keep the browser-facing snapshot in sync with the canonical JSON
python3 - <<'PY'
import json
snap = json.load(open("studio_snapshot.json"))
open("snapshot.js", "w").write("window.VORTEX_SNAPSHOT = " + json.dumps(snap) + ";\n")
PY

NEWVER=$(python3 -c "import json;print(json.load(open('studio_snapshot.json'))['version']['engine'])")
STAMP=$(date +%Y%m%d-%H%M%S)
REPORT_FILE="studio_snapshot.json"      # newest snapshot always at repo root

# newest *already committed* snapshot as the diff baseline (name-sorted).
LAST=$(git ls-files "$SNAP" '*.json' | sort | tail -1 || true)
if [ -z "$LAST" ] || [ ! -f "$LAST" ]; then
    LAST=$(ls "$SNAP"/*.json 2>/dev/null | sort | tail -1 || true)
fi

echo "== [3/4] diff =="
CHANGED=0
if [ -n "$LAST" ] && [ -f "$LAST" ]; then
    if python3 "$BIN/diff.py" "$REPORT_FILE" "$LAST" -o "$REPORT/${STAMP}.diff.json"; then
        echo "changes detected"
        CHANGED=1
    else
        echo "no API changes (identical to $LAST)"
    fi
else
    echo "no baseline yet — first tracked release"
    CHANGED=1
fi

echo "== [4/4] snapshot + commit + push =="
if [ "$CHANGED" = 1 ]; then
    SNAP_FILE="$SNAP/$STAMP-$NEWVER.json"
    cp "$REPORT_FILE" "$SNAP_FILE"
    echo -n "$STAMP  $NEWVER  " >> reports/history.log
    python3 - "$REPORT_FILE" >> reports/history.log <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
n = len(d["classes"])
for c in d["classes"]:
    n += len(c.get("methods", [])) + len(c.get("events", [])) + len(c.get("properties", []))
for v in d.get("enum", {}).values():
    n += len(v)
for t in d.get("datatypes", []):
    n += len(t.get("constructors", [])) + len(t.get("methods", [])) + len(t.get("properties", []))
print(f"symbols+={n} signature symbols")
PY
else
    # unchanged run: drop the (byte-identical) diff report so it is not committed
    rm -f "$REPORT/${STAMP}.diff.json"
    echo "nothing to archive (no change)"
fi

git add studio_snapshot.json snapshot.js snapshots/ reports/ 2>/dev/null || true
if git diff --cached --quiet; then
    echo "nothing to commit (no change)"
    exit 0
fi

git commit -q -m "track: $NEWVER snapshot ($STAMP) — $(git diff --cached --stat | tail -1)"
echo "committed snapshot $NEWVER"

# push back to the remote (GH_TOKEN auth on CI), else rely on origin
if [ -n "${GH_TOKEN:-}" ]; then
    REPO=$(git remote get-url origin)
    REPO=${REPO#https://}   # strip scheme so the token can be injected
    git remote set-url origin "https://x-access-token:${GH_TOKEN}@${REPO}"
fi
git push origin HEAD
echo "pushed $NEWVER snapshot"