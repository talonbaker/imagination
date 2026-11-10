"""Prompt builders, output schemas, and the parsers both backends share."""
import json
import re

GEN_SYSTEM = ("You are a component inside a program that helps a stuck human see their "
              "problem from angles they cannot reach. You produce deliberately strange, "
              "committed ideas. You never evaluate feasibility, never add caveats, and "
              "never write anything outside the JSON your output is parsed as.")

JUDGE_SYSTEM = ("You are the critic inside an imagination-helper program. Your job is to "
                "tell real sparks from secretly obvious ideas and from smooth talk. You "
                "score surprise plus a hidden real connection back to the problem, never "
                "polish and never feasibility. You do not tidy strangeness out of ideas. "
                "Your output is parsed by code.")

BANNED_CORES = ("gamification, points or badges, an AI assistant or chatbot, a dashboard, "
                "notifications or reminders, a social feed or community, personalization, theming")

# ---- schemas --------------------------------------------------------------
IDEAS_SCHEMA = {
    "type": "object",
    "properties": {"ideas": {"type": "array", "items": {
        "type": "object",
        "properties": {"slot": {"type": "integer"}, "headline": {"type": "string"},
                       "mechanism": {"type": "string"}, "bridge": {"type": "string"}},
        "required": ["slot", "headline", "mechanism", "bridge"]}}},
    "required": ["ideas"]}

WALL_SCHEMA = {"type": "object", "properties": {"answers": {"type": "array", "items": {"type": "string"}}},
               "required": ["answers"]}

DECOY_SCHEMA = {"type": "object", "properties": {"answers": {"type": "array", "items": {
    "type": "object", "properties": {"item": {"type": "integer"}, "pick": {"type": "string"}},
    "required": ["item", "pick"]}}}, "required": ["answers"]}

VERDICT_ITEM = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "verdict": {"type": "string", "enum": ["keep", "salvage", "kill"]},
        "reason": {"type": "string", "enum": ["none", "obvious", "costume", "no-kernel",
                                              "duplicate", "exists", "near-copy"]},
        "note": {"type": "string"}, "prior_art": {"type": "string"}, "cf": {"type": "string"},
        "headline": {"type": "string"}, "teaser": {"type": "string"}, "spark": {"type": "string"},
        "kernel": {"type": "string"},
        "motifs": {"type": "array", "items": {"type": "string"}},
        "kind": {"type": "string"},
        "feasibility": {"type": "string", "enum": ["easy", "hard", "impossible", "unknown"]},
        "nearest": {"type": "string"}},
    "required": ["id", "verdict", "reason", "note", "headline", "teaser", "spark", "motifs",
                 "kind", "feasibility", "nearest"]}

CRITIC_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {"type": "array", "items": VERDICT_ITEM},
        "headline_fixes": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "headline": {"type": "string"}}, "required": ["id", "headline"]}},
        "batch_note": {"type": "string"},
        "converged": {"type": "boolean"}},
    "required": ["verdicts", "batch_note", "converged"]}

DEEPEN_SCHEMA = {"type": "object", "properties": {
    "bridge": {"type": "string"}, "prototype_first": {"type": "string"},
    "likely_wrong": {"type": "string"},
    "prior_art_to_check": {"type": "array", "items": {"type": "string"}}},
    "required": ["bridge", "prototype_first", "likely_wrong", "prior_art_to_check"]}


# ---- parsing (shared by headless and agent paths) ---------------------------
class ParseError(ValueError):
    pass


def extract_json(text):
    """Find the first JSON object in model text (tolerates prose and code fences)."""
    if isinstance(text, (dict, list)):
        return text
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = t.find("{")
    while start != -1:
        depth, instr, esc = 0, False, False
        for i in range(start, len(t)):
            ch = t[i]
            if instr:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    instr = False
            elif ch == '"':
                instr = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = t.find("{", start + 1)
    raise ParseError("no JSON object found")


def parse_ideas(obj, slots):
    obj = extract_json(obj)
    items = obj.get("ideas") if isinstance(obj, dict) else obj
    if not isinstance(items, list):
        raise ParseError("ideas is not a list")
    out = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            slot = int(it.get("slot"))
        except (TypeError, ValueError):
            continue
        if slot not in slots or slot in out:
            continue
        h = str(it.get("headline", "")).strip()
        mech = str(it.get("mechanism", "")).strip()
        if not h or not mech:
            continue
        out[slot] = {"headline": h, "mechanism": mech, "bridge": str(it.get("bridge", "")).strip()}
    if not out:
        raise ParseError("no valid ideas")
    return out


def parse_wall(obj):
    obj = extract_json(obj)
    ans = obj.get("answers") if isinstance(obj, dict) else obj
    ans = [str(a).strip() for a in (ans or []) if str(a).strip()]
    if not ans:
        raise ParseError("no answers")
    return ans


