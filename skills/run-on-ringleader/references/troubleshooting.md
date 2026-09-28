# Symptom → cause → command

Diagnose before you edit. Every entry below names the command that produces the *evidence*, not
a guess.

## The one thing to internalise

**Status carries a token; the box's ledger carries the truth.** A failed configuration step
shows up as `Configured=False` with reason `ConfigurationFailed` and a generic message. The
failing step's **name, exit code, stdout and stderr live only in the on-box ledger**, reachable
through:

```bash
rl troubleshoot <name> --failed --kind script -n <ns>
```

Never conclude "the script failed for some reason" from status alone — the reason exists, you
just have not asked for it.

## Workstation never reaches Ready

| Reason on `Configured` | Meaning | Next |
|---|---|---|
| `Configuring` | still applying — not a failure | wait; check `rl logs <name>` for progress |
| `ConfigurationFailed` | a step keeps failing | `rl troubleshoot <name> --failed` |
| `ConfigurationStalled` | box is Running but the agent never reported | the agent bootstrap failed — `rl logs <name>`; often agent delivery |
| `ConfigurationNotDelivered` | the control plane cannot deliver config at all | outranks a step failure; check connectivity/transport |
| `UserConfigFailed` | the login user / groups / sudo never converged | checked first; usually a bad `identity:` block |

Check them with:

```bash
rl workstation describe <name> -n <ns>
rl workstation get <name> -n <ns> -o jsonpath='{.status.conditions}'
```

`status.config.effectiveHash != status.config.appliedHash` is the machine-readable "not
converged yet".

## Box reaches Running but never Configured

Almost always **agent delivery**: the box downloads the agent tarball over HTTP, and if that
version is not published it 404s, never runs the in-VM loop, and sits at `Configured: False`
forever with no step failure to find.

```bash
rl logs <name> -n <ns>          # look for the curl/install of ringleader-agent
rl version                      # prints the exact agent tarball URL the daemon will hand out
curl -I <that url>              # 404 ⇒ this is your problem
```

This is an environment problem, not a manifest problem — no manifest edit fixes it.

## The box died mid-build, or my sizing edit did nothing

Two distinct symptoms, one cause.

**"machine no longer running, reprovisioning"** in the events means the VM ran out of memory and
died — it is not a step failure, and the ledger will show your script as still `running` when the
machine vanished. `rl troubleshoot <name>` and `rl logs <name>` are how you confirm it; the
tell is `systemd-journald: Under memory pressure, flushing caches` shortly before the end.
(A local provider also keeps a serial log under the daemon's own state directory, but finding it
means knowing which provider you got and where it stores things — an assumption G3 forbids, and
one `rl troubleshoot` saves you from making.)

**A `providerConfig.memory` edit that changes nothing** is the same story from the other side. On
qemu and lima, `DiffSpec` compares only the base image, so a sizing edit is an **empty diff** —
no drift, no resize, no error, and a stop/start relaunches from the persisted `machine.json`.

The only fix is **delete and recreate the workstation** (destructive: the overlay disk goes with
it). Check what the machine actually got by asking the guest, not this machine:

```bash
rl shell <name> -- 'free -g; nproc; df -h /'
```

If it still reports ~1 GiB / 2 cpus after you asked for more, either the recreate has not
happened yet or your key is misspelled — `providerConfig` is free-form and unvalidated, so
`memoryGiB:` or `mem:` silently yields the defaults.

## `no space left on device` partway through a build

The disk you asked for was too small. `providerConfig.disk` **is** honoured (the 8 GiB default is
a floor, not a fixed size), so this is a sizing mistake rather than a wall — but it is a
**create-time** one, so re-applying a bigger number does nothing at all.

Confirm the shortfall is inside the box before acting, because a full `~/.ringleader` on the host
produces the same string and recreating bigger makes that worse:

```bash
rl shell <name> -- 'df -h /'          # the box
df -h ~/.ringleader                   # the host
```

Then recreate **once** at a larger size — at least double what you asked for — and say so in the
report. A second `ENOSPC` after that is a real `capacity` finding, not another retry. The recreate
wipes the overlay: the generated `.env`, the checkout and any in-box edits go with it.

