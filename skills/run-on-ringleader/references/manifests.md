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

## The distribution: Ubuntu 26.04 by default, three values portable

```yaml
image: {os: linux, distribution: ubuntu, version: "26.04"}
```

Ubuntu is the default because it is what a developer expects a Linux box to be and what
third-party install instructions are written against. Write something else **only when the user
asks for it** — a repository's own preference is a fact for the report, never an instruction.

| `distribution` | `version` | qemu (Linux host) | lima (macOS host) |
|---|---|---|---|
| `ubuntu` | `26.04` | ✅ **default** | ✅ |
| `debian` | `13` | ✅ | ✅ |
| `debian` | `12` | ✅ | ✅ |
| `ubuntu` | `24.04` | ❌ **loud failure** | ✅ |
| `alpine` | any | ⚠️ silently becomes debian 13 | ⚠️ same |

So the **portable set is exactly `ubuntu` 26.04 and `debian` 12/13** — write anything else and the
manifest stops working for half its audience. Two asymmetries worth holding:

- An unsupported version of a **known** distribution **fails provisioning loudly** and never falls
  back — deliberate, so a box can never lie about its OS. `ubuntu: "24.04"` is the trap: it is
  perfectly good on a colleague's Mac and dead on Linux.
- An **unknown distribution** (`alpine`, a typo) does the opposite: it silently falls back to
  debian 13. A box that came up "fine" on the wrong OS is the harder bug, so spell the
  distribution from the table and confirm what booted:

  ```bash
  rl shell <name> -- 'cat /etc/os-release'
  ```

Both families are debian-family, so `packages:` names, apt repositories and the whole devtool
catalog behave identically across the portable set. Changing distribution does **not** change any
other field of the manifest — and note `image` is the one field `DiffSpec` compares, so editing it
**recreates the box** (wiping the overlay disk), unlike the sizing fields below.

## The devtool catalog is CLOSED and short

An unknown `devtools[].name` **fails the box** — it is reported, not ignored. The complete set:

`docker` · `nodejs` · `go` · `golangci-lint` · `git` · `vscode-web` · `claude-code` · `codex` ·
`playwright` · `kind` · `kubectl` · `helm` · `kubectx` · `kubens` · `fzf` · `gcloud` · `aws` ·
`az` · `gh` · `passthrough-www-browser` · `python` · `spire-agent`

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

Ordering matters: declare `nodejs` **before** `claude-code` / `codex` / `playwright`, or they
pull the distro Node. Declare `docker` before `kind`.

`config` is only read by `kind` and `playwright`. Everywhere else it is inert.

## WorkstationConfig — the fields that matter here

```yaml
apiVersion: workstations.ringleader.dev/v1
kind: WorkstationConfig
metadata:
  name: <app>
spec:
  image: {os: linux, distribution: ubuntu, version: "26.04"}   # the default — see below
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

(For contrast: `dockertest` *does* diff `cpus`/`memory`, and cloud providers resize for real. This
rule is specific to the local VM providers, which is exactly what you are using.)

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
  `providerConfig: {gcp: {machineType: …}}`, which is a cloud pin — see "Cloud providers, when the
  user asks for one" below, and note that sizing is only ever what the user named.

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

**Only when the user names one.** Unasked, write no provider and no requirements and let
capability discovery pick the local one — that is what keeps the manifest portable, and it is
still the default. `rl status -o json` says whether a `CloudAccount` for that provider is
readable from this device (SKILL.md §3, check 5) — **configuration only: it validates no
credential and makes no network call.** `unavailable` is a definite no and a stop; `unknown` for
a cloud usually means the user is not an org administrator rather than that the cloud is missing.
Never fall back to local when a cloud was named.

The change is additive and lives on the **Workstation** only, so the config stays untouched. It is
the pin **plus the fields that cloud requires**, and no more:

```yaml
spec:
  requirements: [provider:gcp]
  providerConfig:
    gcp: {project: <the user's project>, zone: <the user's zone>}
```

**Each cloud has REQUIRED fields, and a box whose RESOLVED config lacks them never starts:**

| cloud | required in `providerConfig.<cloud>` |
|---|---|
| `gcp` | `project`, `zone` |
| `aws` | `region` |
| `azure` | `subscriptionId`, `resourceGroup`, `location`, **and** `networkInterfaceId` **or** `subnetId` |

**You cannot invent any of them** — a project id, a subscription, a resource group and a region are
facts about the user's account that no amount of reading the repository will tell you. **But do not
refuse up front either**: an organisation's `CloudIdentity` can supply them through the
provider-config fold, so a run that stops because the user did not recite them denies work that
would have succeeded. Write what the user gave, apply, and let the box tell you.

**`rl apply` exits 0 whether or not a required field is there.** What changes is the workstation —
and WHICH status it takes depends on who refused. A field the factory needs lands
`ProviderUnavailable` whose `status.message` names it: read that status, report it verbatim, and ask
for the field it names. Azure's network field is refused later, by the VM create, and lands
`CreateFailed` with the field name redacted away — see below.

**Three keys are not the user's to give.** `serviceAccount`, `managedIdentity` and
`iamInstanceProfile` are stripped from a member's config unconditionally and re-injected from the
admin-owned `CloudIdentity`. If the status names one of them, asking the user to set it loops
forever — say that an org administrator has to attach it instead.

**Azure's network field fails LATE and OPAQUELY.** The factory accepts a config without it and the
VM create then fails at `ensureNIC` — and that error is not user-facing, so what reaches the user is
`internal error (ref: <id>)` and nothing else. If an azure box fails with that and its config has
neither `networkInterfaceId` nor `subnetId`, that is almost certainly why: say so, and ask which
subnet. Do not expect the field's name to appear anywhere in the message; it is redacted.

**That table is what the factory or the VM create refuses to proceed without; it is not the whole
matrix.**
Some fields are required only in certain shapes — a GCE **pull** box needs
`providerConfig.gcp.serviceAccount` unless the project's default compute service account exists,
for instance, and that one is admin-owned rather than the user's to set (above). So treat any
status naming a `providerConfig.<cloud>.<field>` the same way: report it verbatim, and ask whoever
owns that field — the user for an account fact, an org administrator for an identity key. Never
guess one, and never work around it by switching to a local provider.

**Everything else in that block stays out unless the user named it** — but for two different
reasons, and the second one bites differently. `machineType`, `diskGiB` and their siblings are
BILLING decisions: write what the user asked for and nothing more, and say in the run report which
fields came from them. On `aws`, `subnetId` and `securityGroupIds` are REACHABILITY: left empty,
EC2 places the box in the default VPC with the default security group, which permits no inbound
SSH — so the box boots, bills, and the device cannot dial it. (Whether that bites depends on the
account's own VPC defaults, so treat it as the first thing to ask about when an aws box is up but
unreachable, not as a field to invent.)

A cloud-pinned Workstation routes to the logged-in control plane and **errors when logged
out**, which is exactly why it is not in the portable default — and why `rl status` is worth
reading first: `remote.loggedIn` is false on a device with no control plane, and every remote
provider then carries a `reason` that already says to log in.

**No eval run has ever exercised this path.** Of the 126 stored runs, none pins a cloud:

```bash
grep -l 'provider:gcp\|provider:aws\|provider:azure' eval/results/*.json | wc -l   # -> 0
```

The routing above is what the product documents; treat a cloud run as unproven, and report what
actually happened rather than assuming it behaved like the local case.
