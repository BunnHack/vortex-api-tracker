# Vortex API Tracker

Watches the **Vortex Studio scripting API** for changes across releases.

Each run logs into playvortex.io, downloads `Studio-windows` (`VortexStudio.exe`),
and scans the embedded Lua scripting registry for classes, methods, events,
data types and services. Any addition or removal across versions is surfaced as
a readable ADDED / REMOVED diff **and** committed as a snapshot — so the history
of the engine's scripting surface is the git history.

> Symbol presence only. Official call syntax is **not** assumed; we fingerprint
> the registry strings so diffs are stable, not prose.

## What it produces

- `studio_snapshot.json` — newest analyzed registry
- `snapshots/<stamp>-<version>.json` — committed snapshot per release (diff baseline)
- `reports/<stamp>.diff.json` — machine-readable ADDED / REMOVED diff
- `reports/history.log` — one-line changelog per tracked version

## Usage

```bash
export VORTEX_USER=bunn
export VORTEX_PASSWORD=you-know-it

bash bin/track.sh                      # fetch → extract → analyze → diff → commit
python3 bin/extract_registry.py studio.exe > studio_snapshot.json   # analyze any PE
python3 bin/diff.py new.json base.json -o out.diff.json             # compare snapshots
```

`fetch.py` needs `requests` (`pip install requests`).

## Automation

`.github/workflows/track.yml` runs the tracker **daily at 06:00 UTC** (and
on-demand via the Actions → *vortex-api-track* → *Run workflow* button).
Set the `VORTEX_USER` and `VORTEX_PASSWORD` **repository secrets** under
Settings → Secrets and variables → Actions.

## Layout

```
bin/fetch.py             login + download studio-windows zip, extract the PE
bin/extract_registry.py  PE → scripting-API JSON (classes/methods/events/types)
bin/diff.py              ADDED / REMOVED between two snapshots
bin/track.sh             end-to-end run (used by the workflow)
```

## Notes

- Read-only monitoring: downloads Vortex's own publicly hosted installer, runs
  no code from it, and only reads strings off the PE.
- The 64 MB installer and 160 MB PE are gitignored — only the small JSON
  snapshots are committed, so the repo stays lean.