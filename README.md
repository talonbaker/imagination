# imagination

A Claude Code skill for when you have stared at a problem so long you have gone
nose-blind to it. It does not try to give you the right answer. It throws strange,
headline-sized angles at the problem, drawn from outside the model's habits, and lets
your gut pick the ones that knock you loose. You keep, kill, or grow them, and it
remembers everything.

```
b1 · fresh · 12 ideas → 7 alive · 9 pressures
  ● a3   Can I have one minute of your money?
  ● a9   Budget Edits Take Effect Tomorrow
  ● a11  The coin box opens only on collection day
  ...
  killed, for the record:
    ✕ a7   No Calendar! Every Deposit Gets Its Own Envelope!  [exists: per-deposit envelopes with no month is standard envelope budgeting]
```

(Real output, from a test run on "budget-app users quit in week two".)

## How it works, in one paragraph

You (or the session you are in) describe the problem. A script asks a cheap model for
the ten obvious answers and puts them on a **wall**: everything you can already reach.
Then it draws random **pressures** (forcing moves such as *remove the most essential
part*, *solve it at the scale of a planet*, *solve it the way a lighthouse keeper
would*) with random **seeds** from shipped lists, and has cheap model calls build one
idea per pressure. Code throws out near-copies for free. A blind **decoy test** checks
whether each idea really came from its seed. One careful judging call kills what is
secretly obvious, already exists, or is noise, and names the **spark** (the underlying
connection) of every idea. You see only the headlines. Everything ever generated stays
in a log, so nothing repeats and nothing is lost.

## Install

Needs python3 (standard library only; macOS, Linux or WSL) and the `claude` CLI on
your PATH (it is, if you use Claude Code).

```bash
git clone https://github.com/talonbaker/imagination.git
cp -r imagination/skills/imagination ~/.claude/skills/
# or keep it updatable:  ln -s "$(pwd)/imagination/skills/imagination" ~/.claude/skills/imagination
```

State goes in `.imagination/` in the directory you run from. Add it to `.gitignore`
(`echo .imagination/ >> .gitignore`), or pass `--dir PATH` to put it elsewhere.

## Use

In Claude Code:

```
/imagination our co-op board game has a quarterback problem
/imagination                     (mid-session: it works out the problem from the conversation)
```

Then talk to it. Plain language works ("keep the coin box one, kill a4, more"); the
session maps it to commands.

| You say | What happens |
|---|---|
| `more` | Hard reshuffle: everything shown joins the wall, fresh seeds (never reused), least-used pressures first, recent themes banned |
| `keep a3 a9` / `kill a4 too cute` / `revive a4` | Your verdicts. Kills are never deleted, only marked |
| `grow a7` | Six offspring from a7's spark (not its wording), via grow pressures |
| `show a7` | What is behind the headline: pressure, seeds, bridge, spark, decoy result, verdict, lineage |
| `deepen a7` | One careful write-up: the bridge explained, what to try first, where it is likely wrong, prior art to search |
| `tree` | Text tree, and the path to `tree.html` |
| `list [--all]` / `status` | Headlines by batch / where things stand and what it has cost |
| `run --batches 3` | Unattended rounds; stops itself on convergence or a usage limit |
| `resume` | Finishes anything interrupted |
| `--size small/medium/large` | 6 / 12 / 24 ideas per batch (default medium) |

You can run the script directly too: `python3 ~/.claude/skills/imagination/scripts/imagine.py --help`.

### The tree

`tree.html` is one self-contained file (no network), light and dark. Branches
collapse, you can filter by status, clicking a headline shows what is behind it and
highlights its lineage, and each apple has keep / kill / grow / revive buttons that
build a command such as `keep a22 ; kill a10 ; grow a11` in a tray at the bottom.
**The page is read-only: it cannot change anything on disk.** Copy the tray string and
paste it into the chat.

## What it costs (measured)

On a Claude plan every model call counts against your usage allowance. That is why the
script makes the model calls itself through a lean headless `claude -p` call (no tools,
a short replaced system prompt, nothing saved) instead of spawning subagents. A
subagent carries the whole agent system prompt: v1 measured 37-44k tokens per worker.
A lean call has about 1.4k tokens of fixed overhead.

Measured in this repo's test runs (three problems, 14 batches, 68 calls), totals
include input, cache and output tokens:

| Call | Model role | Calls | Mean tokens | Range | Mean time |
|---|---|---|---|---|---|
| wall (obvious answers, once per problem) | generation | 3 | 2.8k | 2.6-3.0k | 5 s |
| worker (4 ideas) | generation | 36 | 9.4k | 7.1-13.4k | 34 s |
| decoy test (per batch) | generation | 14 | 5.3k | 3.5-9.9k | 11 s |
| critic (per batch) | judgment | 14 | 11.2k | 8.7-21.4k | 39 s |
| deepen (on request) | judgment | 1 | 4.9k | - | 21 s |

| Batch | Ideas | Batches measured | Mean tokens | Range | Wall-clock |
|---|---|---|---|---|---|
| small | 6 | 8 | 31k | 26-33k | about 1 min |
| medium (default) | 12 | 4 | 51k | 47-54k | about 2 min |
| large | 24 | 1 | 88k | - | about 2.5 min |
| grow | 6 | 1 | 31k | - | about 1 min |

`--no-decoy` saves the decoy line (4-10k per batch). For comparison, v1 spent 226-243k
for a 12-idea wave, so a v2 medium batch costs about a fifth of that.

Two honest notes. First, about half of each worker's tokens are the model's own
thinking (mean 4.7k of 9.4k), which the CLI does not let a script turn off; I tried
`--effort low`, `MAX_THINKING_TOKENS=0` and an `alwaysThinkingEnabled: false` setting
and none reduced it. Second, plans weight models differently and do not publish
allowances in tokens, so I cannot honestly convert these numbers into "batches per
hour of plan". The relative numbers above are what I can stand behind.

## Limits, stated plainly

- **Every call counts.** Generation goes to the cheapest model alias, judgment to a
  mid-tier one, and your main session model does almost nothing. It still costs what
  the table says. The aliases are set in `scripts/imaginelib/backend.py` and can be
  overridden with the `IMAGINATION_GEN_MODEL` and `IMAGINATION_JUDGE_MODEL`
  environment variables.
- **The HTML tree is read-only.** Keep, kill and grow happen through chat (or by
  pasting the tray string).
- **It cannot wake itself up.** An unattended run that hits your usage limit stops
  with everything saved up to the last finished call. You have to start a new session
  later and say `/imagination resume`.
- **Prior-art checking is offline memory.** The critic kills an idea as `exists` only
  when it can name the product or game, and its knowledge is incomplete and dated. It
  will miss things. `deepen` lists what to search for; do the search yourself.
- **Feasibility is a tag, never a filter.** `impossible` ideas stay alive on purpose.
- **Run it beside your own thinking, not instead of it.** When the right answer is
  correct-but-obvious, the critic kills it on purpose; the kill log is where you will
  see it.
- **Editing the skill:** Claude Code reads a skill file once per session and caches
  it. Edit SKILL.md, re-invoke in the same session, and you silently get the old
  version. Test edits in a fresh session, or run the script directly.
- **Agent fallback.** If `claude` is not on PATH or the headless call fails, the
  script writes its prompts to `.imagination/<problem>/pending/` and the session sends
  them as subagents, then runs `ingest`. It works (tested), but it costs the ~40k
  subagent overhead per call again and token use is invisible to the script.

## Extending it

- **Seeds** live in `skills/imagination/seeds/*.txt`, one per line (`#` lines are
  comments). The highest-leverage change you can make is adding mechanisms from your
  own field to `mechanisms.txt`: mechanisms, not nouns ("reefs grow on the skeletons
  of their own dead", not "coral"); distinct from each other; and a few you would be
  embarrassed to defend. The tests fail on duplicates.
- **Pressures** live in `skills/imagination/operators.json`: an id, a name, the seed
  pool it draws from, and a prompt template with `{seed}` (and `{wall}`). Adding one
  needs no code change. Grow pressures are in the same file.
- Tests: `python3 -m unittest discover -s skills/imagination/tests` (about one second;
  uses a fake CLI, no tokens).

Design choices, jargon and known weaknesses are in [DESIGN.md](DESIGN.md).

## Lineage

v1 (2026-08) was a single-shot pipeline of subagents: random mechanism seeds, blind
generators, one critic, a kill log. It established the parts v2 keeps (seeds from a
file sampled by a real RNG, blind generators, the mandatory collision, critic kill
reasons, salvage, honest weak-wave reporting) and measured the subagent cost that v2
was redesigned around. Its build notes are in [docs/v1-notes.md](docs/v1-notes.md).

## License

MIT.
