# JKBuilders

> A development workflow collection for Claude Code — from multi-session development orchestration to requirements, implementation, and review, all driven by a single command with multiple specialist agents collaborating behind the scenes.

[한국어](README.md) | **English**

---

## What is this?

A collection of **workflow tools** for building software in Claude Code. Planning development, making design decisions, and implementing/testing/reviewing code are split across specialist agents and skills. A single command (`/dev-loop`, `/impl`, `/prp-plan`, etc.) sets the relevant agents collaborating automatically behind the scenes.

Multi-session development doesn't line the work up as a single sequence — it lays it out as a **work flowchart**. Each task is one box, connected by "what has to finish before this can start", so whatever can run at once does, and points where the result changes the path are handled as branches.

`/dev-loop` goes one step further. **It hands each box of the flowchart to a separate Claude session** working in its own isolated worktree, and repeats that delegation until the plan is done. Only irreversible operations and design choices a human has to make stay on your screen.

## What's inside?

It's organized into four families.

| Family | What it does | Entry command |
|--------|--------------|---------------|
| **/dev-loop family** | Multi-session development orchestration — lays the work out as a flowchart, then loops research → design → build → review to completion. Each node is delegated to its own session | `/dev` · `/dev-loop` · `/impl` · `/adr` |
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

**Install one family only** (e.g. just the `/dev-loop` family)

```
Port only the /dev-loop family from JKBuilders into my system.
Install skills/dev · dev-loop · impl · adr · tdd-workflow and the
agents/* they spawn, plus rules/ · rules-detail/ · scripts/ , under my
~/.claude/ , and merge the triggers in triggers_CLAUDE.md into my global
CLAUDE.md . Then walk me through the README's "Required setup" section.
```

## Required setup

The `/dev-loop` family needs items 1 and 3 (item 2 is optional). The other families (`/prp`, memory) only need item 1.

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
- **`statusLine`** — not decoration, but **`/dev`'s instrumentation**. It is where a session reads its own context usage; without it the stop-and-hand-off point is missed. If you already run your own status line script, graft the four lines described as **method ②** in the header of `scripts/status-writer.py`.

### 2. Telegram (optional — only if you want the postman)

The postman (`skills/postman/`) is a **standalone relay** that forwards Claude session questions to Telegram and injects your reply back into that session's screen. It is not a component the `/dev-loop` family requires, and **`/dev-loop` runs fine without it** — questions simply appear on screen only, and you have to be at the desk.

1. Create a bot with `/newbot` via `@BotFather` on Telegram and take the token.
2. Put the token **in a file, nowhere else**. The default location is `~/.claude/dev-run/telegram-bot-token`; point `POSTMAN_TOKEN_FILE` elsewhere if you prefer.

   ```bash
   mkdir -p ~/.claude/dev-run
   install -m 600 /dev/null ~/.claude/dev-run/telegram-bot-token
   # open it in an editor and paste the single token line (echo lands in shell history)
   ```

3. Send your bot any 1:1 message and look up your own user id (`from.id` in Telegram's `getUpdates`).

4. **Create the config at mode 600 first**, then fill it in with an editor — an editor creating it from scratch leaves it at 644.

   ```bash
   install -m 600 /dev/null ~/.claude/postman/config.json
   ```

   ```jsonc
   {
     "allowed_user_ids": [123456789],
     "chat_id": 123456789,
     "never_send": ["~/private-notes.md"]
   }
   ```

5. Verify. **Fix and re-run if it prints even one warning** — the exit code is 0 even with warnings, so read the count on the last line to judge a pass.

   ```bash
   python3 ~/.claude/skills/postman/postman/bot.py --check
   ```

> ⚠️ **Do not leave `never_send` empty.** The postman captures session screens and sends them to Telegram. Register the paths of any plaintext personal files here so their contents can't ride out in a screen capture. An empty `allowed_user_ids` makes it discard every incoming update, which kills the channel silently.

See `skills/postman/README.md` for the full protocol and file layout.

### 3. tmux

`/dev-loop` launches the worker session for each node through tmux. Without `tmux` it stops at the pre-spawn check. `/dev` and `/impl` on their own don't need it.

## Things to watch out for

- **Install by family.** The items call one another (e.g. `/impl` auto-spawns planner · tdd-guide · code-reviewer). Take a single agent in isolation and the other agents it calls won't exist, so it stalls.
- **Paths assume the `~/.claude/` convention.** Install elsewhere and you must update the reference paths inside the files too.
- **Mind the model pins.** Each agent's frontmatter pins a `model: opus / sonnet / fable`. If your plan can't access that model, adjust it.
- **Auto-memory only works where the block is installed.** Attach it to the skills/agents you want via `/add-memory`.
- **The `/prp` family writes to `.claude/PRPs/`** — requirements, plans, and reports accumulate there.
- **One postman per machine, one project at a time.** A Telegram bot has exactly one receiver, so two projects running at once will intercept each other's messages.

## Credits

A mix of original items and items adapted from external open source.

- **[Wirasm / PRPs-agentic-eng](https://github.com/Wirasm/PRPs-agentic-eng)** — all `/prp` family commands (prp-prd · prp-plan · prp-implement · prp-pr · prp-commit)
- **[everything-claude-code](https://github.com/affaan-m/everything-claude-code)** — agents architect · planner · tdd-guide · code-reviewer · security-reviewer · e2e-runner, skill tdd-workflow, rule testing
- Everything else is original.

## Full manual

For each command's usage flow, agent collaboration structure, and per-family detail, see:

- [Korean manual](docs/manual.ko.html)
- [English manual](docs/manual.en.html)
