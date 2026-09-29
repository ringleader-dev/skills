# Choosing the SSH key for a private repository

Read this when §3 check 6 finds the repository is private. A private repo cannot be cloned without a
forwarded key, and a missing key fails six minutes later, inside the box, as a clone error.

Work down this list and stop at the first confident answer. Do not silently pick one when two are
plausible.

1. **The user named a path** ("my key is at ~/.ssh/id_github") → use it verbatim.
2. **An existing `SSHKey` object already covers this box**: `rl sshkey get -o yaml`. Check
   `spec.enabled` is not false and that `spec.selector` will match the label you are about to
   put on the Workstation (an absent selector matches everything). If one covers it, **do not
   create a second**. Say which one you are relying on.
3. **The agent already holds a key**: `ssh-add -l`.
4. **`~/.ssh/config` names one for the host**: `ssh -G github.com | grep -i '^identityfile'`,
   the one git itself would use.
5. **Exactly one plausible private key on disk**: an `~/.ssh` entry with a matching `.pub`
   sibling, excluding `known_hosts`/`config`/`authorized_keys` → use it and say so.
6. **Otherwise ask.** Two or more candidates, or none, is a question, not a coin flip.

A named path that is not there is not the end of the list: say so and carry on down 2–5.

**NEVER MINT A CREDENTIAL, AND NEVER SPEND ONE THE HOST ALREADY HOLDS.** When the list is exhausted,
non-interactively, that is a *stop*: report it and finish. Every one of these is off the allowlist:

- `ssh-keygen -t …` to create a keypair, deploy key or token of any kind.
- `gh`, `glab`, `aws`, `gcloud`, `az`, any CLI that acts on a remote service with the invoker's
  stored credentials, and above all anything that **writes to the user's own account**
  (`gh api user/keys`).
- Lifting a token out of the host (`gh auth token`, a `~/.netrc`, an env var) into a manifest, a
  `Secret`, or the box. The host shell expands `$(gh auth token)` *here*, before `rl` ever starts.

A private repository the device cannot reach is a clean, honest failure: `result.reachable:
false`, `result.failureClass: "credentials"`, and `result.notes` naming the credential you looked
for and where. Create nothing, no `Workstation`, no `SSHKey`, no `Secret`.

Verify the choice actually authenticates before you build a box around it:

```bash
ssh -T -o BatchMode=yes -o IdentitiesOnly=yes -i <key> git@github.com   # 1 + a welcome = good
```

**The `SSHKey` must land in the same namespace as the Workstation** or it is silently not
forwarded. It is device-local: `spec.path` points at the key on this laptop and the material never
leaves the device.
