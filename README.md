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

**On cost.** A default run is ten short Haiku generations plus one Sonnet
critique. An earlier version of this README claimed the 150-word output cap, not
the agent count, was what kept it cheap, and that `--deep` therefore costs less
than you would guess. **Measurement says the opposite.**

| Wave | Measured total |
|---|---|
| `--n 6` | 272k tokens |
| default `N=10` | 419k and 442k (two runs) |
| `--deep` (`N=25`) | not run; ~1.0M projected |

Roughly 37k per generator and 55–66k for the critic, near-constant per agent and
dominated by *input*. On Claude Code a subagent cannot be spawned with its tool
list emptied, so each generator pays for a full agent system prompt regardless of
writing 120 words. The agent count is the cost driver; the output cap is a
rounding error. Keep the cap anyway — raising it buys nothing — but budget
`--deep` as a deliberate spend, not a free upgrade. On a harness that can spawn
genuinely tool-less subagents this floor collapses; re-measure before assuming.

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

Not re-tested cold: `--deep`, natural-language triggering without naming the
skill (unverifiable from inside a session that already named it), and the
`awk` fallback on a real macOS box without coreutils.

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