## `internal error (ref: …)` and nothing else

The message the operator sees is a reference, not a reason: the real one is in the daemon log.
Booting `ubuntu` 24.04 on qemu produces exactly this, and the cause is only visible there:

```bash
grep '<the ref>' ~/.ringleader/daemon.log
# → qemu: unsupported image: distribution "ubuntu" version "24.04"
#         (supported: debian-12, debian-13, ubuntu-26.04)
```

So an opaque `CreateFailed` is **not** evidence of an environment problem. Check the log before
classifying it as one — an unsupported `image:` you wrote yourself is a manifest bug, and the
portable set is `ubuntu` 26.04, `debian` 12 and `debian` 13.

**On a cloud-pinned box, check the manifest before the log.** The same opaque `CreateFailed` is
what a missing azure network field produces: `ensureNIC` fails with an error that is not
user-facing, so the field name never reaches the status. If the box pins `provider:azure` and its
`providerConfig.azure` carries neither `networkInterfaceId` nor `subnetId`, that is almost
certainly the cause — say so and ask which subnet, rather than hunting the ref. The other required
fields fail earlier and more helpfully, as `ProviderUnavailable` naming the field;
`references/manifests.md` has each cloud's set.

## After a stop/start the box says Ready and nothing answers

**Verified empirically, not theory.** Stop and start a box whose app was serving, and you get:

| Signal | Says |
|---|---|
| `rl workstation get` | `Ready` |
| `rl workstation wait --for=Ready` | exit 0 |
| `rl binding show` | `Ready=True`, the forward listed |
| `curl` the forwarded port | **connection refused** |
| `docker compose ps` in the box | **no containers** |

Every green signal is honest about what it measures and useless here. `binding show` in particular
does **not** report `NoForwards`, because a declared `ports:` entry seeds the forward whether or
not anything listens.

The mechanism, from the box's own ledger:

```
script  run-app  skipped  already run (runPolicy=onChange, watched inputs unchanged)
```

`stop` is a hard kill; `start` boots the same disk. dockerd comes back active, the containers are
all `exited` (no `restart:` policy), `.env` and the checkout survive — and the one step that would
restart the app is skipped, because its marker lives on that surviving disk and has not changed.
The controller then re-derives `Configured=True` precisely *because* every step was skipped.

**Fix:** a `runPolicy: always` liveness step (`docker compose up -d`, no `--build`). Verified: with
it, a stop/start self-heals in about 20 seconds with no intervention.

## I edited a file in the box and nothing rebuilt

Working as designed, and worth telling the developer up front. **There is no periodic converge**
— a box was measured sitting 19 minutes after an in-box edit with its reconcile id unchanged. The
in-VM run loop is driven by configuration reaching the box, not by the box watching its own
files, so editing source in the box never triggers anything on its own.

Three ways forward, in the order a developer will want them:

1. **Rebuild in the box** — `docker compose up -d --build`, `npm run build`, whatever the run
   command is. Immediate, and what they would do in a terminal anyway.
2. **Force a converge from the laptop** by applying a config change. An identical re-apply pushes
   nothing, so it must be an actual change.
3. **Restart the box** — that converges, and the `runPolicy: always` liveness step runs.

`watchPaths` does not change any of this. What it does is make case 2 and 3 *correct*: without
it, a `runPolicy: onChange` build step degrades to content-hash `once` and is skipped even when a
converge runs, so the moved source is never rebuilt. Verified both halves — a forced converge
re-ran a build step whose own content was unchanged, purely because the watched tree had moved.

## A script did not re-run after I edited it

`runPolicy: once` is gated on the script's **content hash**. If the body is byte-identical it is
skipped, and the ledger says so:

> `already run (runPolicy=once)` / `already run (runPolicy=onChange, watched inputs unchanged)`

Change the body, or use `runPolicy: always` while iterating.

## A devtool is missing

Check what the box was actually told to install, before waiting on another converge:

```bash
rl workstation get-resolved-configuration <name> -n <ns> -o yaml
```

If the devtool is absent from the resolved config, the config did not attach — check the label
selector on both objects. If it is present but not installed, `rl troubleshoot <name> --failed
--kind devtool`.

