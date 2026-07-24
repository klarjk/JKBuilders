# JKBuilders

> A development workflow collection for Claude Code — from multi-session development orchestration to requirements, implementation, and review, all driven by a single command with multiple specialist agents collaborating behind the scenes.

[한국어](README.md) | **English**

---

## What is this?

A collection of **workflow tools** for building software in Claude Code. Planning development, making design decisions, and implementing/testing/reviewing code are split across specialist agents and skills. A single command (`/dev-loop`, `/impl`, `/prp-plan`, etc.) sets the relevant agents collaborating automatically behind the scenes.

## What's inside?

It's organized into four families.

| Family | What it does | Entry command |
|--------|--------------|---------------|
| **/dev-loop family** | Multi-session development orchestration — plan → design → implement → review, looped per session | `/dev` · `/dev-loop` · `/impl` · `/adr` |
| **/prp family** | A one-shot pipeline from requirements → plan → implementation → PR | `/prp-prd` · `/prp-plan` · `/prp-implement` · `/prp-pr` · `/prp-commit` |
| **Memory family** | Auto-memory that lets skills/agents remember what they learned for the next run | `/add-memory` |
| **Other** | Conditional rule-trigger examples, etc. | `triggers_CLAUDE.md` |

For detailed flows and agent collaboration structure, see the [**full manual**](#full-manual).

## Installation

This repository is **built for Claude Code itself**, so let Claude do the install too. After cloning the repo, ask your own Claude something like this.

**Full install**

```
Port the workflows in this JKBuilders repo into my Claude Code system.
Copy agents/ · commands/ · skills/ · rules/ · rules-detail/ into the matching
locations under my ~/.claude/ , and merge the trigger definitions in
triggers_CLAUDE.md into my global ~/.claude/CLAUDE.md . Tell me first if
anything would collide with what I already have.
```

**Install one family only** (e.g. just the `/dev-loop` family)

```
Port only the /dev-loop family from JKBuilders into my system.
Install skills/dev · dev-loop · impl · adr · tdd-workflow and the agents/*
they spawn, plus rules/ · rules-detail/ , under my ~/.claude/ , and merge the
triggers in triggers_CLAUDE.md into my global CLAUDE.md .
```

## Things to watch out for

- **Install by family.** The items call one another (e.g. `/impl` auto-spawns planner · tdd-guide · code-reviewer). Take a single agent in isolation and the other agents it calls won't exist, so it stalls.
- **Paths assume the `~/.claude/` convention.** Install elsewhere and you must update the reference paths inside the files too.
- **Mind the model pins.** Each agent's frontmatter pins a `model: opus / sonnet / fable`. If your plan can't access that model, adjust it.
- **Auto-memory only works where the block is installed.** Attach it to the skills/agents you want via `/add-memory`.
- **The `/prp` family writes to `.claude/PRPs/`** — requirements, plans, and reports accumulate there.
- **Required settings.json** — this workflow assumes sub-agent spawning, parallel tracks, and nested convergence. Set `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` and `worktree.baseRef` in `~/.claude/settings.json` (see the full manual).

## Credits

A mix of original items and items adapted from external open source.

- **[Wirasm / PRPs-agentic-eng](https://github.com/Wirasm/PRPs-agentic-eng)** — all `/prp` family commands (prp-prd · prp-plan · prp-implement · prp-pr · prp-commit)
- **[everything-claude-code](https://github.com/affaan-m/everything-claude-code)** — agents architect · planner · tdd-guide · code-reviewer · security-reviewer · e2e-runner, skill tdd-workflow, rule testing
- Everything else is original.

## Full manual

For each command's usage flow, agent collaboration structure, and per-family detail, see:

- [Korean manual](docs/manual.ko.html)
- [English manual](docs/manual.en.html)
