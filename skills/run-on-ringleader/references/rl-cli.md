# `rl` command cheat-sheet

**`rl docs` is the authority.** This file is a verified starting point so you know *what to look
up*; when it disagrees with `rl docs` or with `rl <cmd> --help`, the binary wins.

## Reading `rl docs` without burning context

The bundle is **~1.2 MB / ~10,700 lines**. Dump once, index, read slices:

```bash
scripts/rl-docs.sh /tmp/rl-docs.txt                 # dump + heading index (skips code fences)
scripts/rl-docs.sh /tmp/rl-docs.txt binding         # index only matching headings
sed -n '3063,3200p' /tmp/rl-docs.txt                # read one section
grep -n 'defaultLocalBinding' /tmp/rl-docs.txt      # find a field
```

Useful anchors in the current bundle (line numbers move — re-index, do not memorise these):
the `rl workstation …` verb reference, `rl shell`, `rl logs`, `rl troubleshoot`, and the
Workstations / WorkstationConfig schema sections.

## Grammar

`rl <kind> <verb>` is canonical (`rl workstation get`). The kubectl-style `rl <verb> <kind>`
forms still work but are hidden. Kind tokens are registry-resolved: `workstation` = `ws` =
`workstations`.

Exit codes: **0** success · **1** operation failed / wait timed out / object not found ·
**2** usage error. Exception: `rl diff` exits **1** when differences exist — that is not an error.

## The commands this skill uses

### Apply / diff / delete

```bash
rl apply -f <file|url|-> [-o yaml|json] [--as <subject>] [--home <dir>]
rl diff  -f <file>                                  # exit 1 = differs, not an error
rl workstation delete <name> [-n <ns>] -y
rl workstation delete -f <file> -y                  # deletes every object THAT FILE declares
```

Two things verified against the binary that a cheat-sheet would otherwise get wrong:

- **`apply` has no `-n`.** Its entire flag set is `-f`, `-o`, `--as`, `--home` (plus hidden
  `--to`/`--force`). Namespace comes from `metadata.namespace` or the resolution ladder below.
- **`-f` takes a file, not a directory** — on both `apply` and `delete`. Passing a directory is
  an error (`is a directory`). Apply one file per command, config before workstation; delete in
  reverse.

Objects within a single `apply` are sorted by kind priority automatically, which is why a
multi-doc file is safe but two separate files need you to order the commands.

`-y` matters only for **delete-by-name** of a `Workstation` or `Secret`: those prompt when stdin
and stderr are both terminals, so a script needs it. `delete -f` has **no confirmation path at
all**, so `-y` there is inert — harmless, but do not read its presence as proof a delete is
non-interactive.

### State and readiness

```bash
rl workstation get [name] [-n <ns>] [-A] [-o table|yaml|json|jsonpath='{...}'] [-w]
rl workstation describe <name> [-n <ns>]        # NO -o flag exists; conditions + reasons table
rl workstation wait <name> --for=<target> --timeout=25m [-n <ns>]
```

`--for` targets:

| target | meaning |
|---|---|
| `Ready` (default) | **composite** for a Workstation: `Ready=True` ∧ `Configured=True` ∧ `ToolsReady≠False` — "the box is usable" |
| `Deleted` | the object is gone — use this to confirm teardown |
| `condition=Configured` / `condition=Configured=False` | one condition |
| `Running`, `Provisioning`, `Failed`, … | a bare phase name |
| `jsonpath='{.status.phase}'=Running` | arbitrary |

Timeout exits **1**. `--timeout 0` waits forever (don't).

Machine-readable conditions come from `get`, not `describe`:

```bash
rl workstation get <name> -n <ns> -o jsonpath='{.status.conditions}'
rl workstation get <name> -n <ns> -o yaml
```

### Forwarded ports

```bash
rl binding show [-n <ns>] [-A]
```

Per binding it prints the Ready condition and each active forward with its **host** port, plus
`DROPPED … reason:` lines for conflicts. `status.bindings[].localPort` is the authoritative
laptop port — it differs from the remote port when `portOffset` or a conflict is in play.

When nothing is forwarded, the `Ready` reason tells you why:
`Disabled` · `NotConnected` (no connected box matches the selector) · `NoForwards` (connected,
but nothing to forward) · `Degraded` (some dropped) · `Pending`.

### Where can this run? (preflight)

```bash
rl status                 # human: local and remote providers, with a reason for each
rl status -o json         # ← branch on this; see SKILL.md §3, check 5
```

`local.providers[]` and `remote.providers[]` each carry `{name, state, reason?, failedChecks?}`.
`state` is one of **`available`** (run there), **`unavailable`** (a prerequisite is missing —
`reason` says which), **`not-registered`** (the host could run it, but the daemon did not
register it) or **`unknown`** (no probe, or no permission to read one). For a LOCAL provider only
`available` means you can run there. The REMOTE half is **configuration only** — no credential is
validated and no network call is made — so `available` means a `CloudAccount` names that provider,
and `unknown` usually means the user is not an org administrator rather than that the cloud is
absent.

`local.source` is `daemon` (the published host probe, readable whether or not the daemon is
running now) or `device` (probed one-shot, because no daemon has ever published here).
`remote.loggedIn` is false on a device with no control plane, and every remote provider then
carries a reason that says to log in.

The container-fixture providers are never reported; they are test scaffolding, not somewhere a
user can run.

### Diagnosis

```bash
rl troubleshoot <name> --failed --kind script [-n <ns>]   # ← which step failed and its output
rl troubleshoot <name> --report-only                      # the in-VM ledger alone
rl troubleshoot <name> --json                             # machine-readable
rl troubleshoot <name> --diagnostics[=PATH]               # sendable zip
rl logs <name> [-f] [--since 30m] [--tail N] [-n <ns>]    # the in-box agent journal
rl workstation get-resolved-configuration <name> -o yaml  # the merged config the box will apply
```

`--kind` values: `user`, `package`, `devtool`, `tool-config`, `script`, `security-update`,
`self-update`.

`get-resolved-configuration` is the fastest way to answer "will my devtool actually be
installed?" **before** waiting on a converge.

### Shell

```bash
rl shell [name] [-n <ns>] [-- <command>]
rl tmux  [name] [-n <ns>]
```

`rl ssh` does not exist — it was removed, and is an unknown-command error, not an alias.

### Auth / namespace / daemon

```bash
rl auth status [-o json]        # safe standalone; never fails on an unreachable control plane
rl namespace use                # reports the resolved namespace AND its provenance
rl daemon status | start | stop
rl sshkey get [-o yaml] [-n <ns>]
rl version
```

## Where an un-namespaced manifest lands

One ladder, highest rung first:

1. explicit `-n/--namespace`
2. the device pin (`rl namespace use <ns>`) — **do not set this**, it is device-wide state
3. the origin's `spec.defaultNamespace`, stamped at login
4. the built-in reserved `local`

So a manifest with no `metadata.namespace` lands in **`local`** when logged out, and in the
**tenant namespace** when logged in. That is why the manifests omit it.

Routing notes that matter:

- The reserved `local` namespace **always** stays on this device, even when logged in.
- A Workstation with no provider pin, or with a local provider (`qemu`, `lima`, `dockertest`,
  `wsl2`), routes to **self** even when logged in — a local box is sticky.
- A Workstation pinned to a cloud provider routes to the logged-in control plane, and **errors
  outright** when logged out: `no origin advertises provider:<p>`.
- `SSHKey` and `LocalBinding` are device-local and never reach a control plane.
