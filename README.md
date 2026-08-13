# imagination

A Claude Code skill that returns 2–4 genuinely non-obvious ideas for a problem,
instead of the ideas any competent team would already have had by lunch.

It works by forcing a collision. Ten isolated generators each receive the same
short problem brief plus **two random mechanism-phrases drawn from a file of 500**
— things like *"reefs grow by building on the skeletons of their own dead"* or
*"the winner pays the second-highest price, which makes honest bidding optimal."*
Each generator must build its idea's core mechanism out of its seed. Then a
single critic kills everything that is secretly obvious or structurally empty,
and returns only what survives.

## Why not just ask for novel ideas

Because asking a language model for novelty produces the *average* of what gets
called novel, which is not novel. Three specific failures, and what this does
about each:

| Failure | Fix |
|---|---|
| Asked to "pick something random," models converge on the same clichés — octopus, jazz, mycelium, origami | Entropy comes from a shipped seed file sampled with `shuf`, never from the model |
| Given the codebase and the history, ideas drift back toward what already exists | Generators get problem context and are **denied** solution context; they never see the repo or the conversation |
| Random inspiration becomes decoration on a standard idea | The generator prompt's litmus test: *if your idea still makes sense with the seed deleted, you failed* |

The critic exists because this trade is deliberate: forcing collisions raises the
ceiling and lowers the floor. Roughly two thirds of each wave is chaff. Someone
has to throw it out, and it should not be you.

## Install

Copy the skill into your skills directory:

```bash
git clone https://github.com/talonbaker/imagination.git
cp -r imagination/skills/imagination ~/.claude/skills/
```

Or symlink it, so `git pull` keeps you current:

```bash
ln -s "$(pwd)/imagination/skills/imagination" ~/.claude/skills/imagination
```

For one project only, use `.claude/skills/` in the project root instead.

Requires `shuf` (standard on Linux, and in Git Bash on Windows). On macOS
without coreutils the skill falls back to an `awk`-based sampler automatically.

*Not shipped as a plugin marketplace entry.* The single-directory copy above is
the supported path; adding a marketplace manifest would mean guessing at a format
this repo has not verified, and a broken manifest is worse than no manifest.

## Use

```
/imagination novel ways to show long-running job progress in a CLI tool
```

Or — the path that matters more — invoke it **with no argument** in the middle of
a session where you are already stuck. It distills the problem out of the
conversation you are having and runs on that.

```
/imagination
```

It also triggers on plain requests: *"give me some non-obvious ideas for this,"*
*"every approach I've come up with is generic."*

### What a run looks like

```
10 generated, 3 survived.

1. Milestone Commits
   Mechanism: an append-only, timestamped log of phase-completion events that
   persists across restarts and disconnects. Each new attempt shows the furthest
   milestone any prior attempt ever reached alongside the current run's live
   position.
   Non-obvious: standard progress displays reset every run; this treats the
   operation's own history as a permanent ruler, so a killed-and-restarted job
   has a benchmark instead of starting the anxiety over from zero.
   Prototype first: add commit-logging to a flaky migration that fails partway
   on repeat runs.
```

Seed for that one: *"the rules are permanently altered by what happens, and never
revert."*

## Knobs

| Flag | Effect |
|---|---|
| *(default)* | 10 generators, 2 seeds each, 1 critic |
| `--deep` | 25 generators. For when a default wave came back weak, or the problem is worth real money |
| `--n <k>` | Explicit wave size |

**On cost.** Cost is per *worker* and almost flat, so the same idea count from
fewer workers is a near-proportional saving. That is why a worker carries three
collisions rather than one.

| Wave | Workers | Ideas | Measured total |
|---|---|---|---|
| `--n 8` | 3 | 8 | 183k |
| default | 4 | 12 | 226k, 243k (two runs) |
| `--deep` | 8 | 24 | 424k |

A one-collision worker costs ~37k; a three-collision worker ~42k. Three ideas for
14% more than one is the entire argument. On Claude Code a subagent cannot be
spawned with its tool list emptied, so each worker pays for a full agent system
prompt regardless of writing 400 words — the cost is *input*, and the 150-word
cap exists for critic legibility, not economy. Keep it anyway; raising it buys
nothing.

The pre-batch design spent 419k and 442k to produce *ten* ideas. `--deep` now
returns 24 for less than that.

