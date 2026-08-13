---
name: imagination
description: Use when someone wants genuinely novel, non-obvious, original or fresh ideas for a problem - "give me novel ideas", "I'm stuck, I need something fresh for X", "brainstorm something non-obvious", "what would nobody else think of", "every idea I have is generic", "help me think differently about this". Forces ideas out of the model by colliding the problem with randomly drawn mechanism-seeds, then killing everything that is secretly obvious. Not for image generation.
allowed-tools: Bash, Task, Agent, Read
---

# imagination

Produce 2-4 genuinely non-obvious solution ideas for a problem, by forcing each
idea's mechanism to be structurally borrowed from a randomly drawn concept the
model did not choose.

## Why it is built this way

Do not restructure these. Every failure mode of idea-generating agents traces to
violating one of them.

1. **Entropy comes from outside the model.** A model asked to "pick something
   random" converges on the same handful of clichés. Randomness comes from
   `seeds.txt` sampled with a real RNG, never from a model's idea of random.
2. **Context is an anchor, not just fuel.** Generators get problem context
   (what the thing is, who uses it, hard constraints) and are deliberately
   denied solution context (how it works now, what has been tried, house
   conventions). Solution context is what drags ideas back to the obvious.
3. **The collision is mandatory, not decorative.** Each idea's core mechanism
   must be built out of its seed. If the idea survives deleting the seed, the
   generator failed.
4. **Small N with a hard prompt beats large N with a soft one.** A dozen ideas,
   not fifty. A strict collision prompt hits roughly one-in-three, which yields
   the target 2-4 survivors without a token spike. How many *workers* carry
   those ideas is a cost question, not a design one - see Step 4.
5. **The critic kills two ways and salvages one.** Chaff is either secretly
   obvious or pure noise. But good ideas often arrive half-broken, so the critic
   must salvage a live kernel rather than discard the whole idea.

## Step 1 - Resolve the problem

Two invocation paths:

- **With an argument** (`/imagination <problem statement>`): use the statement as given.
- **Without an argument** (mid-session): derive the problem from the current
  conversation and project. This is the primary path - the user is stuck on
  something right now and does not want to restate it.

If it is genuinely ambiguous which problem is meant, ask - in plain
conversational text, one question, no option menus. Do not ask if a reasonable
reading exists.

## Step 2 - Distill the problem brief

Write this yourself. Do not delegate it. Roughly 200 words, containing exactly:

- what the thing is
- who uses it and why
- the friction or the goal
- hard constraints (platform, budget class, physics, regulation) - constraints
  sharpen creativity and must be included

Explicitly exclude: current implementation details, existing features, what has
already been tried, tech-stack specifics beyond hard constraints, and any
candidate solutions the user already mentioned.

This brief is the only project information any generator will ever receive.

### Also write the ALREADY OBVIOUS list

Alongside the brief, write 3-8 short lines naming **the answers that already
exist or that any competent team reaches in the first twenty minutes of this
specific problem.** Include whatever the user already told you they have.

This is the single highest-value input to the whole tool. The generic ban list
in the worker prompt (gamification, chatbots, dashboards) bans nothing in most
domains - it is a list of *someone else's* clichés. A problem-specific list is
what actually forces a generator off the obvious path, and it gives the critic a
real yardstick instead of its own guess at what a competent team would say.

Write them as plain claims, not categories: "a bigger fire lights a bigger
circle" beats "size-based mechanics". If the user's own request already named
exclusions, those go in verbatim and first.

Both the brief and this list go to every generator. The list also goes to the
critic as its obviousness benchmark.

## Step 3 - Sample seeds with real RNG

`seeds.txt` sits beside this file in the skill directory. Resolve its path first
(it will be under `~/.claude/skills/imagination/`, or a project's
`.claude/skills/imagination/`, or wherever this skill was installed).

Wave shapes. `--n` counts *ideas*, never workers:

| Mode | Workers | Collisions each | Ideas |
|---|---|---|---|
| default | 4 | 3 | 12 |
| `--deep` | 8 | 3 | 24 |
| `--n <k>` | ceil(k/3) | 3, last worker takes the remainder | k |

