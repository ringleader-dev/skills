# Writing the `.ringleader/` manifests

Three files, all portable — **no `metadata.namespace`, no provider, no `providerConfig`** — unless
the user names a cloud, which is the one exception and is spelled out under "Cloud providers, when
the user asks for one" below:

```
.ringleader/
  workstation-config.yaml     # everything: image, tools, source, ports, scripts
  workstation.yaml            # a name and a label
  sshkey.yaml                 # private repos only
  .run-report.json            # written at the end
```

They join by **label selector**: the Workstation carries `labels.app: <app>`, the config
selects `matchLabels: {app: <app>}`. Do not use an explicit `configs[]` list.

## The distribution: Ubuntu 26.04 by default, two values portable

```yaml
image: {distribution: ubuntu, version: "26.04"}
```

Ubuntu is the default because it is what a developer expects a Linux box to be and what
third-party install instructions are written against. Write something else **only when the user
asks for it** — a repository's own preference is a fact for the report, never an instruction.

| `distribution` | `version` | qemu (Linux) | lima (macOS) | WSL2 (Windows) |
|---|---|---|---|---|
| `ubuntu` | `26.04` | ✅ **default** | ✅ | ✅ |
| `debian` | `13` | ✅ | ✅ | ✅ |
| `debian` | `12` | ✅ | ✅ | ❌ falls back to debian 13 |
| `ubuntu` | `24.04` | ❌ **loud failure** | ✅ | ❌ falls back to debian 13 |
| `alpine`, a typo | any | ⚠️ silently becomes debian 13 | ⚠️ same | ⚠️ same |

So the **portable set is exactly `ubuntu` 26.04 and `debian` 13**. Write anything else and the
manifest stops working for part of its audience. The asymmetries worth holding:

- An unsupported version of a **known** distribution **fails loudly on qemu and lima**, and the
  message names the supported pairs. `ubuntu: "24.04"` is the trap: it is perfectly good on a
  colleague's Mac and dead on Linux.
- An **unknown distribution** (`alpine`, a typo), and anything WSL2 does not carry, does the
  opposite: it silently boots debian 13. A box that came up "fine" on the wrong OS is the harder
  bug, so spell the distribution from the table and confirm what booted:

  ```bash
  rl shell <name> -- 'cat /etc/os-release'
  ```

- **Leave `image.os` out.** WSL2 reads `os` in place of `distribution` when both are set, so
  `os: linux` makes it look up `linux-26.04`, find nothing, and boot debian 13. qemu and lima read
  only `distribution` and `version`, so leaving `os` out costs nothing anywhere.

Both families are debian-family, so `packages:` names, apt repositories and the whole devtool
catalog behave identically across the portable set. Changing distribution does **not** change any
other field of the manifest — and note `image` is the one field `DiffSpec` compares, so editing it
**recreates the box** (wiping the overlay disk), unlike the sizing fields below.

## The devtool catalog is CLOSED and short

An unknown `devtools[].name` **fails the box** — it is reported, not ignored. The complete set:

`docker` · `nodejs` · `go` · `golangci-lint` · `git` · `vscode-web` · `claude-code` · `codex` ·
`cursor-agent` · `agy` · `devcontainer-cli` · `playwright` · `kind` · `kubectl` · `helm` ·
`kubectx` · `kubens` · `fzf` · `gcloud` · `aws` · `az` · `gh` · `passthrough-www-browser` ·
`python` · `spire-agent`

**There is no `rust`, `java`, `uv`, `poetry`, `maven` or `cargo` devtool.** Those runtimes go
through `packages:` or a `scripts:` step. **`python` IS one** — it installs the distribution's
python3, pip and venv, and it takes no `version:`; for a specific interpreter version use
`packages:` or a script.

### Runtime → manifest mapping