`--deep` buys more shots on goal, not more survivors — the critic caps output at
4 either way, and the 24-idea wave measured here returned fewer survivors (2)
than a 12-idea wave (3). Reach for it when a default wave came back weak.

**The batch trade, stated plainly.** Three ideas from one worker risks
*within-worker contamination* — idea 2 quietly restating idea 1's mechanism in a
new wrapper. Two guards contain it: sealed-assignment rules in the worker prompt
(complete each idea before reading the next seed pair; restate prior mechanisms
and re-derive on convergence) and the critic's duplicate test, which sees all
ideas flattened and unattributed so convergence cannot be excused by provenance.
Measured across the four retest runs: one worker in four converged in the first
run, one in eight after the sealed-assignment wording was strengthened.
Cross-worker duplicates appeared at similar rates, which says most convergence
is driven by narrow problems rather than by batching.

## Tuning notes

What was measured while building this, and what it changed:

- **Three end-to-end runs before first commit** — a UI/UX problem (CLI progress
  display), a backend problem (cache invalidation for a small SaaS), and a
  non-code problem (weekly team retro format). Results: 3, 3 and 4 survivors from
  waves of 10. The kill rate of 60–70% is the design working, not the design
  failing; it matches the roughly 1-in-3 hit rate the wave size was chosen for.
- **The generator prompt needed no softening or hardening across those runs.**
  The collision bound in every wave. The one amendment the runs forced was
  operational, not creative: some harnesses cannot spawn a subagent with its tool
  list emptied, so `Use NO tools; answer directly` is now stated in the prompt
  itself rather than assumed from the spawn config.
- **The critic's kill reasons are worth reading.** Across the three runs it
  correctly identified *liveness dots per work unit* as the oldest CLI pattern
  there is, *transaction-offset netting* as incremental view maintenance in
  costume, and *alternating anonymous/discussion/breakout/report segments* as the
  standard four-phase Scrum retro. All three read as fresh in isolation. That is
  exactly the chaff the second stage exists to catch.
- **Seed independence was verified**, not assumed: three consecutive 20-seed
  draws overlapped by 2 of 20 — consistent with sampling 20 from 500 without
  replacement, i.e. real RNG rather than a model's idea of one.
- **Honest failure is a feature.** If fewer than 2 ideas survive, the skill says
  the wave was weak and offers a re-roll. It does not pad the list to look
  productive.

### Cold-start test pass, 2026-08-13

The three runs above were executed by the agent that wrote the skill — the
weakest possible test. A second agent re-ran it cold. Three runs, three problem
shapes, all completed with no manual patching:

| Run | Problem | Wave | Survived |
|---|---|---|---|
| 1 | co-op horror: making players *want* to leave safe light | 10 | 3 |
| 2 | this tool's own cost problem, invoked with **no argument** | 10 | 3 |
| 3 | solo dev drowning in unreviewed agent output (`--n 6`) | 6 | 1 |

Three things that testing changed:

- **The `awk` fallback was silently broken, and only on the argument path.**
  Claude Code substitutes dollar-sign-digit tokens in a skill file with the
  invocation's arguments. `$0` inside the fallback became the first word of the
  user's problem statement, so the command printed blank lines instead of seeds
  — and the likely next move for a model holding an empty seed list is to invent
  seeds, which destroys the whole premise while still producing plausible output.
  Never triggered in the author's runs because `shuf` exists on their machine.
  The fallback is now written with `paste` so no such token appears in the file
  at all, and Step 3 now requires checking that the draw actually returned seed
  text. (The first version of the warning contained literal `$0` examples and so
  mangled *itself*; it is now written out in words.)
- **The cost claim was backwards**, as measured above.
- **Run 3 hit the honest-failure path for the first time** — 1 survivor from 6 —
  and reported it as weak rather than padding. Run 2 exercised `[SALVAGED]`,
  which turned a mediocre idea into the best one in the wave. Both paths work.

**One limitation worth knowing before you rely on this.** In run 2 the tool was
pointed at a real problem whose correct answer was *obvious* — batch several
seeds into one worker to amortise a fixed startup cost. Two generators found it.
The critic killed both, correctly by its own rules, as things a competent team
would reach in twenty minutes. The novelty filter has no channel for
correct-but-obvious, by design. This is a complement to ordinary problem-solving
and a bad substitute for it: run it *beside* your own thinking, never instead.

