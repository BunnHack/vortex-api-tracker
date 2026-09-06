#!/usr/bin/env bash
# End-to-end API tracker run: fetch -> extract -> analyze -> diff -> commit.
set -euo pipefail
cd "$(dirname "$0")/.."

BIN=bin
SNAP=snapshots
REPORT=reports
mkdir -p "$SNAP" "$REPORT"

echo "== [1/4] fetch + extract studio =="
python3 "$BIN/fetch.py"

echo "== [2/4] analyze registry =="
python3 "$BIN/extract_registry.py" studio.exe > studio_snapshot.json

NEWVER=$(python3 -c "import json;print(json.load(open('studio_snapshot.json'))['version']['engine'])")
STAMP=$(date +%Y%m%d-%H%M%S)
REPORT_FILE="studio_snapshot.json"     # newest snapshot always at repo root
SNAP_FILE="$SNAP/$STAMP-$NEWVER.json"

# keep the newest baseline for diffing
LAST=$(ls "$SNAP"/*.json 2>/dev/null | sort | tail -1 || true)

echo "== [3/4] diff =="
if [ -n "$LAST" ] && [ -f "$LAST" ]; then
    if python3 "$BIN/diff.py" "$REPORT_FILE" "$LAST" -o "$REPORT/${STAMP}.diff.json"; then
        echo "changes detected"
    else
        echo "no API changes (identical to $LAST)"
    fi
else
    echo "no baseline yet — first tracked release"
fi

echo "== [4/4] commit snapshot =="
cp "$REPORT_FILE" "$SNAP_FILE"
mkdir -p reports
{
    echo -n "$STAMP  $NEWVER  "
    printf '%s' "$(python3 -c "import json;d=json.load(open('$REPORT_FILE'));print(len(d['classes'])+len(d['enum'])+len(d['datatypes']))" ) symbols"
} >> reports/history.log

git add -A studio_snapshot.json snapshots/ reports/history.log 2>/dev/null || true
if git diff --cached --quiet; then
    echo "nothing to commit (no change)"
    git clean -f -q -e 'studio.exe' -e 'studio.zip' -e '*.diff.json' studio_snapshot.json 2>/dev/null || true
else
    git commit -q -m "track: $NEWVER snapshot ($STAMP) — $(git diff --cached --stat | tail -1)"
    echo "committed snapshot $NEWVER"
fi