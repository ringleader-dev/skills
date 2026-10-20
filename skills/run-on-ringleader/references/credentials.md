# Credentials: the clone, and the keys the box's own tools need

Two different jobs, two different mechanisms, and confusing them wastes a converge:

| The job | What you declare | Needs an Edge? |
|---|---|---|
| **Clone a private repository** (§3 of SKILL.md) | a `Secret` + `sources[].git.credentialRef` | no, anywhere |
| **Let a tool IN the box call an API with a key** | a `Secret` + an `Integration` of `type: httpProxy` | on a cloud, yes |

Part 1 is the one a run needs. Part 2 is for the developer who will work in the box afterwards —
**never create one unasked**, and read "What it costs" before you offer it.

---

# Part 1 — the clone credential

A private repository cannot be cloned without a credential the workstation can use, and a missing
one fails six minutes later, *inside the box*, as a clone error. Resolve it at preflight.

```yaml
sources:
  - name: <app>
    path: /home/dev/src/<app>
    git:
      url: https://github.com/<owner>/<repo>.git
      ref: main
      credentialRef:
        name: <secret-name>     # a Secret in the SAME namespace as the Workstation
        key: token              # which key of its `data` map; omit for a single-key Secret
```

The control plane resolves that Secret and forwards the value to the box, which uses it for the
clone and nothing else.

## Match the URL scheme to what the Secret holds

The product picks the authentication method **from the URL**, not from the Secret:

| `url` | what the Secret must hold |
|---|---|
| `https://…` (or `http://`) | a **token** — a GitHub PAT, a GitLab token, a deploy token |
| `git@host:path`, `ssh://…`, anything else | an **SSH private key** — a deploy key |

Get this pair wrong and the clone fails in the box. A PAT on the SSH path is written to a key file
`ssh` rejects; a private key on the HTTPS path is refused outright, because a multi-line value
would inject a second header. **A PAT is the common case, so rewrite an `ssh`-form URL to its
`https://` form when the credential is a token** — and say in the report that you did, because the
URL in the manifest will no longer be the one the user typed.

Neither form puts the credential on the command line. A token rides in an `http.extraHeader`
(`Authorization: Basic`, the ordinary PAT-over-HTTPS form) set through the environment; a key is
staged in a transient `0600` file and `GIT_SSH_COMMAND` points at it. So the credential is in
neither `ps` output nor `.git/config`.

For a **public** repository use the `https://` URL and no `credentialRef` at all.

## Choosing the credential

Work down this list and stop at the first confident answer. Do not silently pick one when two are
plausible.

1. **The user named a Secret** ("the PAT is in the `gh-pat` secret") → use it verbatim. Confirm it
   is there and carries the key you will name:

   ```bash
   rl secret get <name> -n <ns> -o yaml      # spec.redactedData lists the KEY NAMES, never a value
   ```

2. **A Secret in the namespace is plainly for this** — `rl secret get -n <ns>` and read the names
   and labels. Exactly one plausible candidate → use it and say which. Two → ask.
3. **An `SSHKey` object already covers this box** — `rl sshkey get -o yaml -n <ns>`, with
   `spec.enabled` not false and a `spec.selector` that will match the label you are about to put
   on the Workstation (an absent selector matches everything). The user is already set up: rely on
   it, **create nothing**, and say which object you are relying on. It forwards their local key as
   an ssh-agent, so the source URL stays in its `git@host:path` form. Say in the report that this
   half of the manifest set is **not portable**: an SSHKey is a device-local kind, so it forwards
   only from the device that declared it and nobody else's checkout of `.ringleader/` reproduces
   it.
4. **`$GH_TOKEN` or `$GITHUB_TOKEN` is set in your environment** → the user put a token there for
   this run. Create a Secret from it, name it after the run, and **delete it at teardown**:

   ```bash
   rl secret create <app>-git-${shortHash:creatorUserId} -n <ns> --from-string token="$GH_TOKEN"
   ```

   Write `$GH_TOKEN` in the command, never the value: the variable reaches `rl` and the token
   never reaches your transcript. Say in the report that you created a Secret and which variable
   it came from.
