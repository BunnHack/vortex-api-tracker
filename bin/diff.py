#!/usr/bin/env python3
"""Diff an API snapshot against the newest stored snapshot.

Emits a machine-readable ADDED / REMOVED / CHANGED summary for the scripting
API between two Vortex Studio releases, and prints a short human log.

Usage:
    python3 bin/diff.py <new.json> [ <base.json> ]
    # if base omitted, uses the newest file in snapshots/
"""
import argparse
import fnmatch
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SNAP_DIR = os.path.join(ROOT, "snapshots")


def load(path):
    with open(path) as f:
        return json.load(f)


def newest_snapshot():
    """Newest snapshot by the timestamp embedded in its filename
    (YYYYMMDD-HHMMSS-...), not by mtime — git checkout makes all mtimes
    unreliable. Falls back to name sort, then mtime as a last resort."""
    files = glob.glob(os.path.join(SNAP_DIR, "*.json"))
    if not files:
        return None

    def stamp(p):
        m = re.search(r"(\d{8})-(\d{6})", os.path.basename(p))
        if m:
            return (1, m.group(1), m.group(2))
        return (0, os.path.basename(p), "")

    return max(files, key=stamp)


def keysets(base, new, *field_paths):
    """Return sets of dotted identifiers for a class field, e.g. (.methods)."""

    def collect(snap, fp):
        res = set()
        for cls in snap.get("classes", []):
            val = cls
            ok = True
            for step in fp:
                val = val.get(step)
                if val is None:
                    ok = False
                    break
            if ok:
                for item in val:
                    if isinstance(item, dict):
                        res.add(f"{cls['name']}.{item.get('name')}")
                    else:
                        res.add(f"{cls['name']}.{item}")
        return res

    base_s, new_s = set(), set()
    for fp in field_paths:
        base_s |= collect(base, fp)
        new_s |= collect(new, fp)
    return base_s, new_s


def diff(base, new):
    added = {"classes": [], "methods": [], "events": [], "enum": [], "types": []}
    removed = {"classes": [], "methods": [], "events": [], "enum": [], "types": []}

    base_cls = {c["name"] for c in base.get("classes", [])}
    new_cls = {c["name"] for c in new.get("classes", [])}
    added["classes"] = sorted(new_cls - base_cls)
    removed["classes"] = sorted(base_cls - new_cls)

    bm, nm = keysets(base, new, ["methods"])
    be, ne = keysets(base, new, ["events"])
    added["methods"] = sorted(nm - bm)
    removed["methods"] = sorted(bm - nm)
    added["events"] = sorted(ne - be)
    removed["events"] = sorted(be - ne)

    base_enum = set()
    new_enum = set()
    for name, vals in base.get("enum", {}).items():
        base_enum.add(f"{name}={','.join(sorted(vals))}")
    for name, vals in new.get("enum", {}).items():
        new_enum.add(f"{name}={','.join(sorted(vals))}")
    added["enum"] = sorted(set(e for e in (new_enum - base_enum)))
    removed["enum"] = sorted(base_enum - new_enum)

    base_type = {d.get("name") for d in base.get("datatypes", [])}
    new_type = {d.get("name") for d in new.get("datatypes", [])}
    added["types"] = sorted(new_type - base_type)
    removed["types"] = sorted(base_type - new_type)

    changed_services = sorted(set(new.get("services", [])) - set(base.get("services", [])))
    removed_services = sorted(set(base.get("services", [])) - set(new.get("services", [])))
    return {
        "added": added,
        "removed": removed,
        "changed_services": changed_services,
        "removed_services": removed_services,
    }


def fmt(result, new_ver, base_ver):
    lines = []
    lines.append(f"API diff  {base_ver}  ->  {new_ver}")
    total = sum(len(result["added"][k]) + len(result["removed"][k]) for k in result["added"])
    lines.append(f"totals: +{sum(len(v) for v in result['added'].values())} "
                 f"-{sum(len(v) for v in result['removed'].values())} "
                 f"+services={len(result['changed_services'])} "
                 f"-services={len(result['removed_services'])}")
    for kind in ["classes", "methods", "events", "enum", "types"]:
        if result["added"][kind]:
            lines.append(f"[+class/member] {kind}: " + ", ".join(result["added"][kind]))
        if result["removed"][kind]:
            lines.append(f"[-class/member] {kind}: " + ", ".join(result["removed"][kind]))
    if result["changed_services"]:
        lines.append("[~services] newly present: " + ", ".join(result["changed_services"]))
    if result["removed_services"]:
        lines.append("[-services] no longer present: " + ", ".join(result["removed_services"]))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("new_json", nargs="?", help="new snapshot JSON")
    ap.add_argument("base_json", nargs="?", help="base snapshot; defaults to newest in snapshots/")
    ap.add_argument("-o", "--out", help="write diff JSON to this path")
    args = ap.parse_args()

    if not args.new_json:
        ap.error("no new.json given")
    new = load(args.new_json)
    base_path = args.base_json or newest_snapshot()
    if not base_path:
        print("no baseline snapshot — committing as first tracked release", file=sys.stderr)
        return 0
    base = load(base_path)

    new_ver = new.get("version", {}).get("engine", "unknown")
    base_ver = base.get("version", {}).get("engine", "unknown")

    result = diff(base, new)
    print(fmt(result, new_ver, base_ver))

    if args.out:
        with open(args.out, "w") as f:
            json.dump({**result, "base": base_ver, "new": new_ver}, f, indent=2)
        print(f"[diff] wrote {args.out}", file=sys.stderr)
    has_changes = (any(result["added"][k] or result["removed"][k] for k in result["added"])
                   or bool(result["changed_services"] or result["removed_services"]))
    return 0 if has_changes else 1


if __name__ == "__main__":
    sys.exit(main())