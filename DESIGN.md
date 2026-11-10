# Design notes

## Jargon

- **Apple**: one idea. Stored forever with where it came from. Shown as an id and a
  headline (`a17  Rent Your Own Shadow`).
- **Headline**: at most 8 words (and 56 characters). It has to carry the strangeness
  by itself; everything else sits behind it.
- **Wall**: everything you can already reach. It starts as about ten obvious answers
  (one cheap call per problem) plus anything you said you already tried. Every idea
  ever generated joins it. The judge measures every new idea against the wall.
- **Pressure** (also called an operator): a forcing move applied to the problem, such
  as *collision* (build the idea from a random mechanism), *net removal* (an obvious
  answer is declared impossible for a random absurd reason; solve what is left),
  *subtraction*, *inversion*, *scale shift*, *alien lens*, *literalization*, *brief
  mutation* (restate the problem itself), and *wrong-answer excavation* (what would
  make a killed idea right). Different pressures produce different kinds of ideas.
- **Seed**: the random input a pressure works on, drawn by the operating system's
  random source from a shipped list (`seeds/*.txt`), never chosen by a model.
- **Register**: the tone a headline is written in (deadpan, villainous, bureaucratic,
  nursery rhyme...). Cheap extra variety; it is never the source of the idea.
- **Bridge**: the worker's one-sentence claim of which part of the seed became which
  part of the idea.
- **Spark**: the judge's one sentence naming the underlying connection that makes an
  idea work, the part that would survive if every noun changed. Growing an apple
  starts from its spark, not its wording.
- **Costume**: an ordinary idea dressed in seed language. Delete the seed words and a
  wall item is left. The commonest kill.
- **Decoy test**: a blind reader (a cheap call) sees an idea's mechanism with every
  word it shares with the candidate seeds masked, plus three seeds (the real one and
  two decoys from the same list), and picks which one produced it. Code knows the
  answer. Pass means the seed's structure really shaped the idea; fail suggests the
  bridge was smooth talk.