5. **Otherwise — STOP.** This is a clean, honest failure, not a problem to improvise around.
   Report `result.reachable: false`, `result.failureClass: "credentials"`, name what you looked
   for, and give the user the two things that would fix it:

   ```bash
   rl secret create <app>-git -n <ns> --from-string token=<a GitHub PAT with `repo` read access>
   ```

   ```yaml
   # then in .ringleader/workstation-config.yaml, under the source:
   credentialRef: {name: <app>-git, key: token}
   ```

   Create nothing: no `Workstation`, no `WorkstationConfig`, no `Secret`.

## Never mint one, and never read one out of a credential store

The line is **who put the value in front of you**. An environment variable the user exported for
this run is a hand-off. A credential store is not — reading one spends a credential the user
holds for everything else, in a session they are not watching.

Off the allowlist, every one of them:

- `ssh-keygen -t …`, or any other way of creating key material on this machine.
- `gh`, `glab`, `aws`, `gcloud`, `az` — any CLI that acts on a remote service with the invoker's
  stored credentials, and above all one that **writes to the user's own account**
  (`gh api user/keys`, `gh api repos/…/keys`).
- Reading a credential store: `~/.config/gh/hosts.yml`, `~/.netrc`, `~/.git-credentials`,
  `git credential fill`, a keyring, a cloud CLI's cached token. `cat` does not make it reading a
  file; it is still spending the credential.
- `$(gh auth token)` inside an `rl secret create`. The host shell expands it **here**, before `rl`
  ever starts, so it is the same act with an extra step.
- Putting a token into a manifest, into a clone URL (`https://<token>@github.com/…`), or into a
  `scripts[].env` literal.

## Four things that will bite you

- **`rl apply` does NOT check that the Secret exists.** Verified: a config naming a Secret that is
  not there applies cleanly and exits 0. The failure arrives much later, in the box, as a clone
  error. So confirm the Secret before you apply, not after.
- **The Secret must land in the SAME namespace as the Workstation**, or it does not resolve.
  `rl apply` has no `-n`; `rl secret create` does, so pass the namespace `rl namespace use`
  reported.
- **A Secret is broadcast to every origin of its namespace**, and its values are masked wherever
  Ringleader prints them. Logged out, the namespace is `local` and it stays on the device. Logged
  in, it reaches the control plane — which is what makes a cloud box work, and is worth one line
  in the report when you created it.
- **Apply the Secret before the config**, so the first converge already has it.

## What actually reaches the box

Measured on a qemu box cloning a private repository through a `credentialRef`:

- the clone's `origin` URL holds **no token** — `.git/config` is the plain `https://…` URL;
- the login user **cannot** read the credential anywhere;
- the forwarded value lives in `/opt/ringleader/config/secrets.json`, mode `0600`, owned by
  `root` — the agent uses it for the clone and the ledger redacts it.

So the credential does not reach the checkout, the remote URL, or the developer's home directory.
It is still *on the box*, readable by root, which is the honest difference from Part 2 — there the
key never reaches the box at all. Say so if the user asks for a key that must never land on the
machine.

## Teardown

A Secret **you created** is an object you created, so §6 applies to it. Delete it by name and
verify:

```bash
rl secret delete <name> -y -n <ns>
rl secret get -A                      # your name must not appear
```

`scripts/reap.py` reaps a Secret from a manifest file like any other object. One you created
imperatively is not in a manifest, so name it:

```bash
scripts/reap.py .ringleader --also Secret/<name>
```

A Secret the **user** already had is not yours. Never delete it.

---

# Part 2 — keys the box's own tools need

This is what Ringleader's own documentation calls **credential injection**, and it is a different
thing from Part 1. You name a host and a header; when a request to that host leaves the
workstation, Ringleader adds the key from a Secret. Nothing running on the box can read it, print
it, or send it anywhere else.

It is for the developer who will work in the box — an AI coding agent calling an LLM provider, a
script calling the GitHub API, a package manager hitting a private registry.

