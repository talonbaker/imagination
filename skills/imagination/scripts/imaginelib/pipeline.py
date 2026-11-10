"""Batch pipeline: plan -> workers -> prefilter -> decoy -> critic -> show.

Each stage appends one event (workers: one per worker). A batch resumes at the
first stage that has no event, so an interruption loses at most the model call
that was in flight."""
import os
import random
from concurrent.futures import ThreadPoolExecutor

from . import backend as be
from . import checks, compose, prompts, render
from .store import Log, fold


class Ctx:
    def __init__(self, root, slug, prefer="auto", claude_bin=None, out=print,
                 thresholds=None, use_schema=True):
        self.root = root
        self.slug = slug
        self.dir = os.path.join(root, slug)
        os.makedirs(self.dir, exist_ok=True)
        self.log = Log(os.path.join(self.dir, "events.jsonl"))
        self.catalog = compose.load_catalog()
        self.pools = compose.load_pools()
        self.headless = be.Headless(self.dir, claude_bin, use_schema=use_schema)
        self.agent = be.Agent(os.path.join(self.dir, "pending"))
        self.prefer = prefer
        self.out = out
        self.thresholds = thresholds or {}
        self._fell_back = False

    def state(self):
        return fold(self.log.read())

    def path_name(self):
        if self.prefer == "agent" or not self.headless.available() or self._fell_back:
            return "agent"
        return "headless"

    def call(self, key, kind, role, system, prompt, schema, parse):
        if os.path.exists(self.agent.paths(key)[1]) or self.path_name() == "agent":
            return self.agent.call(key, kind, role, system, prompt, schema, parse)
        try:
            return self.headless.call(key, kind, role, system, prompt, schema, parse)
        except be.CallFailed as e:
            if not self._fell_back:
                msg = "Headless call failed (%s); falling back to the agent path." % e
                self.out(msg)
                self.log.append("note", text=msg)
            self._fell_back = True
            return self.agent.call(key, kind, role, system, prompt, schema, parse)

    def render(self):
        render.write_all(self.dir, self.state())


# ---- problem setup ------------------------------------------------------------
def ensure_wall(ctx):
    st = ctx.state()
    if any(st.nodes[w]["source"] == "obvious" for w in st.wall_ids):
        return
    attempts = [st.nodes[w]["headline"] for w in st.wall_ids]
    obj, rec, _ = ctx.call("wall", "wall", "gen", prompts.GEN_SYSTEM,
                           prompts.wall_prompt(st.brief, attempts), prompts.WALL_SCHEMA,
                           prompts.parse_wall)
    n = st.next_wall_num()
    items = []
    for i, h in enumerate(obj[:12]):
        items.append({"id": "w%d" % (n + i), "headline": checks.cap_headline(h)[0], "source": "obvious"})
    ctx.log.append("wall_add", items=items, call=rec)


# ---- stages ---------------------------------------------------------------------
def _ops_by_id(ctx):
    return {o["id"]: o for o in ctx.catalog["fresh"] + ctx.catalog["grow"]}


def _grow_ctx(st, b):
    if b.kind != "grow":
        return None
    p = st.nodes[b.plan["parent"]]
    sibs = [st.nodes[c].get("display") for c in st.children(p["id"]) if st.nodes[c]["batch"] != b.id]
    return {"id": p["id"], "spark": p.get("spark") or p.get("kernel") or p.get("mechanism"),
            "headline": p.get("display"), "mechanism": p.get("mechanism", ""), "siblings": sibs}


def stage_workers(ctx, bid):
    st = ctx.state()
    b = st.batches[bid]
    plan = b.plan
    ops = _ops_by_id(ctx)
    wall = [st.nodes[w]["headline"] for w in st.wall_ids]
    grow = _grow_ctx(st, b)
    by_slot = {a["slot"]: a for a in plan["assignments"]}
    todo = [k for k in range(len(plan["workers"])) if k not in b.ideas]
    pending = []

    def one(k):
        assigns = [by_slot[i + 1] for i in plan["workers"][k]]
        slots = {a["slot"] for a in assigns}
        prompt = prompts.worker_prompt(st.brief, wall, plan.get("banned_motifs"), assigns, ops, grow=grow)
        key = "%s-w%d" % (bid, k + 1)
        try:
            ideas, rec, _ = ctx.call(key, "worker", "gen", prompts.GEN_SYSTEM, prompt,
                                     prompts.IDEAS_SCHEMA, lambda raw: prompts.parse_ideas(raw, slots))
        except be.Pending as p:
            return ("pending", p.keys)
        except (be.CallFailed, prompts.ParseError) as e:
            ctx.log.append("ideas", batch=bid, worker=k, ideas={}, error=str(e))
            return ("failed", str(e))
        ctx.log.append("ideas", batch=bid, worker=k, ideas={str(s): v for s, v in ideas.items()}, call=rec)
        return ("ok", len(ideas))

    if todo:
        with ThreadPoolExecutor(max_workers=len(todo)) as ex:
            results = list(ex.map(one, todo))
        for r in results:
            if r[0] == "pending":
                pending += r[1]
            elif r[0] == "failed":
                ctx.out("A worker failed after retries (%s); continuing without it." % r[1])
    if pending:
        raise be.Pending(pending)