- **Smooth talk**: a convincing-sounding bridge that connects anything to anything.
- **Motif**: a short tag the judge gives each idea naming its underlying move ("hide
  the number", "move authority"). Used to detect convergence.
- **Kind**: one of a fixed list of idea types (device, ritual, rule-change, role-swap,
  economy, story, place, time-shift, material, game, social-contract, reframe,
  removal).
- **Convergence**: a batch circling one theme. Detected in code from motifs, kinds,
  lexical clusters, repeats of earlier batches and near-copies.
- **Salvage**: the judge keeps an idea that is broken as written because one live
  insight (the kernel) survives; it restates the kernel.
- **Headless call / agent path**: the script calling `claude -p` itself, versus the
  fallback where it writes prompts for the session to send as subagents.
- **Event log**: `events.jsonl`, one JSON line per step, append-only. All state is
  computed by replaying it ("folding").

## Choices and why

1. **The script makes the model calls.** A subagent costs about 40k tokens before it
   writes a word; a lean `claude -p` call costs about 1.4k of overhead. So the
   session that invoked the skill only writes the brief and runs one command, and the
   script does the rest. This also makes unattended runs and resume simple: one long
   command, and a log it can pick up from. Verified here: nested `claude -p` works
   from inside a Claude Code session without unsetting `CLAUDECODE`; the script still
   retries once with it unset on a failure, as a cheap fallback.
2. **Structured output.** `claude -p` has a `--json-schema` flag; with it the model's
   answer arrives already parsed. The same tolerant parser also reads plain-text
   replies, which is what the agent fallback and `--no-schema` use.
3. **Randomness lives in code.** `random.SystemRandom()` draws pressures, seeds,
   registers and decoys; every draw is written into the batch's first event. File
   seeds are never reused on a problem (counted in the log; `status` prints the
   count); if a list runs out, the least-used seed is reused and the batch says so.
4. **Variety in kind, not just count.** A 12-idea batch uses at least 5 pressures and
   none more than twice (all 10 when available); least-used pressures go first, and
   each worker's 3-4 ideas all get different pressures, which also limits one idea
   riffing on the previous one inside a call.
5. **Cheap filters before expensive judgment.** Code checks the schema, caps, lexical
   near-duplicates against every earlier idea, abstraction-word bridges, bridges that
   share no words with their seed, and pasted seed text. Flags are evidence for the
   judge, never kills, except exact-ish duplicates, which are pruned by code and never
   sent to the judge.
6. **One dense judging call per batch.** The judge sees the brief, the whole wall
   (obvious answers, your attempts, every earlier idea and what happened to it), and
   the candidates with their decoy results and flags. It returns a verdict, reason,
   rewritten headline, teaser, spark, motifs, kind, feasibility and nearest wall item
   for every candidate, killed or kept. Killed ideas get sparks too, so you can revive
   and grow them.
7. **"Exists" is narrow.** A kill only when this mechanism for this purpose is a
   product or game the judge can name; a resemblance elsewhere is a `cf` note.
   Feasibility is a tag and never a reason.
8. **"More" is a hard reshuffle by construction.** Fresh seeds, least-used pressures,
   new registers, and the last two batches' recurring motifs passed to workers as
   "themes already taken". Workers are not shown the full list of earlier ideas (it
   would anchor them); the judge is, and kills repeats as duplicates.
9. **Grow uses the spark.** Offspring get the parent's spark as their seed and its
   headline and mechanism as a banned surface, under grow pressures (collide, extremize,
   transplant, merge with another kept spark, invert, concretize). The judge kills
   near-copies of the parent.
10. **Convergence is measured, announced and acted on.** After each fresh batch: share
    of ideas sharing a motif word, share of one kind, largest lexical cluster, overlap
    of recurring themes with the previous two batches, near-copy rate, plus the
    judge's own yes/no. When it trips, the batch prints a plain `Convergence:` line,
    and the next batch avoids the pressures that dominated, forces brief mutation and
    excavation, and bans the themes. Two converging batches in a row with the change
    applied stop an unattended run with a `Stopping:` line.
11. **Never delete.** Kills are status changes with a reason and who made them
    (code, judge, you). `revive` flips them back. Briefs replaced with `rebrief` stay
    in the log.
12. **Headline-first.** Batch output is id + headline, then a one-line-each kill log
    (kept from v1: when the right answer is obvious, this is where you see it). Details
    only via `show`. Caps are enforced in code; an over-long worker headline is shown
    to the judge uncut with a request to rewrite it, and anything still over is trimmed
    at a clause break, flagged, and queued for the next judge call to fix.

## Where it deviates from the build brief

- Workers return only slot, headline, mechanism and bridge; the code already knows
  each slot's pressure and seeds, so the model is not asked to echo them.
- The decoy test masks words shared with any candidate seed, so it tests structure
  rather than vocabulary matching.
- The headline cap is 8 words and 56 characters rather than about 48 characters; at
  48, ordinary eight-word headlines were being cut.
- Motifs turned out too literal to measure convergence ("melting ice", "kitchen") in
  the first runs, so no batch ever registered as converging. The judge is now told to
  tag the underlying move and to reuse tags from a running "themes seen so far" list,
  and a kind-share signal was added. After that, a narrow test problem converged
  naturally on its second batch.
- Grow batches are measured but never trigger a tactic change: circling the parent's
  spark is the point.
- v1's optional second "garnish" seed per idea was dropped: one seed per pressure.
- Extra commands not in the brief: `apply` (runs the HTML tray string), `rebrief`,
  `use`, `more --mutate` (half the batch restates the problem), `--backend`,
  `--thresholds`, `--no-schema`. `ingest` is the same command as `resume`.
- One event kind beyond the brief: `queued` records that a batch was asked for before
  the wall existed, so an interruption between them still resumes into the batch.

## Where it is weakest

- **The judge is lenient.** Across 125 test ideas it kept 45, salvaged 24 and killed
  56 (45%). v1 capped survivors at four. More survivors means more to skim; I left it
  because the spec values spark over correctness, but a stricter keep rule or a cap
  per batch may serve people better.
- **Lexical duplicate detection never fired on real output** (0 of 125). Paraphrased
  duplicates share too few words; the judge caught 20 duplicates itself, which costs
  judgment tokens. The standard library has no semantic similarity tool.
- **The decoy test is weak evidence.** 104 of 123 ideas passed. Failures were killed
  more often (12 of 19, 63%) than passes (43 of 104, 41%), so it carries some signal,
  but with three choices a lucky guess passes a third of the time.
- **Bridge heuristics are noisy.** `bridge-unanchored` fired on 38 of 125, often
  where the bridge paraphrased the seed in different words.
- **Thinking tokens.** About half of each worker's cost is the model's own thinking,
  which no flag I found turns off.
- **Register can leak.** In the first run one worker built its idea from the tone (a
  door-to-door salesman) instead of its seed; the prompt now says the tone is for the
  headline only, and the judge checks the idea came from its listed seed. Some
  register-forced headlines still need explaining ("Little Flight Of Three, Spit It
  Sweetly"), which is against the headline rule.
- **A hard kill leaves calls running.** If the script is killed mid-batch, model
  calls already in flight keep running to completion in the background and spend
  tokens that are not recorded; resume re-runs those workers.
- **Usage-limit detection matches error text.** I could not hit a real limit; it was
  tested with a fake CLI that prints a limit message.
- **The agent fallback** was tested end to end with simulated subagent replies, not
  with real subagents.

## What I would do next

1. Learn from your verdicts: weight future pressure and seed-pool draws toward what
   you keep and away from what you kill, per problem.
2. A stricter, calibrated keep rule (for example at most half a batch, best first).
3. Cheaper duplicate detection that sees meaning, for example a tiny batched
   "which of these are the same move" call on the cheapest model before the judge.
4. Decoy test with five choices and two blind readers, to make it worth trusting.
5. Make headlines a separate cheap pass that sees only the spark, so register never
   shapes the idea and the headline always carries the spark.