**Do not apply one unasked.** It changes how the box reaches the network, it can restart the box,
and on a cloud it needs an object only a namespace administrator may write. Ship it commented out
in `templates/git-credential.yaml`, say in the report that it is there, and apply it only when the
user asks.

```yaml
apiVersion: workstations.ringleader.dev/v1
kind: Integration
metadata:
  name: <app>-github-api
spec:
  type: httpProxy
  selector:
    ownerScope: true                 # your own workstations only
    matchLabels:
      app: <app>
  httpProxy:
    rules:
      - host: api.github.com
        inject:
          header: Authorization
          value: "Bearer ${secret:<app>-git/token}"
```

The `${secret:<name>/<key>}` body is the same grammar `credentialRef: {name, key}` compiles to, so
**one Secret can serve both halves**: the clone and the API call. The header differs because the
services do — `Authorization: Basic` for git over HTTPS, `Bearer` for the GitHub REST API — and
the rule is where you say which.

**Proof-read the selector.** It is an opaque subtree, so a typo in `matchLabels` does not fail;
it silently changes what the Integration reaches, and an absent or empty selector matches **every**
workstation in the namespace. The same was true of an `SSHKey`'s selector, and it is the one
mistake here that produces no error anywhere.

## Where the key is added, and what you must declare

| Provider | Where the key is added | What you declare |
|---|---|---|
| `qemu` (Linux), `vz` (Mac), `hcs` (Windows) | the workstation's own network process, on this machine | the Integration only |
| `lima` (Mac fallback) | the Ringleader daemon, on this machine | the Integration only |
| `gcp`, `aws`, `azure` | an **edge instance** — a VM in the user's cloud account | the Integration **and** an `Edge` |
| `wsl2` | nowhere; it is not supported | use a cloud workstation |

**On a cloud, an `Edge` is required and a namespace administrator declares it.** It is one VM per
provider and region, shared by every workstation in that namespace and region, and no field on a
workstation or an Integration names it — it is matched by provider and region:

```yaml
apiVersion: core.ringleader.dev/v1
kind: Edge
metadata:
  name: gcp-us-east4
spec:
  provider: gcp
  region: us-east4        # aws and azure also need `subnet:`, the one cloud onboarding reserved
```

The VM is built when the first workstation that needs it reports in; until then `rl edge get`
shows `Ready=False` with reason `NoMachine`. With no Edge at all, a cloud workstation reports
`EgressEnforced=False` with reason `NoEdge` and simply goes without the key.

In a personal namespace the user is the administrator and can declare it themselves. In a shared
one they cannot, and asking them to is the right answer — **never substitute a local box for a
cloud one to get around it** (`clouds.md`).

## What it costs

- **A qemu workstation restarts once** when an Integration first injects into it, and once more
  when the last one stops, because its network cards change. Mid-converge that is a lost build.
- **Only the hosts you name are decrypted**, and each box gets its own CA. Ringleader installs it
  and sets `SSL_CERT_FILE`, `CURL_CA_BUNDLE`, `REQUESTS_CA_BUNDLE`, `GIT_SSL_CAINFO`,
  `CARGO_HTTP_CAINFO` and `NODE_EXTRA_CA_CERTS`, so `curl`, `git`, `requests`, Node and Go accept
  it with no setup. A tool with its own pinned trust store will refuse the connection; leave that
  host out of the rules.
- **A named host is served over HTTP/1.1**, so an HTTP/2-only client cannot reach it.
- **On a local box the key is held on this machine**, so whoever uses the machine could read it. A
  rule's `allowDaemonPlacement` gates that: unset means only the author's own workstations.
- A cloud box behind an edge instance stops answering at its own public address; `rl shell` goes
  through the edge instead.

## Checking it

```bash
rl workstation describe <name> -n <ns>     # EgressEnforced: True, reason CredentialOnly
```

`CredentialOnly` is the healthy answer for a box with a key and no egress policy.
`GatewayNotServing` means the network process is not up yet; `NoEdge` means a cloud box has no
Edge. On lima the condition is `EgressCredential` instead, `CredentialHeld` when the key is being
added.
