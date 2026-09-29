# Making the box a workspace, and surviving a restart

Getting the app to answer once is the test. The manifests are the deliverable, and someone will use
them to work in that box. Read this before you write the final manifests (SKILL.md §5b).

## 1. The checkout is editable, but nothing rebuilds it for you

Measured, not assumed:

- The checkout is writable and the developer can edit it freely.
- **An in-box edit triggers nothing.** There is no periodic converge to notice it: a box sat
  untouched for 19 minutes after an edit with the reconcile id never moving. The run loop is driven
  by a configuration change reaching the box, not by the box watching its own files.
- **`watchPaths` still matters, for a different reason than it looks.** When a converge does happen
  (a config edit, a restart, a re-apply), a `runPolicy: onChange` step with no `watchPaths` degrades
  to content-hash `once` and is **skipped**, so the moved source is never rebuilt. With
  `watchPaths` it re-fires. Verified: after an in-box edit, forcing a converge by changing an
  unrelated field re-ran the build step whose own content had not changed.

```yaml
- name: run-app
  runPolicy: onChange
  watchPaths: [/home/dev/src/<app>]
```

So tell the developer the truth about their inner loop: **rebuild in the box** (`docker compose up
-d --build`, or whatever their run command is), which is immediate and is what they would do in a
terminal anyway. `watchPaths` keeps a *converge* honest; it is not a file watcher. To force a
rebuild from the laptop, apply a config change. An identical re-apply pushes nothing and converges
nothing.

## 2. Git must work for commits, not just the clone

A `git` devtool installs the binary; it does not give the box an identity, and with none
`git commit` refuses outright. So the manifest needs a `git` toolconfig, but ship it **commented
out, with placeholders**:

```yaml
# Uncomment and fill in to be able to COMMIT from inside the box.
# toolconfigs:
#   - id: git
#     name: git
#     config:
#       userName: "<your name>"
#       userEmail: <you@example.com>
```

**Do not bake the host's real `git config --global` values into it.** `.ringleader/` is written into
the project repository and is meant to be committed and shared, so a personal name and email would
land in someone else's tree, and be wrong for every other developer who uses these manifests. The
only exception is the user explicitly telling you to use their identity.

Same reasoning, opposite conclusion, for the key: an `SSHKey` is **required** for a private clone,
so generate it. For a **public** repo a developer who wants to `git push` still needs one, because
the forwarded agent is the box's only outbound credential. So ship `sshkey.yaml` **commented out**
with a note saying why, rather than omitting it. `spec.path` is a path on the developer's own laptop,
so it is safe to leave as an example; the identity fields are not.

## 3. Say what the box does not have

The clone is `git clone --depth 1`, a shallow checkout, so `git log`, `git blame` and branch
switching are degraded until the developer runs `git fetch --unshallow`. Put that in the report
rather than letting them discover it.

## 4. Restart behavior: assume it is broken until you prove otherwise

`rl workstation stop` is a **hard kill** of the VM process, and `start` boots the same disk again.
In practice:

- **On-disk state survives** (the generated `.env`, the checkout, uncommitted edits): the same disk
  is reused.
- **Nothing that was running comes back.** Docker containers with no `restart:` policy stay down.
- **Your scripts do not re-run.** Their ledger markers live on that surviving disk, so a
  `runPolicy: once` step, or an `onChange` step with no `watchPaths`, is skipped.
- **The box still reports `Configured: True` and `Ready: True`.** The verdict is re-derived, and
  re-derives clean *because every step was skipped*.

So the default outcome of a stop and start is **a healthy-looking box serving nothing.** Close it
with a cheap, idempotent liveness step that is allowed to run every time:

```yaml
- name: ensure-app-up
  phase: user
  runPolicy: always        # never gate-skipped; no build, so it is cheap
  content: |
    set -e
    cd ~/src/<app>
    docker compose up -d   # no --build: brings back what is already built
```

Prove it before you report success: `rl workstation stop <name>`, then `start`, wait, and `curl` the
forwarded port again. If you did not test the restart, say so in the report rather than implying it
works.

**A destructive corollary:** because sizing is fixed at create (SKILL.md §5), the remedy for an
undersized box is delete and recreate, which **wipes the overlay disk**. That takes the generated
`.env` and any uncommitted work with it, and a `seed-env` step then mints *new* random secrets. Get
sizing right before the first apply, and warn the user that a recreate is not a restart.
