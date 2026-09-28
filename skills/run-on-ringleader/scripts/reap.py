#!/usr/bin/env python3
"""Teardown backstop for the run-on-ringleader skill.

Deletes exactly the objects a `.ringleader/` manifest set declares, then verifies they are gone.

    scripts/reap.py .ringleader [-n <namespace>] [--dry-run] [--timeout 600]

SAFETY: it only ever deletes objects NAMED IN THE MANIFESTS. It will not delete an object it
merely thinks looks related, and it will not delete by label or prefix. A leftover that is not
in the manifests is reported, never removed.

Exit codes: 0 = everything gone · 1 = something survived · 2 = usage/environment error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("reap.py needs PyYAML (pip install pyyaml)", file=sys.stderr)
    raise SystemExit(2)

RL = os.environ.get("RL", "rl")

# Delete in reverse dependency order: the Workstation first (it owns the VM), then the things
# that only describe it.
KIND_ORDER = ["Workstation", "LocalBinding", "SSHKey", "WorkstationConfig", "Secret", "ConfigMap"]

# kind -> the CLI noun `rl` uses for it.
KIND_NOUN = {
    "Workstation": "workstation",
    "WorkstationConfig": "workstationconfig",
    "SSHKey": "sshkey",
    "LocalBinding": "binding",
    "Secret": "secret",
    "ConfigMap": "configmap",
}


def run(args: list[str], timeout: int = 120) -> tuple[int, str, str]:
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def declared_objects(manifest_dir: Path) -> list[tuple[str, str]]:
    """Every (kind, name) the manifests declare, deduped, in deletion order."""
    found: list[tuple[str, str]] = []
    for path in sorted(manifest_dir.glob("*.y*ml")):
        try:
            docs = list(yaml.safe_load_all(path.read_text()))
        except yaml.YAMLError as exc:
            print(f"warning: cannot parse {path}: {exc}", file=sys.stderr)
            continue
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            kind = doc.get("kind")
            name = (doc.get("metadata") or {}).get("name")
            if kind and name and (kind, name) not in found:
                found.append((kind, name))

    def sort_key(item: tuple[str, str]) -> int:
        kind = item[0]
        return KIND_ORDER.index(kind) if kind in KIND_ORDER else len(KIND_ORDER)

    return sorted(found, key=sort_key)


def ns_args(namespace: str | None) -> list[str]:
    return ["-n", namespace] if namespace else []


def name_pattern(raw: str) -> re.Pattern:
    """Match a manifest name whose `${...}` tokens the CLI expands at apply time.

    A manifest name like `myapp-${shortHash:creatorUserId}` never appears literally in the
    store — the CLI resolves it client-side. Looking for the raw string finds nothing, and
    "nothing found" reads as "already deleted": this tool would report a clean environment
    while the workstation was still running. So match a pattern, never the raw string.
    """
    parts = re.split(r"\$\{[^}]*\}", raw)
    # The digest is bare alphanumerics — NO separators. Allowing `-` here made
    # `memeleader-${...}` match a live, unrelated `memeleader-gcp-box-5098e52d`, which this
    # tool would then have DELETED. Keep this class tight.
    return re.compile(r"^" + "[A-Za-z0-9]+".join(re.escape(p) for p in parts) + r"$")


def live_names(kind: str, raw: str, namespace: str | None) -> list[str]:
    """Resolved names of objects of `kind` matching this declared (possibly templated) name."""
    noun = KIND_NOUN.get(kind, kind.lower())
    scope = ns_args(namespace) or ["-A"]
    code, stdout, _ = run([RL, noun, "get", *scope, "-o", "json"])
    if code != 0:
        # Unknown is not empty. Surface it rather than reporting "already gone".
        raise RuntimeError(f"cannot list {noun}: `rl {noun} get` exited {code}")
    try:
        doc = json.loads(stdout) if stdout.strip() else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"cannot parse `rl {noun} get` output: {exc}") from exc
    items = doc.get("items", []) if isinstance(doc, dict) else (doc if isinstance(doc, list) else [])
    pat = name_pattern(raw)
    return sorted(
        (item or {}).get("metadata", {}).get("name", "")
        for item in items
        if pat.match((item or {}).get("metadata", {}).get("name", ""))
    )


def delete(kind: str, name: str, namespace: str | None) -> tuple[bool, str]:
    noun = KIND_NOUN.get(kind, kind.lower())
    code, out, err = run([RL, noun, "delete", name, "-y", *ns_args(namespace)], timeout=300)
    return code == 0, (err or out).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest_dir", nargs="?", default=".ringleader", type=Path)
    ap.add_argument("-n", "--namespace", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--timeout", type=int, default=600, help="seconds to wait for objects to disappear")
    ap.add_argument("--json", action="store_true", help="emit a machine-readable summary")
    args = ap.parse_args()

    if not args.manifest_dir.is_dir():
        print(f"no such directory: {args.manifest_dir}", file=sys.stderr)
        return 2

    objects = declared_objects(args.manifest_dir)
    if not objects:
        print(f"no objects declared in {args.manifest_dir}")
        return 0

    print(f"declared in {args.manifest_dir}:")
    for kind, name in objects:
        print(f"  {kind}/{name}")

    if args.dry_run:
        print("\n--dry-run: nothing deleted")
        return 0

    deleted, failed = [], []
    resolved: list[tuple[str, str]] = []   # (kind, RESOLVED name) — what we actually act on
    for kind, raw in objects:
        try:
            names = live_names(kind, raw, args.namespace)
        except RuntimeError as exc:
            print(f"  {kind}/{raw}: CANNOT VERIFY — {exc}", file=sys.stderr)
            failed.append(f"{kind}/{raw}")
            continue
        if not names:
            print(f"  {kind}/{raw}: already gone")
            continue
        for name in names:
            resolved.append((kind, name))
            ok, detail = delete(kind, name, args.namespace)
            if ok:
                print(f"  {kind}/{name}: delete issued")
                deleted.append(f"{kind}/{name}")
            else:
                print(f"  {kind}/{name}: DELETE FAILED — {detail}", file=sys.stderr)
                failed.append(f"{kind}/{name}")

    # A Workstation passes through Terminating while its VM is destroyed. Poll until the row is
    # actually gone rather than trusting the delete call.
    deadline = time.time() + args.timeout
    pending = list(resolved)
    while pending and time.time() < deadline:
        still = []
        for k, n in pending:
            try:
                if n in live_names(k, n, args.namespace):
                    still.append((k, n))
            except RuntimeError:
                still.append((k, n))   # cannot verify => assume present, never assume gone
        pending = still
        if pending:
            time.sleep(5)

    leftovers = [f"{k}/{n}" for k, n in pending]
    summary = {
        "manifestDir": str(args.manifest_dir),
        "namespace": args.namespace,
        "declared": [f"{k}/{n}" for k, n in objects],
        "deleted": deleted,
        "deleteFailed": failed,
        "leftovers": leftovers,
        "clean": not leftovers,
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    elif leftovers:
        print("\nSTILL PRESENT after teardown:", file=sys.stderr)
        for item in leftovers:
            print(f"  {item}", file=sys.stderr)
    else:
        print("\nclean — every declared object is gone")

    return 1 if leftovers else 0


if __name__ == "__main__":
    raise SystemExit(main())
