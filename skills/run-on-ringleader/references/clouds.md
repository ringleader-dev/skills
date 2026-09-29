# When the user names a cloud

Read this when the user asked for a cloud: "run this on GCP", "use AWS", "on Azure". Without that
request, none of it applies: manifests stay portable and local (SKILL.md §0b), and a cloud
workstation, which bills real money, is never a substitute for a missing local provider.

## Decide from `rl status`

Find the named provider in `remote.providers` of `rl status -o json`. That answer is
**configuration only**: `rl status` makes no network call about a cloud and validates no
credential.

- `available` → run there. Pin it on the **Workstation** with
  `spec.requirements: [provider:<name>]`, the spelling `manifests.md` documents, plus only the
  `providerConfig.<cloud>` fields the user gave you (below). Say in the run report that the user
  asked for the cloud and which fields came from them. The `WorkstationConfig` stays untouched and
  portable.
- `unavailable` → **STOP**, quoting its `reason`. That is a definite no.
- **a LOCAL provider's name** (`qemu`, `lima`, `wsl2`) → that is not a cloud request at all.
  Proceed exactly as unasked: write no pin, and let the daemon choose. Say in the report which
  local provider `rl status` shows `available`, so the user can see whether they got the one they
  meant.
- **any other name** → `rl status` names only the clouds this product knows (`aws`, `azure`,
  `gcp`). Stop, say which clouds exist, and let the user pick.
- `unknown` → you **cannot tell from this device**, and the usual cause is that the user is not an
  org administrator (only one may read `CloudAccount` objects). Pin it and proceed, and say in the
  report that availability could not be confirmed here and why. **This holds even when no local
  provider is available**: the user asked for a cloud, so a local one being absent changes
  nothing about their request. If the box then fails, report that failure together with the
  `reason` `rl status` gave. Refusing here would deny a user a cloud their organization has.

**If this `rl` is too old to have `status` (the paragraph in SKILL.md §3) and the user named a
cloud, still pin it.** You cannot confirm the cloud from here, which is the same position as an
`unknown` verdict, so do what that says: write the pin, say in the report that no check was
possible on this CLI, and let the BOX report it if the cloud is not there. The apply exits 0
whichever way it goes (below). Going local instead is the silent fallback, and an old CLI is not a
reason to give the user something they did not ask for.

Never fall back to a local provider when a cloud was named. A run that quietly goes local after the
user said "on GCP" reports success for work they did not ask for.

## The fields a cloud needs

**WHENEVER YOU PIN A CLOUD** (on `available`, on `unknown`, or on a `status`-less CLI) the
workstation ends up needing that cloud's placement fields. The product documents these as required
(`rl docs`, the Providers reference):

| cloud | required in `providerConfig.<cloud>` |
|---|---|
| `gcp` | `project`, `zone` |
| `aws` | `region` |
| `azure` | `subscriptionId`, `resourceGroup`, `location`, **and** `subnetId` **or** `networkInterfaceId` |

**Usually none of them is yours to write.** An organization's `CloudIdentity` supplies placement
through its `defaultProviderConfig` and `overrideProviderConfig`, so a workstation names only the
values that should differ. So **write what the user gave you and no more.** Do not invent any of
them: they are facts about the user's account. And do not STOP just because the user did not name
them: the `CloudIdentity` can supply them, so a run that refuses up front denies work that would
have succeeded.

**`rl apply` exits 0 either way.** A missing field shows up on the WORKSTATION rather than as an
apply error, and its `status.message` names the field. Read it, report it verbatim, and ask the
user for the named field. Which condition carries it depends on who refused:

- The placement fields are refused when the provider is built, so the box lands
  `ProviderUnavailable`.
- Azure's network field is checked later, when the VM is created, so that box lands `CreateFailed`.
  Its message names both `subnetId` and `networkInterfaceId`; ask which subnet to use.

That is why azure's network field surfaces differently from the rest: a different condition, the
same kind of message. The product can sometimes derive a field from another one (a region from a
zone, a subscription from a full subnet ID), so trust the message over this table when they
disagree. Never switch to a local provider to get around either.

**Three keys are not the user's to give**: `serviceAccount`, `managedIdentity` and
`iamInstanceProfile` are stripped from a member's config unconditionally and re-injected from the
admin-owned `CloudIdentity`. If the status names one of those, asking the user to set it loops
forever. Say instead that an org administrator has to attach it.

**The table is what the product documents, not the whole matrix.** Some fields are required only
in certain shapes, and some are admin-owned (above). Treat any status naming a
`providerConfig.<cloud>.<field>` the same way: report it verbatim, and ask whoever owns that field,
the user for an account fact and an org administrator for an identity key. Never guess one.

**A cloud-pinned Workstation needs a control plane.** It routes to the logged-in control plane and
errors when logged out, which is why it is never in the portable default. `rl status` already says
so: `remote.loggedIn` is false on a device with no control plane, and every remote provider then
carries a `reason` that says to log in.

## Every other `providerConfig` key

Add no OTHER `providerConfig` key unless the user named it. Most of them size a machine somebody
pays for: `machineType`, `diskGiB`, `instanceType`, `size`. If the user asked for a size, use the
cloud's own key, and say in the run report what the box actually got.

Not all of them are about money: on `aws`, `subnetId` and `securityGroupIds` decide where the box
lands and whether anything can reach it. Left empty, EC2 places the box in the account's default
VPC and security group, which may permit no inbound SSH, so the box boots, bills, and the device
cannot dial it. So if an aws box comes up but the reachability check cannot dial it, ask for those
rather than guessing a network. A cloud workstation is dialed
directly on port 22, so a box that reports `Ready` can still be unreachable when no firewall or
security-group rule allows inbound TCP 22.

The flat local keys (`memory`, `cpus`, `disk`) mean nothing to a cloud provider, which reads
`providerConfig.<cloud>` only. A cloud block discards a typo'd key silently, exactly as the local
one does.

## In the run report

- `workstation.provider`: the cloud you pinned, and whether `rl status` could confirm it.
- The `providerConfig` fields you wrote, and who gave you each one.
- **`environment` also covers a cloud box that failed for a missing required field.** Unlike the
  no-provider stop, that one HAS built objects, but the field is the user's or an administrator's
  to supply rather than your mistake, so it is never `manifest`. Name the field in
  `result.notes`.
- Copy the `Ready=False` condition into `workstation.failedReason` and
  `workstation.failedMessage` verbatim, as SKILL.md §7 says for every failed box. `rl status`
  still reports the provider `available` after such a failure, and has nothing to say about why
  the box died.
