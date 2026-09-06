#!/usr/bin/env python3
"""Extract the embedded Lua scripting registry from a VortexStudio.exe PE.

Vortex Studio's scripting API is registered in the binary as (mostly
case-concatenated) symbol strings: class names, method/event names, enum values,
data-type helpers and global/`GetService` lookups. Official call syntax is NOT
assumed here — we only fingerprint the presence of symbols and let diffs surface
additions/removals across releases.

Operates on raw bytes only (string scan). Never executes the binary.

Usage:
    python3 bin/extract_registry.py <studio.exe> > report.json

Output JSON:
    {
      "version": "engine 2.6.0",
      "build_hash": "rustc 59807616e1fa...",
      "classes":  [ { "name","methods":[],"events":[] ,"properties":[] } ],
      "enum":     { "HumanoidStateType": [...] },
      "datatypes": [ {...} ],
      "services": [...],
      "globals":  [...]
    }
"""
import json
import os
import re
import sys


# --- symbol fingerprints (case-insensitive, prefix/boundary aware) ---------
INSTANCE_METHODS = [
    "GetChildren", "GetDescendants", "FindFirstChild", "WaitForChild",
    "FindFirstChildOfClass", "IsA", "GetPropertyChangedSignal",
    "SetAttribute", "GetAttribute", "GetAttributes", "GetAttributeChangedSignal",
    "Destroy", "Clone",
]

REMOTE_METHODS = ["FireServer", "FireClient", "FireAllClients", "InvokeServer"]
REMOTE_EVENTS = ["OnServerEvent", "OnClientEvent", "OnServerInvoke"]
HUMANOID_EVENTS = [
    "HealthChanged", "Died", "StateChanged", "Jumping", "FreeFalling", "Running",
]
PLAYER_EVENTS = ["CharacterAdded", "CharacterRemoving"]
PLAYERS_EVENTS = ["PlayerAdded", "PlayerRemoving"]
RUNSERVICE_EVENTS = ["Heartbeat"]

CLASSES = [
    # services
    "Workspace", "Lighting", "Camera", "ReplicatedStorage",
    "StarterPlayerScripts", "ServerScriptService", "Players", "RunService",
    "Debris", "TweenService", "UserInputService",
    # world / parts
    "Model", "Part", "Baseplate", "SpawnLocation", "Truss", "Texture",
    "PointLight", "SpotLight", "DirectionalLight",
    # scripts
    "Script", "LocalScript", "ModuleScript",
    # remotes
    "RemoteEvent", "BindableEvent", "RemoteFunction",
    # values / misc
    "IntValue", "StringValue", "Humanoid", "Player", "Instance",
]
# classes that appeared only inside larger concatenated blocks
EXTRA_CLASS_TOKENS = ["Serverscript", "ServerStorage", "StarterGui", "StarterPack"]

DATATYPES = {
    "Vector3": {
        "constructors": ["Vector3.new"],
        "properties": ["X", "Y", "Z"],
        "methods": ["Magnitude", "zero"],
    },
    "Color3": {
        "constructors": ["Color3.fromRGB"],
        "properties": ["R", "G", "B"],
    },
    "CFrame": {
        "constructors": ["CFrame.fromMatrix"],
        "methods": ["LookAt", "Inverse", "Lerp", "Dot", "Unit",
                     "xAxis", "yAxis", "zAxis", "qx", "qy", "qz", "qw"],
    },
    "Enum": {
        "methods": ["GetEnumItems", "FromName", "FromValue"],
    },
}

SERVICES = [
    "Workspace", "Lighting", "Camera", "ReplicatedStorage",
    "StarterPlayerScripts", "ServerScriptService", "Players", "RunService",
    "Debris", "TweenService", "UserInputService",
]

GLOBALS = ["game", "workspace", "script", "Instance", "ipairs", "pairs",
           "require", "setmetatable", "print"]


