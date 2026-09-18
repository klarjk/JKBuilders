# JKBuilders

> A development workflow collection for Claude Code — from multi-session development orchestration to requirements, implementation, and review, all driven by a single command with multiple specialist agents collaborating behind the scenes.

[한국어](README.md) | **English**

---

## What is this?

A collection of **workflow tools** for building software in Claude Code. Planning development, making design decisions, and implementing/testing/reviewing code are split across specialist agents and skills. A single command (`/dev`, `/impl`, `/prp-plan`, etc.) sets the relevant agents collaborating automatically behind the scenes.

Multi-session development doesn't line the work up as a single sequence — it lays it out as a **work flowchart**. Each task is one box, connected by "what has to finish before this can start", so whatever can run at once does, and points where the result changes the path are handled as branches.

Implementation boxes that run in parallel are each handed to **their own isolated worktree and a separate Claude session**. The running sessions can be mirrored side by side in one window, and you can double-click a box that needs an answer to step straight in.

Inside tmux, add `--auto` and a stop condition (a time or a box to reach) to turn on **auto-continue**. It gathers every question only a human can answer up front in the first round, then keeps chaining fresh rounds on its own each time the context fills, until the stop condition. Choices met along the way are made by a judge agent, and any "can't go further" call is reviewed once more by a referee agent.

## What's inside?

It's organized into four families.

| Family | What it does | Entry command |
|--------|--------------|---------------|
| **/dev family** | Multi-session development orchestration — lays the work out as a flowchart, then runs research → design → build → review. Parallel boxes go to their own sessions, and it can optionally auto-continue to a stop condition | `/dev` · `/impl` · `/adr` |
| **/prp family** | A one-shot pipeline from requirements → plan → implementation → PR | `/prp-prd` · `/prp-plan` · `/prp-implement` · `/prp-pr` · `/prp-commit` |
| **Memory family** | Auto-memory that lets skills/agents remember what they learned for the next run | `/add-memory` |
| **Other** | Conditional rule-trigger examples, etc. | `triggers_CLAUDE.md` |

For detailed flows and agent collaboration structure, see the [**full manual**](#full-manual).

## Installation

This repository is **built for Claude Code itself**, so let Claude do the install too. After cloning the repo, ask your own Claude something like this.

**Full install**

```
Port the workflows in this JKBuilders repo into my Claude Code system.
Copy agents/ · commands/ · skills/ · rules/ · rules-detail/ · scripts/ into the
matching locations under my ~/.claude/ , and merge the trigger definitions in
triggers_CLAUDE.md into my global ~/.claude/CLAUDE.md . Tell me first if
anything would collide with what I already have.
```

**Install one family only** (e.g. just the `/dev` family)

```
Port only the /dev family from JKBuilders into my system.
Install skills/dev · impl · adr · tdd-workflow and the
agents/* they spawn, plus rules/ · rules-detail/ · scripts/ , under my
~/.claude/ , and merge the triggers in triggers_CLAUDE.md into my global
CLAUDE.md . Then walk me through the README's "Required setup" section.
```

## Required setup

The `/dev` family's parallel delegation and auto-continue need both of the items below. The other families (`/prp`, memory) only need item 1.

### 1. settings.json

```jsonc
{
  "env": { "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1" },
  "worktree": { "baseRef": "head" },
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.claude/scripts/status-writer.py"
  }
}
```

- **`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`** — enables nested spawning (a sub-agent spawning another sub-agent). Without it, `/impl`'s chain and `synthesizer`'s convergence stall.
- **`worktree.baseRef`** — the base commit parallel tracks branch their isolated worktrees from.
- **`statusLine`** — not decoration, but **`/dev`'s instrumentation**. It is where a session reads its own context usage; without it the stop-and-hand-off point, and auto-continue's round switch, are missed. If you already run your own status line script, graft the four lines described as **method ②** in the header of `scripts/status-writer.py`.

### 2. tmux

`/dev` launches the worker sessions for parallel implementation boxes through tmux, and auto-continue only turns on inside a tmux window. Without `tmux`, parallel boxes can't be handed to separate sessions and the main session handles them itself, and auto-continue stays off. `/impl` on its own doesn't need it.

## Things to watch out for

- **Install by family.** The items call one another (e.g. `/impl` auto-spawns planner · tdd-guide · code-reviewer). Take a single agent in isolation and the other agents it calls won't exist, so it stalls.
- **Paths assume the `~/.claude/` convention.** Install elsewhere and you must update the reference paths inside the files too.
- **Mind the model pins.** Each agent's frontmatter pins a `model: opus / sonnet / fable`. If your plan can't access that model, adjust it.
- **Auto-memory only works where the block is installed.** Attach it to the skills/agents you want via `/add-memory`.
- **The `/prp` family writes to `.claude/PRPs/`** — requirements, plans, and reports accumulate there.
- **Auto-continue runs without permission prompts.** So it doesn't stall while nobody is watching, it launches worker sessions with permission checks skipped. Only turn it on in repositories you trust.

## Credits

A mix of original items and items adapted from external open source.

- **[Wirasm / PRPs-agentic-eng](https://github.com/Wirasm/PRPs-agentic-eng)** — all `/prp` family commands (prp-prd · prp-plan · prp-implement · prp-pr · prp-commit)
- **[everything-claude-code](https://github.com/affaan-m/everything-claude-code)** — agents architect · planner · tdd-guide · code-reviewer · security-reviewer · e2e-runner, skill tdd-workflow, rule testing
- Everything else is original.

## Full manual

For each command's usage flow, agent collaboration structure, and per-family detail, see:

- [Korean manual](docs/manual.ko.html)
- [English manual](docs/manual.en.html)