Draw `2 x IDEAS` seeds - a primary and a secondary for every collision, so 24
for a default wave and 48 for `--deep`:

```bash
shuf -n $((2*IDEAS)) /path/to/seeds.txt
```

If `shuf` is unavailable (macOS without coreutils):

```bash
awk -v seed="${RANDOM:-$$}" 'BEGIN{srand(seed)} {print rand()}' /path/to/seeds.txt | paste - /path/to/seeds.txt | sort -n | head -n $((2*IDEAS)) | cut -f2-
```

Seed `srand` explicitly as shown. A bare `srand()` takes the clock at
one-second granularity, so two fallback draws inside the same second return the
*same* seeds - which looks like working randomness and is not.

**Do not "simplify" that back to the awk one-liner that prints the whole line
via a dollar-sign-zero field reference.** Some harnesses substitute
dollar-sign-digit tokens inside a skill file with the invocation's own arguments
before you ever read it - turning that command into one that silently prints
blank lines. The `paste` form exists so that no dollar-sign-digit token appears
anywhere in this file, including in this warning. (Claude Code does exactly
this; measured 2026-08-13.)

**Then check what you drew.** Confirm the command actually printed `2 x IDEAS`
non-empty lines of seed text before going on - count them. A sampler that
silently returns nothing is the one failure that breaks principle 1 while still
producing plausible output, because the next thing a model does with an empty
seed list is invent one. If the draw comes back short or empty, fix the command.
Never fill the gap yourself.

Pair them off in order: collision *i* gets seed *2i* as primary and seed *2i+1*
as secondary. Then deal the collisions to workers in blocks of three - worker 1
takes collisions 1-3, worker 2 takes 4-6, and so on. Never pick seeds by reading
the file and choosing; that defeats the entire mechanism.

## Step 4 - Spawn the workers in parallel

All workers in a single message so they run concurrently. Each is a subagent
with `model: haiku` (fall back silently to the session model if the override is
unsupported). Give workers **no tools** - they must not explore anything.
Blindness plus the brief is the design.

If the harness cannot spawn a subagent with its tool list emptied, the
`Use NO tools; answer directly` line in the prompt below is what enforces it.
Keep that line either way - it costs nothing, and it is the only guard when
tools cannot actually be stripped. It does work: measured across 20 workers,
every one reported zero tool calls.

**Each worker carries three collisions, not one.** Cost on this harness is
per-worker and nearly flat, so three ideas out of one worker cost about a third
of three ideas out of three workers. What that buys is a real risk -
*within-worker contamination*, idea 2 quietly riffing on idea 1 - and the
sealed-assignment rules below plus the critic's duplicate test are what contain
it. Do not drop either guard.

Send each worker exactly this, with the placeholders filled:

```
You are one isolated worker among several. The other workers' seeds are
unknown to you. You know nothing about this project except the brief below.
Missing context is a feature - do not ask for more, do not hedge about what
you don't know. Use NO tools; answer directly.

PROBLEM BRIEF:
{brief}

ALREADY OBVIOUS - these answers are taken. Producing any of them, or a
rewording of one, is an automatic failure:
{already_obvious_list}

You will produce THREE ideas in this session, one per seed pair below.
Treat each as a separate, sealed assignment:
- Complete idea 1 fully before looking at seed pair 2, and so on.
- The three ideas must not share a core mechanism and must not reference,
  extend, or riff on each other. If a later idea converges on an earlier
  one's mechanism, discard it and re-derive from its own seed.
- Before writing each idea after the first, restate to yourself the core
  mechanism of every idea you have already written, and confirm the new
  one is not that same mechanism at a different granularity, in a
  different location, or with a different degree of automation. The same
  mechanism in a new wrapper is convergence - discard and re-derive.
- Each idea obeys all rules and the output format independently, separated
  by a line containing only "---".

SEED PAIR 1 (randomly drawn; non-negotiable):
1. {primary_seed_1}
2. {secondary_seed_1}

SEED PAIR 2 (randomly drawn; non-negotiable):
1. {primary_seed_2}
2. {secondary_seed_2}

SEED PAIR 3 (randomly drawn; non-negotiable):
1. {primary_seed_3}
2. {secondary_seed_3}

For each seed pair, produce exactly ONE idea that addresses the brief, where
that idea's core mechanism is structurally borrowed from that pair's seed 1.
That pair's seed 2 is optional garnish.

Rules:
- The borrowing must be mechanical, not metaphorical. "It's like X" is
  failure; "it works the way X works, specifically: ..." is success.
- Litmus test: if your idea would still make sense with seed 1 deleted,
  you have failed. Start over before answering.
- Banned outright: anything on the ALREADY OBVIOUS list above, and any
  idea a competent team would produce in their first 20 minutes of
  ordinary brainstorming. If your domain has no specific list, the usual
  suspects are gamification, an AI assistant/chatbot, a dashboard,
  notifications, social/community features, personalization, theming.
- State, in one clause inside WHY NON-OBVIOUS, which ALREADY OBVIOUS
  entry your idea is most likely to be mistaken for, and why it is not
  that. If you cannot name one, your idea is probably too far from the
  problem to be useful.
- Do not evaluate feasibility. Do not add caveats. Commit to the bit.

Output exactly this per idea, 150 words maximum each, nothing before or
after, with the three ideas separated by a line containing only "---":
IDEA NAME: ...
MECHANISM: how it concretely works
SEED LINK: the structural borrowing, one sentence
WHY NON-OBVIOUS: one sentence

Your output is consumed by a critic program, not a human.
```

A worker handed fewer than three pairs (the remainder worker on some `--n`
values) produces that many ideas - drop the unused pairs and change "THREE" to
match.

## Step 4b - Solo mode, when workers cannot be spawned

Many sessions cannot dispatch subagents - a project rule that keeps exploration
separate from orchestration, a harness limit, a policy against fan-out. **Treat
this as a main path, not an exotic edge case.** The moment someone reaches for
this tool is usually mid-conversation while stuck, which in a lot of workflows is
exactly the mode that forbids dispatching. Expect solo mode to run often.

What is never acceptable is running it undisclosed. **Do not silently run the
pipeline in your own context and report it as a normal wave.** That produces the same
headline number from a materially weaker process, which is the one failure this
tool exists to not commit.

If you cannot spawn workers, run solo mode and say so:

- Draw the seeds exactly as in Step 3. Real RNG is non-negotiable and costs
  nothing here, so principle 1 still holds fully.
- Work one seed pair at a time. **Do not read ahead.** Write each idea out
  completely before looking at the next pair - the sealed-assignment discipline
  applied to yourself, since there is no isolation to enforce it for you.
- Run the critic as a genuinely separate pass over the flattened list, judging
  the ideas as text rather than as things you remember writing.
- Label the result honestly in Step 6: `12 generated in solo mode, 4 survived`,
  followed by one line naming what was weakened - the ideas were not written
  blind, so they can drift toward what the session already knows and converge
  more than isolated workers would.

Solo mode is a legitimate fallback, not a failure. It is only a failure when it
is not disclosed. A user who is told gets to weigh the ideas accordingly; a user
who is not told believes they received something they did not.

## Step 5 - The critic

One subagent, `model: sonnet` (or the session model if that is stronger or the
override is unsupported). **Flatten every worker's ideas into a single numbered
list first.** The critic must not know which worker produced what, so that
convergence gets judged on the merits rather than excused by provenance.

**The critic gets more context than the generators, deliberately.** Principle 2
says solution context drags ideas back to the obvious - that is a fact about
*generation*, not about *judgment*. A blind critic cannot make the single most
valuable kill there is: "you already have this under a different name." So give
the critic the ALREADY OBVIOUS list and, if you have it, a short note on what
already exists or has been tried. It uses that for the obviousness and duplicate
tests only, never to soften a kill on feasibility grounds.

Give it the brief, the ALREADY OBVIOUS list, and the flattened list, then
exactly this:

```
You are the sole gatekeeper for a forced-collision ideation pipeline. You
have {IDEAS} ideas from isolated workers, each forced to build a solution
out of a random concept. Most are chaff of two kinds: (a) SECRETLY OBVIOUS
- a standard idea wearing its seed as costume; (b) NOISE - the collision
produced no working mechanism. Return only the survivors: at most 4, and
fewer if fewer deserve it. An empty result is an acceptable result.

Apply these tests to each idea, in order:
1. OBVIOUSNESS: is this on the ALREADY OBVIOUS list, a rewording of an
   entry on it, or something a competent team would reach in their first
   20 minutes on this specific problem? Kill it. The list is your
   benchmark - use it before your own intuition about what is obvious.
2. COSTUME: mentally delete the seed language. Is what remains a standard
   idea? Kill it.
3. KERNEL: if the idea is incoherent, does one live insight survive? If
   yes, SALVAGE: restate the kernel yourself in 2 sentences or fewer, keep
   it, and mark it [SALVAGED]. Only kill incoherence with no kernel.
4. DUPLICATES: near-identical mechanisms under different seeds - keep
   only the strongest. Ideas generated in the same batch may converge;
   your duplicate test is the backstop - when near-identical mechanisms
   appear, keep only the strongest.

Score surprise and mechanism, never feasibility or polish. Do not pad a
weak wave to reach a count; say the wave was weak instead.

For each survivor output: name; mechanism (tightened by you); why it is
non-obvious, one sentence; and THE FIRST THING THAT WOULD FALSIFY IT -
name the load-bearing assumption and the cheapest test that could kill
the idea, in one sentence. Not a generic first step: the thing that, if
it came out wrong, means do not build this at all.

Then, after the survivors, list every idea you did not keep:

KILLED - one line each, no elaboration:
  <idea name> - (obvious|costume|no-kernel|duplicate): <one short clause>

Every idea you did not keep must appear there exactly once.
```

## Step 6 - Present

Relay the critic's survivors to the user. Add one line giving the wave size and
kill rate, e.g. `12 generated, 3 survived.`

**Print the seed that produced each survivor, beside it.** One line, the seed
text verbatim. This is not decoration: it is the only way the reader can audit
whether the collision actually bound, or whether the seed was worn as costume
and the critic missed it. It also teaches the reader what a productive seed looks
like, which is what makes them able to extend `seeds.txt` themselves.

Then relay the kill log verbatim, under a short heading: `Killed, for the
record`. This is presentation only - it changes nothing about what survives.
It exists because this tool has one systematic blind spot: when the real answer
to a question is correct-but-obvious, the critic kills it on the merits and the
user never learns it was found. A one-line kill entry is the difference between
discarding that answer and showing it.

If fewer than 2 survived, say so plainly - "that wave was weak" - and offer one
re-roll with fresh seeds. **Never pad the list to reach a count.** An honest
weak result is the product working; a padded one is the product broken.

Offer to save the results to a file. Do not write the file unless asked.

## Token discipline

**Cost is per worker and almost flat. Worker count is the only real lever.**
The 150-word cap is for critic legibility, not cost - keep it, but do not
imagine it is saving you anything.

Measured on Claude Code, 2026-08-13, where subagents **cannot** be spawned with
their tool list emptied, so every worker carries a full agent system prompt no
matter how little it writes:

| Wave | Workers | Ideas | Measured total |
|---|---|---|---|
| `--n 8` | 3 | 8 | 183k |
| default | 4 | 12 | 226k, 243k (two runs) |
| `--deep` | 8 | 24 | 424k |

A one-collision worker costs ~37k; a three-collision worker costs ~42k (range
40.1k-43.9k). **Three ideas for 14% more than one** is the whole argument for
batching. The critic runs 62-72k and scales only weakly with idea count.

For comparison, the pre-batch design spent 419k and 442k to produce *ten* ideas.
`--deep` now returns 24 ideas for less than that old default cost.

One honest caveat about `--deep`: it buys more shots on goal, not more
survivors. The critic caps output at 4 regardless, and the 24-idea wave measured
here returned *fewer* survivors (2) than a 12-idea wave (3), because that
problem's solution space was dense with known tactics. Reach for `--deep` when a
default wave came back weak, not to raise the survivor count.

On a harness that can spawn genuinely tool-less subagents the per-worker floor
collapses and batching matters less. Re-measure before assuming either.