def stage_prefilter(ctx, bid):
    st = ctx.state()
    b = st.batches[bid]
    by_slot = {a["slot"]: a for a in b.plan["assignments"]}
    raw = {}
    for ev in b.ideas.values():
        for s, v in ev.get("ideas", {}).items():
            raw[int(s)] = v
    priors = [{"id": w, "headline": st.nodes[w]["headline"]} for w in st.wall_ids]
    priors += [{"id": a["id"], "headline": a["headline"], "mechanism": a.get("mechanism", "")}
               for a in st.apples()]
    num = st.next_apple_num()
    apples = []
    for slot in sorted(raw):
        v = raw[slot]
        a = by_slot[slot]
        aid = "a%d" % num
        num += 1
        seeds = [s["text"] for s in a["seeds"] if s["role"] == "seed"]
        flags = checks.bridge_flags(v["bridge"], seeds, v["mechanism"])
        h, trimmed = checks.cap_headline(v["headline"])
        if trimmed:
            flags.append("headline-long")
        if checks.word_count(v["mechanism"]) > 90:
            flags.append("mechanism-long")
        cand = {"id": aid, "headline": h, "mechanism": v["mechanism"]}
        dup = checks.near_duplicate(cand, priors)
        apples.append({"id": aid, "slot": slot, "operator": a["operator"], "register": a["register"],
                       "seeds": a["seeds"], "headline": h, "worker_headline": v["headline"],
                       "mechanism": v["mechanism"], "bridge": v["bridge"], "flags": flags,
                       "dup_of": dup, "parent": b.plan.get("parent")})
        priors.append(cand)
    ctx.log.append("prefilter", batch=bid, apples=apples,
                   dropped=len(b.plan["assignments"]) - len(apples))


LETTERS = "ABC"


def stage_decoy(ctx, bid):
    st = ctx.state()
    b = st.batches[bid]
    by_slot = {a["slot"]: a for a in b.plan["assignments"]}
    r = random.SystemRandom()
    items, keymap, results = [], {}, {}
    for ap in b.prefilter["apples"]:
        node = st.nodes[ap["id"]]
        a = by_slot[ap["slot"]]
        seed = next((s["text"] for s in a["seeds"] if s["role"] == "seed"), None)
        if node["status"] == "pruned":
            continue
        if not seed or len(a.get("decoys", [])) < 2:
            results[ap["id"]] = {"pass": None, "why": "no seed pool for this pressure"}
            continue
        choices = [seed] + a["decoys"][:2]
        r.shuffle(choices)
        i = len(items) + 1
        items.append({"item": i, "masked": checks.mask_seed_words(ap["mechanism"], choices),
                      "choices": choices})
        keymap[i] = (ap["id"], LETTERS[choices.index(seed)], choices)
    rec = None
    if items:
        try:
            picks, rec, _ = ctx.call("%s-decoy" % bid, "decoy", "gen", prompts.GEN_SYSTEM,
                                     prompts.decoy_prompt(items), prompts.DECOY_SCHEMA, prompts.parse_decoy)
        except be.CallFailed as e:
            picks = {}
            ctx.out("Decoy test failed (%s); continuing without it." % e)
        for i, (aid, ans, choices) in keymap.items():
            p = picks.get(i)
            results[aid] = {"pass": (p == ans) if p else None, "picked": p, "answer": ans,
                            "choices": choices}
    ctx.log.append("decoy", batch=bid, results=results, call=rec)


def _wall_lines(st, exclude_batch):
    lines = []
    for w in st.wall_ids:
        n = st.nodes[w]
        lines.append("%s: %s [%s]" % (w, n["headline"], "obvious" if n["source"] == "obvious" else "their attempt"))
    for a in st.apples():
        if a["batch"] == exclude_batch:
            continue
        tag = a["status"] if a["status"] != "pruned" else "pruned:%s" % a.get("reason")
        lines.append("%s: %s [%s]" % (a["id"], a.get("display"), tag))
    return lines