An unknown devtool name is an error, not a silent skip. The catalog is in `manifests.md`.

## Nothing is forwarded to the laptop

**First, find out whether a binding exists at all** — that is a different failure from a binding
that exists and is not forwarding, and only one of the two has a `Ready` reason to read:

```bash
rl binding get -A          # is there a binding for this box?
rl binding show -n <ns>    # if yes, why is it not forwarding?
```

**No binding at all** means the seed never happened. The daemon seeds the generated LocalBinding
**once per workstation UID**, recorded in a ledger — and if the `defaultLocalBinding` template was
malformed, the UID is recorded anyway. That box will never get a binding, and **editing
`defaultLocalBinding` and re-applying is a silent no-op**: the seed is create-time. The remedies
are to write the binding by hand (`rl binding …`) or to delete and recreate the box.

**A binding exists but forwards nothing** — read the `Ready` reason:

| Reason | Meaning |
|---|---|
| `NotConnected` | no *connected* workstation matches the binding's selector — the box is not up, or the labels do not match |
| `NoForwards` | connected, but nothing to forward: no listeners, no static ports, `forwardAll` off |
| `Disabled` | `spec.enabled: false` |
| `Degraded` | some forwards dropped — read `status.dropped[].reason` (usually a host port conflict) |

Also useful:

```bash
rl troubleshoot <name> -n <ns>     # has a "device-local port forwarding" section
```

It is the one that diagnoses *absence* — including "NO LocalBinding on this device targets this
workstation", and whether the seed ledger already holds the box (seeded + no binding ⇒ it will
never be recreated automatically).

## The port is forwarded but curl fails

Distinguish three cases before editing anything:

1. **Nothing listening in the box.** `rl shell <name> -- ss -ltnp` (or `netstat -ltnp`).
   The app crashed after starting — `rl shell <name> -- docker compose logs --tail 50`.
2. **Listening on the wrong interface.** A process bound to `127.0.0.1` inside the box is still
   forwardable; one bound to a container-internal address is not. For compose, check the
   published host-side mapping.
3. **Listening, forwarded, but erroring.** A 502/500 is the app's own problem — read its logs.
   Report it honestly; it is a real result.

## The dev server starts, prints its URL, then dies — `spawn xdg-open ENOENT`

A workstation is **headless**, and a lot of dev servers try to open a browser on startup. Vite,
Create React App and several `npm start` wrappers shell out to `xdg-open`, which is not installed,
and Node turns the failed spawn into an **unhandled `error` event** that kills the process:

```
VITE v5.0.12  ready in 809 ms
  ➜  Local:   http://localhost:3000/
Error: spawn xdg-open ENOENT
  ... code: 'ENOENT', syscall: 'spawn xdg-open', spawnargs: [ 'http://localhost:3000/' ]
```

The tell is that it is **not** a build failure and not a port problem: the server genuinely came up
and announced itself a moment before dying, so the log looks like success right up to the crash.
Anything watching for "did it bind the port" sees it bind and then vanish.

Fix it in the manifest, at the start command — do not install a browser:

- `BROWSER=none` in the step's `env:` — honoured by CRA, Vite and most `open`-based launchers;
- or the flag the tool provides: `vite --open false`, `next dev` (which does not open by default),
  `ng serve --open=false`;
- or `server: {open: false}` in `vite.config.ts`, if a config edit is cheaper than a flag.

`BROWSER=none` is the first thing to reach for: it is one line, needs no knowledge of which
launcher the repo uses, and is inert where it is not needed. Note that `env:` folds into the
script's content hash, so adding it re-runs the step.

## Host port conflict on the laptop

`status.dropped[].reason` names it. Another process (or another workstation) already holds the
port. Options: stop the other holder, or give the binding a `portOffset` / an explicit
`localPort`. Do not silently pick a different port and report success on it — say which port
the app is really on.

## Delete hangs in Terminating

The VM is being destroyed. Wait for it properly:

```bash
rl workstation wait <name> --for=Deleted --timeout=10m -n <ns>
```

If it does not clear, report it with the object name and the command to retry. Do not move on
quietly — a stuck Terminating workstation is exactly the leak this skill must not produce.