def parse_decoy(obj):
    obj = extract_json(obj)
    out = {}
    for a in obj.get("answers", []):
        try:
            out[int(a["item"])] = str(a["pick"]).strip().upper()[:1]
        except (KeyError, TypeError, ValueError):
            continue
    return out


def parse_critic(obj, ids):
    obj = extract_json(obj)
    vs = {}
    for v in obj.get("verdicts", []):
        if not isinstance(v, dict):
            continue
        vid = str(v.get("id", "")).strip().lower()
        if vid in ids and vid not in vs:
            if v.get("verdict") not in ("keep", "salvage", "kill"):
                v["verdict"] = "kill" if v.get("reason") not in (None, "", "none") else "keep"
            vs[vid] = v
    if not vs:
        raise ParseError("no verdicts for known ids")
    fixes = [f for f in obj.get("headline_fixes", []) or [] if isinstance(f, dict)]
    return vs, fixes, str(obj.get("batch_note", "")).strip(), bool(obj.get("converged", False))


def parse_deepen(obj):
    obj = extract_json(obj)
    if not isinstance(obj, dict) or not obj.get("bridge"):
        raise ParseError("no deepen fields")
    return obj


# ---- prompts --------------------------------------------------------------
def _bullets(items):
    return "\n".join("- " + i for i in items) if items else "- (none)"


def wall_prompt(brief, attempts):
    return ("PROBLEM BRIEF\n%s\n\nList the 10 most obvious answers to this problem: the ones any "
            "competent team would write down in its first twenty minutes, and the ones a search "
            "engine would return. Do not include anything already tried, listed here:\n%s\n\n"
            "Each answer is a headline of at most 8 words. Return JSON: {\"answers\": [..]}."
            % (brief, _bullets(attempts)))


def seed_line(a, op):
    seed = next((s["text"] for s in a["seeds"] if s["role"] == "seed"), "")
    wall = next((s["text"] for s in a["seeds"] if s["role"] == "wall"), "")
    return op["template"].replace("{seed}", seed).replace("{wall}", wall)


def worker_prompt(brief, wall_headlines, banned_motifs, assigns, ops_by_id, grow=None):
    k = len(assigns)
    parts = ["PROBLEM BRIEF\n" + brief]
    parts.append("THE WALL: answers everyone already has. Every idea must get past these. An "
                 "idea that is one of these in disguise is a failure.\n" + _bullets(wall_headlines))
    if banned_motifs:
        parts.append("THEMES ALREADY TAKEN (earlier rounds used these up; do not build on them): "
                     + ", ".join(banned_motifs))
    if grow:
        parts.append("THE SPARK you are growing (the underlying connection that made an earlier "
                     "idea work; it is the seed, not the wording):\n" + grow["spark"])
        parts.append("BANNED SURFACE: the parent idea. Do not restate it, reuse its objects, its "
                     "setting or its words.\n- %s: %s" % (grow["headline"], grow["mechanism"]))
        if grow.get("siblings"):
            parts.append("ALSO BANNED (already grown from this spark):\n" + _bullets(grow["siblings"]))
    parts.append(
        "You have %d sealed assignment%s. Treat each as a separate job:\n"
        "- Finish one before reading the next. The ideas must not share a core mechanism or "
        "refer to each other. Before each idea after the first, restate to yourself the "
        "mechanisms already written; if the new one is the same mechanism at a different size, "
        "place or level of automation, discard it and re-derive from its own assignment.\n"
        "- Each pressure and seed was drawn at random by a program and is non-negotiable. The "
        "idea must be BUILT from it: if the idea would still make sense with the seed deleted, "
        "you failed.\n"
        "- Commit to the bit. Strange, wrong and unbuildable are allowed. Generic is not. Do "
        "not evaluate feasibility or add caveats.\n"
        "- Banned as the core of any idea: %s."
        % (k, "" if k == 1 else "s", BANNED_CORES))
    for a in assigns:
        op = ops_by_id[a["operator"]]
        parts.append("ASSIGNMENT %d - pressure: %s - tone: %s\n%s"
                     % (a["slot"], op["name"], a["register"], seed_line(a, op)))
    parts.append(
        "OUTPUT: JSON {\"ideas\": [...]}, one object per assignment with:\n"
        "- slot: the assignment number\n"
        "- headline: at most 8 words, in the assignment's tone. It must carry the spark alone: "
        "someone skimming it should feel the strangeness with no explanation.\n"
        "- mechanism: at most 60 words, how it concretely works.\n"
        "- bridge: one sentence of the form \"the seed's <specific feature> becomes the idea's "
        "<specific feature>\". Name real parts, not vibes.")
    return "\n\n".join(parts)


