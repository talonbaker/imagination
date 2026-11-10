"""Randomness and batch composition. All draws use the OS random source and are
recorded in the batch_start event, so a batch can be re-run identically."""
import json
import math
import os
import random
from collections import Counter

from . import checks

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SEEDS_DIR = os.path.join(SKILL_DIR, "seeds")
OPERATORS_PATH = os.path.join(SKILL_DIR, "operators.json")

SIZES = {"small": 6, "medium": 12, "large": 24}
PER_WORKER = 4


def rng():
    return random.SystemRandom()


def load_catalog(path=OPERATORS_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_pool_file(name, seeds_dir=SEEDS_DIR):
    path = os.path.join(seeds_dir, name + ".txt")
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return out


def load_pools(seeds_dir=SEEDS_DIR):
    pools = {}
    for fn in sorted(os.listdir(seeds_dir)):
        if fn.endswith(".txt"):
            pools[fn[:-4]] = load_pool_file(fn[:-4], seeds_dir)
    return pools


def dynamic_pools(state, catalog, parent=None):
    """Pools that come from the problem itself. Reuse is allowed in these."""
    wall = [n["headline"] for n in (state.nodes[i] for i in state.wall_ids)]
    killed = []
    for a in state.apples({"pruned"}):
        if a.get("pruned_by") in ("critic", "user"):
            killed.append(a.get("display") or a["headline"])
    sparks = []
    for a in state.apples({"alive", "kept"}):
        if parent and a["id"] == parent:
            continue
        if a.get("spark") and (a["status"] == "kept" or parent):
            sparks.append(a["spark"])
    return {"wall": wall, "killed": killed, "sparks": sparks,
            "parts": list(catalog.get("parts", []))}


DYNAMIC = ("wall", "killed", "sparks", "parts")


def draw(pool_name, pools, used, r, taken):
    """Draw one seed string. File pools never repeat a string on one problem
    (`used` counts every earlier draw); if a pool is exhausted, the least-used
    string is reused and the draw is marked reused."""
    items = pools.get(pool_name) or []
    if not items:
        return None
    if pool_name in DYNAMIC:
        fresh = [s for s in items if s not in taken] or items
        return {"pool": pool_name, "text": r.choice(fresh), "track": False}
    fresh = [s for s in items if used.get(s, 0) == 0 and s not in taken]
    if fresh:
        return {"pool": pool_name, "text": r.choice(fresh), "track": True}
    least = min(used.get(s, 0) for s in items)
    cand = [s for s in items if used.get(s, 0) == least and s not in taken] or items
    return {"pool": pool_name, "text": r.choice(cand), "track": True, "reused": True}


def available_ops(ops, dyn):
    out = []
    for op in ops:
        if all(dyn.get(p) for p in op.get("needs", [])):
            out.append(op)
    return out


def compose_operators(n, ops, usage, r, avoid=(), force=()):
    """Choose n operator ids. Forced operators come first, then the least-used so
    far (random tiebreak). Avoided operators are dropped entirely when the rest can
    still fill the batch with each used at most twice and at least five distinct;
    otherwise they go last. Each operator appears at most ceil(n / k) times, so 12
    ideas over 10 operators uses all 10 and none more than twice."""
    ids = [o["id"] for o in ops]
    forced = [f for f in force if f in ids]
    rest = [i for i in ids if i not in avoid or i in forced]
    if avoid and len(rest) >= min(5, n) and math.ceil(n / len(rest)) <= max(2, math.ceil(n / len(ids))):
        ids = rest
    order = sorted(ids, key=lambda i: (i in avoid, usage.get(i, 0), r.random()))
    order = forced + [i for i in order if i not in forced]
    out = [order[k % len(order)] for k in range(n)]
    r.shuffle(out)
    return out


def worker_sizes(n, per=PER_WORKER):
    w = max(1, math.ceil(n / per))
    base, extra = divmod(n, w)
    return [base + (1 if i < extra else 0) for i in range(w)]


def deal(slot_ops, sizes):
    """Assign slots to workers so no worker gets the same operator twice when
    that is possible. Returns a list of slot-index lists."""
    w = len(sizes)
    workers = [[] for _ in range(w)]
    # Most frequent operators first, spread round-robin across workers.
    idx = sorted(range(len(slot_ops)), key=lambda i: (-slot_ops.count(slot_ops[i]), slot_ops[i]))
    for i in idx:
        op = slot_ops[i]
        choices = [k for k in range(w) if len(workers[k]) < sizes[k]]
        clean = [k for k in choices if op not in (slot_ops[j] for j in workers[k])]
        pick = min(clean or choices, key=lambda k: (len(workers[k]) / sizes[k], k))
        workers[pick].append(i)
    return [sorted(ws) for ws in workers]


def pick_registers(n, registers, last_used, r):
    fresh = [x for x in registers if x not in last_used] or list(registers)
    r.shuffle(fresh)
    out = []
    while len(out) < n:
        out.extend(fresh)
    return out[:n]


def banned_motifs(state, extra=()):
    """Top recurring themes of the last two fresh batches, plus convergence bans."""
    c = {}
    for b in state.last_fresh_batches(2):
        apples = [state.nodes[a["id"]] for a in b.prefilter["apples"]]
        tc = checks.theme_counts([a for a in apples if a.get("motifs")])
        for tok, k in tc.most_common(3):
            if k >= 2:
                c[checks.theme_label(apples, tok)] = 1
        if b.convergence and b.convergence.get("converging"):
            for m in b.convergence.get("ban", []):
                c[m] = 1
    for m in extra:
        c[m] = 1
    return list(c)[:8]


def plan_batch(state, catalog, pools, n, kind="fresh", parent=None, r=None,
               mutate=False, decoy=True):
    """Build the batch_start payload: every random draw for the batch."""
    r = r or rng()
    dyn = dynamic_pools(state, catalog, parent=parent)
    allpools = dict(pools)
    allpools.update(dyn)
    changes = []
    avoid, force = set(), []
    if kind == "grow":
        ops = available_ops(catalog["grow"], dyn)
    else:
        ops = available_ops(catalog["fresh"], dyn)
        last = state.last_fresh_batches(1)
        if last and last[0].convergence and last[0].convergence.get("converging"):
            conv = last[0].convergence
            used_last = Counter(a["operator"] for a in last[0].plan["assignments"])
            force = ["brief_mutation"] + (["excavation"] if dyn.get("killed") else [])
            avoid = {op for op, _ in used_last.most_common() if op not in force}
            avoid = set(sorted(avoid, key=lambda o: -used_last[o])[:3])
            changes.append("tactic change after convergence in %s: avoiding %s, forcing %s"
                           % (last[0].id, ", ".join(sorted(avoid)), ", ".join(force)))
        if mutate:
            force = ["brief_mutation"] + [f for f in force if f != "brief_mutation"]
    slot_ops = compose_operators(n, ops, state.op_usage, r, avoid=avoid, force=force)
    if mutate and kind == "fresh":
        # brief mutation on half the slots
        k = max(1, n // 2)
        idx = list(range(n))
        r.shuffle(idx)
        for i in idx[:k]:
            slot_ops[i] = "brief_mutation"
    op_by_id = {o["id"]: o for o in ops}
    last_regs = set()
    if state.batch_order:
        lb = state.batches[state.batch_order[-1]]
        last_regs = {a.get("register") for a in lb.plan["assignments"]}
    regs = pick_registers(n, allpools.get("registers", ["deadpan-serious"]), last_regs, r)
    taken = set()
    assignments = []
    for i, opid in enumerate(slot_ops):
        op = op_by_id[opid]
        seeds = []
        if op.get("needs") and "wall" in op["needs"]:
            w = draw("wall", allpools, state.used_seeds, r, taken)
            if w:
                w["role"] = "wall"
                seeds.append(w)
        if op.get("pool"):
            s = draw(op["pool"], allpools, state.used_seeds, r, taken)
            if s:
                s["role"] = "seed"
                seeds.append(s)
                taken.add(s["text"])
        a = {"slot": i + 1, "operator": opid, "register": regs[i], "seeds": seeds}
        primary = next((s for s in seeds if s["role"] == "seed"), None)
        if decoy and primary:
            pool_items = [x for x in allpools.get(primary["pool"], []) if x != primary["text"]]
            if len(pool_items) >= 2:
                a["decoys"] = r.sample(pool_items, 2)
        assignments.append(a)
    sizes = worker_sizes(n)
    workers = deal(slot_ops, sizes)
    ban = banned_motifs(state) if kind == "fresh" else []
    reused = sum(1 for a in assignments for s in a["seeds"] if s.get("reused"))
    if reused:
        changes.append("%d seed pool(s) exhausted; least-used seeds reused" % reused)
    return {"batch": state.next_batch_id(), "kind": kind, "parent": parent, "n": n,
            "assignments": assignments, "workers": workers, "banned_motifs": ban,
            "decoy": decoy, "changes": changes, "mutate": bool(mutate)}