That answer turned out to be right, and it is now how the tool works — which is
exactly why the **kill log** exists. Every non-survivor is reported back in one
line with its kill reason (`obvious`, `costume`, `no-kernel`, `duplicate`). It
changes nothing about what survives; it just means the correct-but-obvious answer
gets named on its way out instead of vanishing. If the thing you actually needed
is in that list, the tool still found it for you.

### Batched waves, 2026-08-13

Cost measurement drove a redesign: one worker now carries three collisions
instead of one. Four cold runs after the change, all completing unassisted:

| Run | Problem | Invocation | Workers | Ideas | Survived | Tokens |
|---|---|---|---|---|---|---|
| A | co-op horror: wanting to leave safe light | argument | 4 | 12 | 3 | 226k |
| B | this skill's own stale-cache problem | **no argument** | 4 | 12 | 2 | 243k |
| C | judging your own work with fresh eyes | `--n 8` | 3 | 8 | 3 | 183k |
| D | indie launch visibility | `--deep` | 8 | 24 | 2 | 424k |

Also found and fixed in the same pass: `awk`'s bare `srand()` seeds from the
clock at one-second granularity, so two fallback draws inside the same second
returned identical seeds — real-looking randomness that isn't. Now seeded
explicitly, and verified by two same-second draws returning different seeds.

Not re-tested cold at the time: natural-language triggering without naming the
skill (structurally unverifiable from inside a session that already named it),
the `awk` fallback on a real macOS box without coreutils, whether the seeded
fallback survives argument substitution *as delivered*, and a default-shape run
after the sealed-assignment wording was strengthened. The last two are closed
below.

**A caching gotcha for anyone editing this skill.** Claude Code reads a skill
file once per session and reuses it. Edit the file, invoke it again in the same
session, and you silently get the *old* version — the run looks entirely normal.
Any "I fixed it and retested" done in one sitting is testing the pre-edit file.
Verified here: a re-invocation after editing served the previous body while
`diff` confirmed the new text was on disk. Start a fresh session to test an edit,
or execute the file's instructions from a direct read rather than the invocation.

### Fresh-session verification, 2026-08-13

The batched redesign was measured by the agent that built it, in a session where
the caching gotcha above applies. That left two questions open. Both are now
closed from a session that had never loaded the skill body.

**Loader delivery: verified.** Invoking the skill served the current batched body
— wave-shape table, three-collision worker prompt, measured cost tables — and the
fallback line arrived intact as `awk -v seed="${RANDOM:-$$}"`. Nothing in it was
substituted. The `paste` rewrite holds *as delivered*, not merely as written.

**One more default wave, cold:**

| Run | Problem | Invocation | Workers | Ideas | Survived | Tokens |
|---|---|---|---|---|---|---|
| E | persisting player-built structures across nights | argument | 4 | 12 | 4 | 222k |

24 of 24 seeds drawn non-empty and unique, counted in the shell. All four workers
reported zero tool calls. Kill log complete — all eight non-survivors named
exactly once. Cost sits inside the 226k/243k band already measured.

**Within-worker convergence was zero.** The wave's one duplicate kill was
*cross*-worker: two workers who cannot see each other independently arrived at
pay-upkeep-or-decay. That is the strengthened sealed-assignment wording holding
on the default shape, and it is further evidence for the earlier finding — most
apparent batch contamination is a narrow solution space rather than a worker
riffing on itself. A duplicate kill is not automatically a batching failure, and
reading it as one would lead you to weaken batching for no gain.

Still open, unchanged: natural-language triggering without naming the skill, and
the `awk` fallback on a real macOS box without coreutils.

## The seed file

`skills/imagination/seeds.txt` — 500 unique lines, each a *mechanism* (how
something works) rather than a noun, spanning cell biology, ecology, insect
behavior, fermentation, geology, physics, materials science, failure engineering,
logistics, military doctrine, economics, auction theory, historical trade, law,
linguistics, game mechanics, sports rules, music theory, cooking technique and
theater production.

"Coral reef" would be a bad seed. *"Reefs grow by building on the skeletons of
their own dead"* is a good one, because it hands the generator a structure to
borrow rather than an image to decorate with.

Add your own domain's mechanisms if you have one — that is the single highest-
leverage change you can make to this tool. Keep them mechanical, keep them
distinct from each other, and keep a few you would be embarrassed to defend.

## License

MIT.
