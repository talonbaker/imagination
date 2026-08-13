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
4. **Small N with a hard prompt beats large N with a soft one.** Ten generators,
   not fifty. A strict collision prompt hits roughly one-in-three, which yields
   the target 2-4 survivors without a token spike.
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

## Step 3 - Sample seeds with real RNG

`seeds.txt` sits beside this file in the skill directory. Resolve its path first
(it will be under `~/.claude/skills/imagination/`, or a project's
`.claude/skills/imagination/`, or wherever this skill was installed).

Wave size: default `N=10`. `--deep` sets `N=25`. `--n <k>` sets it explicitly.

Draw `2N` seeds:

```bash
shuf -n $((2*N)) /path/to/seeds.txt
```

If `shuf` is unavailable (macOS without coreutils):

```bash
awk 'BEGIN{srand()} {print rand()"\t"$0}' /path/to/seeds.txt | sort -n | head -n $((2*N)) | cut -f2-
```

Pair them off in order: generator *i* gets seed *2i* as primary and seed *2i+1*
as secondary. Never pick seeds by reading the file and choosing - that defeats
the entire mechanism.

## Step 4 - Spawn N generators in parallel

All `N` in a single message so they run concurrently. Each is a subagent with
`model: haiku` (fall back silently to the session model if the override is
unsupported). Give generators **no tools** - they must not explore anything.
Blindness plus the brief is the design.

If the harness cannot spawn a subagent with its tool list emptied, the
`Use NO tools; answer directly` line in the prompt below is what enforces it.
Keep that line either way - it costs nothing, and it is the only guard when
tools cannot actually be stripped.

Send each generator exactly this, with the placeholders filled:

```
You are one isolated idea generator among several. You know nothing about
this project except the brief below. Missing context is a feature - do not
ask for more, do not hedge about what you don't know. Use NO tools; answer
directly.

PROBLEM BRIEF:
{brief}

YOUR SEEDS (randomly drawn; non-negotiable):
1. {primary_seed}
2. {secondary_seed}

Produce exactly ONE idea that addresses the brief, where the idea's core
mechanism is structurally borrowed from seed 1. Seed 2 is optional garnish.

Rules:
- The borrowing must be mechanical, not metaphorical. "It's like X" is
  failure; "it works the way X works, specifically: ..." is success.
- Litmus test: if your idea would still make sense with seed 1 deleted,
  you have failed. Start over before answering.
- Banned outright: any idea a competent product team would produce in
  their first 20 minutes of ordinary brainstorming - including anything
  centered on gamification, an AI assistant/chatbot, a dashboard,
  notifications, social/community features, personalization, or theming.
- Do not evaluate feasibility. Do not add caveats. Commit to the bit.

Output exactly this, 150 words maximum total, nothing before or after:
IDEA NAME: ...
MECHANISM: how it concretely works
SEED LINK: the structural borrowing, one sentence
WHY NON-OBVIOUS: one sentence

Your output is consumed by a critic program, not a human.
```

## Step 5 - The critic

One subagent, `model: sonnet` (or the session model if that is stronger or the
override is unsupported). Give it the brief plus all `N` raw generator outputs,
and exactly this:

```
You are the sole gatekeeper for a forced-collision ideation pipeline. You
have {N} ideas from isolated generators, each forced to build a solution
out of a random concept. Most are chaff of two kinds: (a) SECRETLY OBVIOUS
- a standard idea wearing its seed as costume; (b) NOISE - the collision
produced no working mechanism. Return only the survivors: at most 4, and
fewer if fewer deserve it. An empty result is an acceptable result.

Apply these tests to each idea, in order:
1. OBVIOUSNESS: would this appear in the first 20 ideas from a competent
   team brainstorming without seeds? Kill it.
2. COSTUME: mentally delete the seed language. Is what remains a standard
   idea? Kill it.
3. KERNEL: if the idea is incoherent, does one live insight survive? If
   yes, SALVAGE: restate the kernel yourself in 2 sentences or fewer, keep
   it, and mark it [SALVAGED]. Only kill incoherence with no kernel.
4. DUPLICATES: near-identical mechanisms under different seeds - keep
   only the strongest.

Score surprise and mechanism, never feasibility or polish. Do not pad a
weak wave to reach a count; say the wave was weak instead.

For each survivor output: name; mechanism (tightened by you); why it is
non-obvious, one sentence; what to prototype first, one sentence.
```

## Step 6 - Present

Relay the critic's survivors to the user. Add one line giving the wave size and
kill rate, e.g. `10 generated, 3 survived.`

If fewer than 2 survived, say so plainly - "that wave was weak" - and offer one
re-roll with fresh seeds. **Never pad the list to reach a count.** An honest
weak result is the product working; a padded one is the product broken.

Offer to save the results to a file. Do not write the file unless asked.

## Token discipline

A default run is 10 short Haiku generations plus one Sonnet critique. The 150
word cap on generator output, more than the agent count, is what keeps it cheap.
Do not raise the cap.
