#!/usr/bin/env python3
"""A stand-in for `claude -p` used by the offline tests. It reads the prompt from
stdin and returns canned JSON shaped like the real CLI's --output-format json.
FAKE_SLEEP=<secs> delays each call; FAKE_LIMIT=1 simulates a usage-limit error;
FAKE_THEME=<word> makes every idea and motif use that word (forces convergence)."""
import json
import os
import random
import re
import sys
import time

args = sys.argv[1:]
schema = args[args.index("--json-schema") + 1] if "--json-schema" in args else ""
prompt = sys.stdin.read()
if os.environ.get("FAKE_SLEEP"):
    first = re.search(r"ASSIGNMENT (\d+)", prompt)
    # workers sleep in proportion to their first slot, so they finish at different times
    time.sleep(float(os.environ["FAKE_SLEEP"]) * (int(first.group(1)) if first else 1))
if os.environ.get("FAKE_LIMIT"):
    print(json.dumps({"is_error": True, "result": "Claude usage limit reached. Your limit will reset at 5pm."}))
    sys.exit(1)
theme = os.environ.get("FAKE_THEME")
r = random.Random(hash(prompt) & 0xFFFF)
_g = random.Random(7)
WORDS = sorted({"".join(_g.choice("bcdfgklmnprstvz") + _g.choice("aeiou") for _ in range(3))
                for _ in range(600)})


def phrase(k):
    return " ".join(r.choice(WORDS) for _ in range(k))


if '"ideas"' in schema or "ASSIGNMENT" in prompt and '"answers"' not in schema and '"verdicts"' not in schema:
    slots = [int(x) for x in re.findall(r"ASSIGNMENT (\d+)", prompt)]
    obj = {"ideas": [{"slot": s, "headline": (theme + " " if theme else "") + phrase(3).title(),
                      "mechanism": ("%s %s " % (theme, theme) if theme else "") + phrase(14),
                      "bridge": "the seed's %s becomes the idea's %s" % (phrase(1), phrase(1))} for s in slots]}
elif '"verdicts"' in schema or "CANDIDATES" in prompt:
    ids = re.findall(r"^ID (a\d+)", prompt, re.M)
    vs = []
    for i, aid in enumerate(ids):
        kill = i % 3 == 2
        vs.append({"id": aid, "verdict": "kill" if kill else ("salvage" if i % 5 == 4 else "keep"),
                   "reason": "costume" if kill else "none", "note": "a %s in a hat" % phrase(1),
                   "prior_art": "", "cf": "", "headline": phrase(3).title(), "teaser": phrase(10),
                   "spark": "the %s makes the %s do the work" % (phrase(1), phrase(1)),
                   "motifs": [theme] if theme else [phrase(1), phrase(1)], "kind": "device",
                   "feasibility": "hard", "nearest": "w1"})
    obj = {"verdicts": vs, "headline_fixes": [], "batch_note": "varied" if not theme else "all about " + theme,
           "converged": bool(theme)}
elif "ITEM" in prompt:
    items = re.findall(r"^ITEM (\d+)", prompt, re.M)
    obj = {"answers": [{"item": int(i), "pick": r.choice("ABC")} for i in items]}
elif "prototype_first" in schema:
    obj = {"bridge": phrase(20), "prototype_first": phrase(8), "likely_wrong": phrase(8),
           "prior_art_to_check": [phrase(2)]}
else:
    obj = {"answers": [phrase(4).title() for _ in range(10)]}
out = {"type": "result", "is_error": False, "result": json.dumps(obj), "structured_output": obj,
       "usage": {"input_tokens": 2, "cache_creation_input_tokens": 1400 + len(prompt) // 4,
                 "cache_read_input_tokens": 0, "output_tokens": 300}}
print(json.dumps(out))
