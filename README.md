# Ringleader skills

Agent skills for working with [Ringleader](https://ringleader.dev) workstations. Each skill is a
plain [Agent Skills](https://agentskills.io) folder under `skills/`, so it works in Claude Code,
Codex, and any other agent that reads `SKILL.md`.

| Skill | What it does |
| --- | --- |
| [`run-on-ringleader`](skills/run-on-ringleader/) | Takes a code repository and gets it running on a Ringleader workstation, reachable on a local port. It writes reusable `.ringleader/` manifests and tears the workstation down afterwards. |

## Install

In **Claude Code**, add this repository as a plugin marketplace, then install a skill from it:

```
/plugin marketplace add ringleader-dev/skills
/plugin install run-on-ringleader@ringleader
```

In **Codex**, which reads the same marketplace:

```bash
codex plugin marketplace add ringleader-dev/skills
codex plugin add run-on-ringleader@ringleader
```

For **any other agent** (Cursor, Gemini CLI, GitHub Copilot, OpenCode and more), use the
[`skills`](https://github.com/vercel-labs/skills) installer:

```bash
npx skills add ringleader-dev/skills --skill run-on-ringleader
```

To install **by hand**, copy a skill's folder into `~/.claude/skills/` for Claude Code, or into
`~/.agents/skills/` for Codex and most other agents. Start a new session afterwards, because agents
read skills when a session starts.

## Contributing

This repository is published from Ringleader's internal one, and each publish replaces its
contents. A pull request here cannot be merged directly. Open an issue instead, and we will make
the change upstream.