| Detected | What to write |
|---|---|
| Node / npm / pnpm / vite / next | `- {name: nodejs, version: "24"}` — the leading integer is the NodeSource **major**; omit `version` for the distro package |
| Go | `- {name: go, version: "1.24.0"}` — **exact** upstream release, not `1.24` or `latest` |
| Python / uv / Django / FastAPI | `devtools: [{name: python}]` for python3 + pip + venv; `packages:` or a script for anything version-specific |
| Rust | no devtool → `packages: [rustc, cargo]` or a rustup script |
| Java / Maven | no devtool → `packages: [openjdk-21-jdk, maven]` |
| Dockerfile or compose present | `- {name: docker}` **and** `identity.groups: [docker]` |
| Kubernetes / Helm | `docker`, then `- {name: kind, config: {...}}`, `kubectl`, `helm` — docker must come first |
| Playwright tests | `- {name: playwright, config: {browsers: [chromium]}}` — adds minutes to the first converge |
| `.devcontainer/devcontainer.json` | `- {name: devcontainer-cli}` installs the `devcontainer` CLI, after `nodejs` and `docker`; building and starting the container is a `scripts:` step |

Ordering matters: declare `nodejs` **before** `claude-code` / `codex` / `playwright` /
`devcontainer-cli`, or they pull the distro Node. Declare `docker` before `kind`. `claude-code`,
`codex`, `cursor-agent` and `agy` install coding-agent CLIs; they are for a developer working in
the box, and nothing an app needs to run.

`config` is only read by `kind` and `playwright`. Everywhere else it is inert.

## WorkstationConfig — the fields that matter here

```yaml
apiVersion: workstations.ringleader.dev/v1
kind: WorkstationConfig
metadata:
  name: <app>
spec:
  image: {distribution: ubuntu, version: "26.04"}   # the default — see below
  selector: {matchLabels: {app: <app>}}
  priority: 100

  identity:                      # pin the user so every path below is deterministic
    user: dev
    shell: /bin/bash
    groups: [docker]             # only when the docker devtool is declared
    sudo: true

  packages: [git, curl]          # system packages; strings or {name, version, type: system|npm}
  devtools: [...]                # see the catalog above

  sources:
    - name: <app>
      git:
        url: <clone url>
        ref: <branch|tag|sha>    # empty = the remote's default branch
      path: /home/dev/src/<app>  # a source with an empty path is SKIPPED ENTIRELY
      updatePolicy: pinned       # pinned (default, clone once) | latest (re-pull each reconcile)

  ports: [3000]                  # a HINT that seeds a stable forward before the app listens
  defaultLocalBinding:
    enabled: true
    autoForward: {forwardAll: true}

  scripts:
    - name: run-app
      phase: user                # anything other than "user" runs as ROOT
      runPolicy: onChange        # once (default) | onChange | always
      timeoutSeconds: 1800       # 0 = no limit; a compose build is multi-minute
      content: |
        set -e
        ...
```

### Script rules that bite

- `phase: user` (or `runAsDefaultUser: true`) runs as the login user in their home. Anything
  else — including omitting it — runs as **root**.
- `runPolicy: once` (the default) is gated on the script's **content hash**. Editing the body
  re-runs it; re-applying an unchanged body does not. `always` never skips.
- **`onChange` with no `watchPaths` is exactly `once`.** The re-run marker only folds in a watched
  digest when `watchPaths` is non-empty; otherwise it is the content hash alone. So a `run-app`
  step declared `onChange` and nothing else is skipped forever, and **a code edit never rebuilds**.
  If the step should re-fire when the source moves, it must say so:

  ```yaml
  runPolicy: onChange
  watchPaths: [/home/dev/src/<app>]
  ```
- **Two independent failure axes**: `fatal` (default `true`) decides whether the failure blocks
  `Configured`; `failOnError` (default `false`) decides whether it aborts the rest of the apply.
  Keep the app-start script `fatal` so `--for=Ready` means something.