def read_ascii(data):
    # real strings tool equivalent: printable ASCII runs of length >= 4
    out = []
    for m in re.finditer(rb"[\x20-\x7e]{4,}", data):
        out.append(m.group().decode("ascii"))
    return out


def read_utf16(data):
    out = []
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00){4,}", data):
        out.append(m.group().decode("utf-16le"))
    return out


def norm(s, lower=True):
    return s.lower() if lower else s


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    path = sys.argv[1]
    data = open(path, "rb").read()

    ascii_strs = read_ascii(data)
    utf16 = read_utf16(data)
    haystacks = {
        "ascii": [norm(x) for x in ascii_strs],
        "utf16": [norm(x) for x in utf16],
    }
    # also the concatenated "blob" views (registry dumps collide adjacent tokens)
    all_text = ascii_strs + utf16
    blob = norm("".join(all_text))

    def seen(*symbols):
        """True if every symbol appears somewhere in the raw strings (loose)."""
        for sym in symbols:
            t = norm(sym)
            if any(t in h for h in haystacks["ascii"]) or t in blob:
                return True
        return False

    def strong(*symbols):
        """Strict match: appears as its own run (best signal)."""
        for sym in symbols:
            t = norm(sym)
            if t in {norm(x) for x in all_text}:
                return True
            if t in blob:
                return True
        return False

    classes = []
    for c in CLASSES:
        entry = {
            "name": c,
            "methods": [],
            "events": [],
            "properties": [],
            "services": c in SERVICES,
        }
        # per-class associations (loose but useful for diffing)
        if c in ("RemoteEvent", "RemoteFunction", "BindableEvent"):
            entry["methods"] = [m for m in REMOTE_METHODS if seen(m)]
            entry["events"] = [e for e in REMOTE_EVENTS if seen(e)]
        if c == "Humanoid":
            entry["events"] = [e for e in HUMANOID_EVENTS if strong(e)]
        if c == "Player":
            entry["events"] = [e for e in PLAYER_EVENTS if strong(e)]
        if c == "Players":
            entry["events"] = [e for e in PLAYERS_EVENTS if strong(e)]
        if c == "RunService":
            entry["events"] = [e for e in RUNSERVICE_EVENTS if strong(e)]
        if c == "Instance":
            entry["methods"] = [m for m in INSTANCE_METHODS if seen(m)]
            entry["services"] = False
        classes.append(entry)

    enum_data = {}
    if seen("EnumHumanoidStateType", "HumanoidStateType"):
        values = []
        for v in ["Standing", "Running", "Jumping", "FreeFalling", "Climbing", "Dead"]:
            if strong(v):
                values.append(v)
        enum_data["HumanoidStateType"] = values

    datatypes = []
    for name, spec in DATATYPES.items():
        present = {
            "name": name,
            "constructors": [c for c in spec.get("constructors", []) if strong(c.split(".")[-1])],
            "methods": [m for m in spec.get("methods", []) if strong(m)],
            "properties": [p for p in spec.get("properties", []) if strong(p)],
        }
        datatypes.append(present)

    snapshot = {
        "classes": classes,
        "enum": enum_data,
        "datatypes": datatypes,
        "services": [s for s in SERVICES if strong(s)],
        "globals": [g for g in GLOBALS if strong(g)],
        "absent": {
            # known-stable negatives worth tracking for regressions
            "gui": [g for g in ["ScreenGui", "GuiObject", "TextButton",
                                "TextLabel", "ImageLabel", "MouseButton1Click"] if strong(g)],
            "http": [h for h in ["HttpGet", "HttpService", "DataStore"] if strong(h)],
            "renders": [r for r in ["RenderStepped"] if strong(r)],
        },
    }

    # detect engine version / rust commit from known literals
    meta = {
        "engine": "engine 2.6.0",
        "build": "",
    }
    m = re.search(r"rustc[ :-]([0-9a-f]{16})", " ".join(ascii_strs))
    if m:
        meta["build"] = f"rustc {m.group(1)}…"
    snapshot["version"] = meta

    json.dump(snapshot, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()