def decoy_prompt(items):
    lines = ["Each item below is the mechanism of an idea, with some words masked as ▢. "
             "Exactly one of its three candidate sources was the seed it was built from. Pick "
             "it by structure (how the parts relate, what causes what), not by vocabulary. If "
             "none fits, still pick the closest.\n"]
    for it in items:
        lines.append("ITEM %d\nMECHANISM: %s\nA: %s\nB: %s\nC: %s\n"
                     % (it["item"], it["masked"], it["choices"][0], it["choices"][1], it["choices"][2]))
    lines.append("Return JSON {\"answers\": [{\"item\": 1, \"pick\": \"A\"}, ...]} for every item.")
    return "\n".join(lines)


def critic_prompt(brief, wall_lines, cands, kinds, grow=None, fix_queue=None):
    parts = ["PROBLEM BRIEF\n" + brief]
    parts.append("THE WALL: everything the human can already reach - obvious answers, their own "
                 "attempts, and every idea shown in earlier rounds (with what happened to it).\n"
                 + "\n".join(wall_lines))
    if grow:
        parts.append("These candidates were grown from parent %s \"%s\" (spark: %s). Kill any "
                     "near-copy of the parent with reason near-copy." % (grow["id"], grow["headline"], grow["spark"]))
    parts.append("CANDIDATES\n" + "\n\n".join(cands))
    parts.append(
        "Judge every candidate, in order:\n"
        "1. OBVIOUS: would it appear in a competent team's first twenty minutes, or is it on the "
        "wall? kill, reason obvious.\n"
        "2. COSTUME: delete the seed language. Is what remains a standard idea or a wall item? "
        "kill, reason costume; name the plain idea in the note.\n"
        "3. KERNEL: if it is incoherent, does one live insight survive? If yes, salvage and "
        "restate the kernel in kernel (2 sentences max). Kill, reason no-kernel, only when "
        "nothing survives.\n"
        "4. DUPLICATE of another candidate or of a wall item: keep only the strongest; kill the "
        "rest, reason duplicate, nearest = the id it duplicates.\n"
        "5. EXISTS: kill only when this mechanism for this purpose is already a product, game or "
        "practice you can name in prior_art. A resemblance in another domain is NOT a kill: "
        "write it in cf and judge on the merits.\n"
        "Evidence you have: decoy=pass means a blind reader, shown the mechanism with seed words "
        "masked, picked the real seed out of three - a real structural link. decoy=fail means "
        "they could not - suspect costume or smooth talk. flags are code heuristics (smooth = "
        "abstraction words in the bridge; bridge-unanchored = bridge shares no words with the "
        "seed). Evidence, not verdicts.\n"
        "Keep what would knock a stuck person loose: an unexpected idea with a hidden bridge "
        "back to the problem. Absurd, wrong or unbuildable ideas can be keeps. Feasibility is a "
        "tag, never a reason. Never keep to reach a count; an empty keep list is fine.\n\n"
        "For EVERY candidate (kept or killed) return: id; verdict keep|salvage|kill; reason "
        "(none if kept); note (one short clause: why); prior_art and cf (empty if none); "
        "headline (at most 8 words; rewrite only if the worker's headline needs explaining or "
        "is over 8 words; keep it strange - never make it more sensible); teaser (at most 25 "
        "words); spark (one sentence: the underlying connection that makes it work - what "
        "would survive if every noun changed); motifs (1-3 lowercase tags of 1-2 words for its "
        "theme); kind (one of: %s); feasibility easy|hard|impossible|unknown; nearest (id of the "
        "wall item or earlier idea it most resembles, or empty).\n"
        "Then batch_note: one line on whether this batch circles one theme, and converged: "
        "true if it does." % ", ".join(kinds))
    if fix_queue:
        parts.append("ALSO: these earlier headlines broke the 8-word cap. Return a rewrite of each "
                     "in headline_fixes:\n" + "\n".join("%s: %s" % (i, h) for i, h in fix_queue))
    return "\n\n".join(parts)


def deepen_prompt(brief, apple, lineage):
    return ("PROBLEM BRIEF\n%s\n\nThe human kept this idea and wants it opened up. Do not tidy it into "
            "something sensible; explain it as it is.\n\nHEADLINE: %s\nMECHANISM: %s\nPRESSURE: %s\n"
            "SEED: %s\nBRIDGE: %s\nSPARK: %s\nLINEAGE: %s\n\nReturn JSON with: bridge (3-5 sentences "
            "explaining the real connection from seed to idea to problem), prototype_first (the "
            "smallest thing to try this week), likely_wrong (where it is most likely wrong), "
            "prior_art_to_check (things that might already exist; your knowledge is offline and "
            "incomplete, so say what to search for)."
            % (brief, apple.get("display"), apple.get("mechanism"), apple.get("operator"),
               "; ".join(s["text"] for s in apple.get("seeds", [])), apple.get("bridge"),
               apple.get("spark"), lineage))