def stage_critic(ctx, bid):
    st = ctx.state()
    b = st.batches[bid]
    ops = _ops_by_id(ctx)
    cands, ids = [], []
    for ap in b.prefilter["apples"]:
        node = st.nodes[ap["id"]]
        if node["status"] == "pruned":
            continue
        ids.append(ap["id"])
        seed = "; ".join("%s: %s" % (s["role"], s["text"]) for s in ap["seeds"]) or "(none)"
        d = node.get("decoy") or {}
        dec = "n/a" if d.get("pass") is None else ("pass" if d["pass"] else "fail")
        cands.append("ID %s | pressure: %s | %s\nHEADLINE: %s\nMECHANISM: %s\nBRIDGE: %s\nDECOY: %s | FLAGS: %s"
                     % (ap["id"], ops[ap["operator"]]["name"], seed, ap["headline"], ap["mechanism"],
                        ap["bridge"], dec, ", ".join(ap["flags"]) or "none"))
    grow = _grow_ctx(st, b)
    fixq = [(i, st.nodes[i].get("display")) for i in st.headline_fix_queue if i in st.nodes]
    verdicts, fixes, note, conv, rec = {}, [], "", False, None
    if ids:
        prompt = prompts.critic_prompt(st.brief, _wall_lines(st, bid), cands, ctx.catalog["kinds"],
                                       grow=grow, fix_queue=fixq)
        (verdicts, fixes, note, conv), rec, _ = ctx.call(
            "%s-critic" % bid, "critic", "judge", prompts.JUDGE_SYSTEM, prompt, prompts.CRITIC_SCHEMA,
            lambda raw: prompts.parse_critic(raw, set(ids)))
    out, over = {}, []
    kinds = set(ctx.catalog["kinds"])
    for aid in ids:
        v = dict(verdicts.get(aid) or {"verdict": "keep", "reason": "none",
                                         "note": "the critic returned no verdict; shown unjudged"})
        caps = []
        if not v.get("headline"):
            v["headline"] = st.nodes[aid]["headline"]
        h, t = checks.cap_headline(v["headline"])
        if t:
            caps.append("headline-trimmed")
            over.append(aid)
        v["headline"] = h
        tz, tt = checks.cap_teaser(v.get("teaser", ""))
        if tt:
            caps.append("teaser-trimmed")
        v["teaser"] = tz
        v["motifs"] = [str(m).lower().strip() for m in (v.get("motifs") or [])][:3]
        if v.get("kind") not in kinds:
            v["kind"] = "reframe" if v.get("kind") else "device"
        if v.get("verdict") != "kill":
            v["reason"] = "none"
        if aid not in verdicts:
            caps.append("unjudged")
        v["flags_cap"] = caps
        out[aid] = {k: v.get(k) for k in ("verdict", "reason", "note", "prior_art", "cf", "headline",
                                         "teaser", "spark", "kernel", "motifs", "kind", "feasibility",
                                         "nearest", "flags_cap") if v.get(k) is not None}
    clean_fixes = []
    for f in fixes:
        h, t = checks.cap_headline(f.get("headline", ""))
        if f.get("id") in st.nodes and not t:
            clean_fixes.append({"id": f["id"], "headline": h})
    ctx.log.append("verdicts", batch=bid, verdicts=out, headline_fixes=clean_fixes,
                   batch_note=note, converged=conv, over_cap=over, call=rec)


def stage_show(ctx, bid):
    st = ctx.state()
    b = st.batches[bid]
    apples = [st.nodes[a["id"]] for a in b.prefilter["apples"]]
    prev = []
    for pb in st.last_fresh_batches(3):
        if pb.id != bid and len(prev) < 2 and st.batch_order.index(pb.id) < st.batch_order.index(bid):
            prev.append([st.nodes[a["id"]] for a in pb.prefilter["apples"]])
    res = checks.convergence(apples, prev, critic_flag=bool(b.verdicts.get("converged")),
                             thresholds=ctx.thresholds)
    if b.kind != "fresh":
        res["converging"] = False  # a grown batch is meant to circle its spark
        res["note"] = "grow batch: convergence measured but not acted on"
    if res["converging"]:
        res["message"] = checks.convergence_message(res)
    ctx.log.append("convergence", batch=bid, **res)
    shown = [a["id"] for a in apples if a.get("pruned_by") != "code"]
    ctx.log.append("shown", batch=bid, ids=shown)


STAGES = [("workers", stage_workers), ("prefilter", stage_prefilter), ("decoy", stage_decoy),
          ("critic", stage_critic), ("show", stage_show)]


def advance(ctx, bid):
    """Run the remaining stages of one batch. Raises be.Pending on the agent path."""
    while True:
        st = ctx.state()
        stage = st.batches[bid].stage()
        if stage == "done":
            ctx.render()
            return
        fn = dict(STAGES)[stage]
        fn(ctx, bid)
        ctx.render()


def start_batch(ctx, n, kind="fresh", parent=None, mutate=False, decoy=True):
    st = ctx.state()
    plan = compose.plan_batch(st, ctx.catalog, ctx.pools, n, kind=kind, parent=parent,
                              mutate=mutate, decoy=decoy)
    ctx.log.append("batch_start", **plan)
    return plan


def deepen(ctx, aid, lineage_text):
    st = ctx.state()
    a = st.nodes[aid]
    n = sum(1 for _ in [a.get("deepen")] if _) + 1
    obj, rec, _ = ctx.call("deepen-%s-%d" % (aid, n), "deepen", "judge", prompts.JUDGE_SYSTEM,
                           prompts.deepen_prompt(st.brief, a, lineage_text), prompts.DEEPEN_SCHEMA,
                           prompts.parse_deepen)
    ctx.log.append("deepen", id=aid, detail=obj, call=rec)
    return obj