- `env:` is folded into the content hash, so changing it re-runs the script.
- **`scripts` and `files` have no element sub-schema.** A typo in `devtools[].nmae` is rejected
  at apply; a typo in `scripts[].run` is silently accepted and does nothing. Proof-read them.

### Other gotchas

- `files[].mode` is an **octal string** — `"0644"`. Unquoted `0644` is a YAML number and is
  refused.
- A `WorkstationConfig` may **not** carry `providerConfig`, `ttl` or `ttlAction` — they are
  tombstoned and rejected at apply.
- Top-level unknown keys are rejected. The schema is closed except where noted.

## Workstation — deliberately trivial

```yaml
apiVersion: workstations.ringleader.dev/v1
kind: Workstation
metadata:
  name: <app>
  labels:
    app: <app>
spec:
  # Only when the run plan involves a real build — see the sizing rule below.
  providerConfig:
    memory: 8   # GiB
    cpus: 4
    disk: 40    # GiB — the 8 GiB default is a FLOOR and is too small for most builds
```

No provider and no requirements — unless the user named a cloud (SKILL.md §3 check 5), the one case
that pins one. Unasked, capability discovery picks the local provider, and the same file
works against a control plane.

### Sizing: the default box is 1 GiB / 2 vCPU

That is enough to install packages and clone a repo. It is **not** enough for `npm ci`, a
bundler, a compiler, or a multi-stage Docker build. Measured on a default qemu box:
`memoryMiB: 1024, cpus: 2`.

A VM that exhausts memory does not report a failed step — **it dies**, and the controller
reprovisions it from scratch:

```
Normal  Pending       machine no longer running, reprovisioning
Normal  Provisioning  adopting existing qemu machine
```

You lose the entire converge and learn nothing about your app. The tell in the box's serial log
is `systemd-journald: Under memory pressure, flushing caches` shortly before the box vanishes.

### Sizing is decided at CREATE and can never be changed by re-applying

This is the part that makes it a *plan* decision rather than a *fix* decision. On qemu and lima:

- `DiffSpec` compares only the **base image**. It never compares memory or cpus, so a sizing edit
  produces an **empty diff** — the controller sees no drift, and there is not even a failed or
  queued resize to observe. The reconcile is silent.
- A **stop/start does not help**: `Start` takes no spec and relaunches from the persisted
  `machine.json`.
- The only path that re-derives sizing from the spec is a fresh `Create`. **Delete and recreate
  the workstation** — and note this is destructive: the qcow2 overlay goes with the machine
  directory, so on-box state is lost.

So an undersized first attempt costs you a full delete + recreate plus a fresh converge. Decide
sizing from the run plan, before the first apply. 8 GiB / 4 vCPU is a reasonable default for a
Node or Go build; go higher for a monorepo.

(Cloud providers resize for real. This rule is specific to the local VM providers, which is exactly
what you are using.)

### Three more constraints on `providerConfig`

- **The accepted keys differ by provider:**

  | Provider | Accepted `providerConfig` keys |
  |---|---|
  | qemu (Linux) | `image`, `command`, `memory`, `cpus`, `disk` |
  | lima (macOS) | `cpus`, `memory`, `disk` |

  `disk` is in GiB and works on **both**. On qemu the 8 GiB default is a **floor**, not a fixed
  size: a larger request is honoured and the guest grows its root filesystem into it, and a
  request BELOW 8 is clamped back up to 8 — which is what makes it a floor rather than a default.

  **Size the disk from the run plan, exactly like memory.** Measured on qemu, `rl 0.12.0`:

  | Request | Device | Usable | Free (git only) | Free after git+docker+nodejs |
  |---|---|---|---|---|
  | (default) | 8 GiB | 6.7 GiB | 4.5 GiB | **3.8 GiB** |
  | `disk: 4` | 8 GiB | 6.7 GiB | 4.5 GiB | **3.8 GiB** — clamped to the floor |
  | `disk: 40` | 40 GiB | 38 GiB | 36 GiB | **36 GiB** |

  The default is the wrong size for most real stacks — a Postgres + Redis + app-image compose
  graph, a monorepo's `node_modules`, or any source build of a large project will exhaust it, and
  the failure is `no space left on device` partway through a build rather than anything graceful.
  40 GiB is a sensible starting point for anything with a real build, 60+ for a monorepo. Asking
  high costs nothing: a qcow2 overlay is sparse, so the host allocates only what is written.

  Like `memory` and `cpus` it is **fixed at create**, so it cannot be raised by re-applying. When
  the estimate turns out short, the recovery is a **one-time** delete-and-recreate at a larger
  size — bounded deliberately, and described in SKILL.md §5 ("The one bounded exception").

