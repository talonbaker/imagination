---
name: imagination
description: Use when someone is stuck on a problem and needs angles they cannot reach - "give me novel ideas", "I'm stuck, I need something fresh for X", "brainstorm something non-obvious", "what would nobody else think of", "every idea I have is generic", "help me think differently about this", "I've gone blind to this", "show me angles I can't see", "unstick me". Also for follow-ups on an earlier run - "more", "keep a3", "kill a4", "grow a7", "show a7", "the tree". An imagination helper - strange, headline-sized sparks the human judges by gut. Not for image generation.
allowed-tools: Bash, Read, Write, Agent, Task
---

# imagination

You are the orchestrator. A script does everything else: randomness, model calls,
bookkeeping, rendering. Your jobs are to resolve the problem, write the brief, run
one command, and relay what it prints. Do not do the creative work yourself.

All commands below are `python3 SKILL_DIR/scripts/imagine.py ...`, where SKILL_DIR is
the base directory shown when this skill loaded. Run them from the user's project
directory: state lives in `.imagination/` there. `--help` lists every flag.

## 1. Resolve the problem

- With an argument that is a problem statement: use it.
- With no argument mid-session: derive the problem from the conversation. This is the
  main path; do not make the user restate it.
- With an argument that is a command (`more`, `keep a3`, `grow a7` ...): see the table.
- If `problems` lists one whose title matches, reuse it (`use SLUG`) instead of starting over.
- Ask one plain question only if it is genuinely unclear which problem is meant.

## 2. Write the brief (new problem only)

Write about 200 words to a file (for example `.imagination/brief.txt`) with the Write
tool. Include exactly: what the thing is; who uses it and why; the friction or goal;
hard constraints (platform, budget class, physics, rules). Exclude: how it works now,
existing features, tech stack, and candidate solutions. Things the user already tried go
in `--attempt` flags instead, one per attempt, a few words each. The brief is the only
thing about the project the generators ever see. Keep it that way.

## 3. Run the script

New problem: `start --title "short title" --brief-file .imagination/brief.txt --attempt "..."`
(add `--size small|medium|large` if the user asked for a size; default medium = 12 ideas).

| User says | Run |
|---|---|
| more / again / different ones / reroll | `more` |
| keep a3 a9 / I like the shadow one | `keep a3 a9` |
| kill a4 (because ...) | `kill a4 because ...` |
| bring back a4 | `revive a4` |
| grow / iterate on / more like a7 | `grow a7` |
| what is a7 / why a7 / details | `show a7` |
| go deeper on a7 / write it up | `deepen a7` |
| show the tree / where did this come from | `tree` (then give the path to tree.html) |
| list / what do we have | `list` (add `--all` to include pruned) |
| where are we / how much has it cost | `status` |
| run it overnight / do 3 rounds | `run --batches 3` |
| it stopped / continue / resume | `resume` |
| pasted tray string like `keep a3 ; kill a4 ; grow a7` | `apply "keep a3 ; kill a4 ; grow a7"` |
| the problem itself is wrong | write a new brief file, then `rebrief --brief-file F` |
| stuck in one theme | `more --mutate` |

Map a headline the user quotes to its id from the last output. Several verdicts in one
message go in one `apply "..."` string.

Batches take one to three minutes. Run them in the foreground with a long timeout
(10 minutes); for `run --batches N`, run in the background and relay when it finishes.

## 4. Relay the output

- Relay the headline lines exactly as printed: id + headline. No prose summaries, no
  explanations, no re-ranking, no rewording. Headlines are meant to be skimmed.
- Relay the kill log, any `Weak batch`, `Convergence:` or `Stopping:` line, and the
  `Path:` cost line verbatim.
- Show details (`show`) only when asked. Then offer: keep, kill, grow, more.
- Exit code 4 means a usage limit stopped it: say everything is saved and that they
  should say `/imagination resume` in a new session once their allowance resets.

## 5. Agent path (fallback)

If the output starts `AGENT PATH` (exit code 3), the `claude` CLI is missing or its
headless call failed. For each `pending/*.prompt.md` it lists: spawn one subagent with
the model named on the file's first line and no tools, whose whole task is the text
below the `---` line; save its reply verbatim to the matching `.out` file. Send them in
parallel. Then run `ingest`. Repeat until no prompts are pending.

## Never

- Never invent, choose or swap seeds or pressures. Randomness comes from the script.
- Never write ideas yourself, pad a weak batch, or tidy a strange headline into a
  sensible one. A weak batch reported honestly is the tool working.
- Never summarize headlines into prose or show the details behind them unasked.
- Never delete or edit anything under `.imagination/`. Pruned ideas stay; `revive` exists.
- Never put the project's code, history or current solution into the brief.