- **`memory` is in GiB, not MiB** — `memory: 8` becomes qemu `-m 8192`. `cpus` is a count.
- **It is unvalidated free-form, so anything else you write is SILENTLY DISCARDED.** `memoryGiB:`,
  `memoryGiB:`, `mem:`, `diskGiB:` — all accepted at apply, all ignored, no error anywhere. **Do not trust that
  what you wrote took effect: check it.**

  ```bash
  rl shell <name> -- 'free -g; nproc; df -h /'          # what the guest actually has
  ```

  Verify this on the first converge, not after a build dies. **Ask the guest, not the host** —
  reading the provider's own machine file on this machine would mean knowing which provider you
  got and where it keeps its state, which is exactly the assumption G3 forbids. It is also the
  weaker question: what the VM was *launched* with is not what the guest *has*.
- **It is read from the Workstation spec only.** `providerConfig` is tombstoned on
  `WorkstationConfig` and rejected at apply — sizing cannot live in the config layer.
- The flat `memory` / `cpus` keys are the **local** shape. A cloud provider takes a nested
  `providerConfig: {gcp: {machineType: …}}`, which is a cloud pin — see `clouds.md`, and note that
  sizing is only ever what the user named.

## SSHKey — private repos only

```yaml
apiVersion: workstations.ringleader.dev/v1
kind: SSHKey
metadata:
  name: <app>-git
spec:
  path: ~/.ssh/id_ed25519          # the key on THIS laptop; there is no inline-key field
  selector:
    matchLabels:
      app: <app>
```

- Device-local: it never reaches a control plane, and the private key stays in the daemon's
  in-process keyring — it is forwarded as an ssh-agent, never written to the box.
- **It must share a namespace with the Workstation.** A key in `local` does not reach a box in
  `acme`, silently.
- An absent or empty `selector` matches **every** workstation in the namespace.
- `spec.selector` is an opaque subtree — a typo in `matchLabels` silently means "match
  everything". Proof-read it.
- github.com's host key is trusted automatically for a `git@github.com:` source. A self-hosted
  host needs `sources[].sshKnownHosts`.

## Secrets an app needs to boot

Many stacks refuse to start without values the docs say to *generate*. Do it on the box, in the
start script, idempotently — never bake a secret into a manifest:

```yaml
- name: seed-env
  phase: user
  runPolicy: once
  content: |
    set -e
    cd ~/src/<app>
    [ -f .env ] || {
      echo "REDIS_TOKEN=$(openssl rand -hex 32)"      >> .env
      echo "REDIS_PASSWORD=$(openssl rand -hex 32)"   >> .env
    }
```

For a secret the *user* must supply (an API key), use a `Secret` object and a `${secret:NAME}`
reference — do not paste it into the manifest.

## Cloud providers, when the user asks for one

**Only when the user names one.** Unasked, write no provider and no requirements and let capability
discovery pick the local one; that is what keeps the manifest portable. When the user does name a
cloud, `clouds.md` has the whole procedure: when to pin and when to stop, which `providerConfig`
fields you may write, and how a missing one shows up. The pin lives on the **Workstation** only,
so the config stays untouched:

```yaml
spec:
  requirements: [provider:gcp]
  providerConfig:
    gcp: {project: <the user's project>}   # only what the user gave you
```
