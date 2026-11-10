"""Append-only event log and the fold that derives all state from it.

Nothing is ever deleted. Every step appends one JSON line (written, flushed
and fsynced). State is recomputed by folding the whole log, so a crash can
lose at most the line being written, and a torn last line is skipped.
"""
import json
import os
import re
import threading
import time
from collections import Counter

ID_RE = re.compile(r"^[aw]\d+$")


class Log:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()

    def append(self, _t, **data):
        ev = {"t": _t, "ts": round(time.time(), 3)}
        ev.update(data)
        line = json.dumps(ev, ensure_ascii=False)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
        return ev

    def read(self):
        if not os.path.exists(self.path):
            return []
        out = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # torn line from an interrupted write
        return out


def slugify(text, maxwords=6):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words[:maxwords]) or "problem"


class Batch:
    def __init__(self, plan):
        self.id = plan["batch"]
        self.plan = plan
        self.kind = plan.get("kind", "fresh")
        self.ideas = {}          # worker index -> event
        self.prefilter = None
        self.decoy = None
        self.verdicts = None
        self.shown = None
        self.convergence = None

    @property
    def n_workers(self):
        return len(self.plan["workers"])

    def stage(self):
        if len(self.ideas) < self.n_workers:
            return "workers"
        if self.prefilter is None:
            return "prefilter"
        if self.plan.get("decoy", True) and self.decoy is None:
            return "decoy"
        if self.verdicts is None:
            return "critic"
        if self.shown is None:
            return "show"
        return "done"


class State:
    def __init__(self):
        self.problem = None
        self.brief = ""
        self.briefs = []
        self.nodes = {}
        self.wall_ids = []
        self.apple_ids = []
        self.batches = {}
        self.batch_order = []
        self.used_seeds = Counter()   # seed text -> times used
        self.op_usage = Counter()
        self.calls = []               # per model call: dict with usage
        self.notes = []
        self.headline_fix_queue = []
        self.queued = None            # a batch asked for but not started yet

    # ---- helpers -------------------------------------------------------
    def apples(self, statuses=None):
        out = [self.nodes[i] for i in self.apple_ids]
        if statuses:
            out = [a for a in out if a["status"] in statuses]
        return out

    def next_apple_num(self):
        return len(self.apple_ids) + 1

    def next_wall_num(self):
        return len(self.wall_ids) + 1

    def next_batch_id(self):
        return "b%d" % (len(self.batch_order) + 1)

    def last_fresh_batches(self, k, done_only=True):
        out = []
        for bid in reversed(self.batch_order):
            b = self.batches[bid]
            if b.kind != "fresh":
                continue
            if done_only and b.stage() != "done":
                continue
            out.append(b)
            if len(out) == k:
                break
        return out

    def incomplete_batches(self):
        return [self.batches[b] for b in self.batch_order
                if self.batches[b].stage() != "done"]

    def children(self, aid):
        return [i for i in self.apple_ids if self.nodes[i].get("parent") == aid]

    def resolve(self, ident):
        ident = ident.strip().lower()
        return ident if ident in self.nodes else None


def _hist(node, what, **extra):
    h = {"what": what}
    h.update(extra)
    node.setdefault("history", []).append(h)


def fold(events):
    st = State()
    for ev in events:
        t = ev["t"]
        if t == "problem":
            st.problem = {k: ev[k] for k in ("slug", "title") if k in ev}
            st.problem["created"] = ev["ts"]
        elif t == "brief":
            st.brief = ev["text"]
            st.briefs.append(ev["text"])
        elif t == "wall_add":
            for item in ev["items"]:
                node = {"id": item["id"], "type": "wall", "headline": item["headline"],
                        "source": item.get("source", "obvious"), "status": "wall",
                        "batch": None, "parent": None}
                st.nodes[item["id"]] = node
                st.wall_ids.append(item["id"])
            if ev.get("call"):
                st.calls.append(dict(ev["call"], batch=ev.get("batch")))
        elif t == "queued":
            st.queued = ev
        elif t == "batch_start":
            st.queued = None
            b = Batch(ev)
            st.batches[b.id] = b
            st.batch_order.append(b.id)
            for a in ev["assignments"]:
                st.op_usage[a["operator"]] += 1
                for s in a.get("seeds", []):
                    if s.get("track", True):
                        st.used_seeds[s["text"]] += 1
            if ev.get("parent") and ev["parent"] in st.nodes:
                st.nodes[ev["parent"]]["grown"] = True
        elif t == "ideas":
            b = st.batches[ev["batch"]]
            b.ideas[ev["worker"]] = ev
            if ev.get("call"):
                st.calls.append(dict(ev["call"], batch=ev.get("batch")))
        elif t == "prefilter":
            b = st.batches[ev["batch"]]
            b.prefilter = ev
            for ap in ev["apples"]:
                node = dict(ap)
                node["type"] = "apple"
                node["batch"] = b.id
                node.setdefault("parent", b.plan.get("parent"))
                node["display"] = ap["headline"]
                if ap.get("dup_of"):
                    node["status"] = "pruned"
                    node["pruned_by"] = "code"
                    node["reason"] = "duplicate"
                    node["note"] = "near-copy of %s (lexical)" % ap["dup_of"]
                else:
                    node["status"] = "pending"
                _hist(node, "generated", batch=b.id)
                st.nodes[node["id"]] = node
                st.apple_ids.append(node["id"])
        elif t == "decoy":
            b = st.batches[ev["batch"]]
            b.decoy = ev
            for aid, res in ev.get("results", {}).items():
                if aid in st.nodes:
                    st.nodes[aid]["decoy"] = res
            if ev.get("call"):
                st.calls.append(dict(ev["call"], batch=ev.get("batch")))
        elif t == "verdicts":
            b = st.batches[ev["batch"]]
            b.verdicts = ev
            for aid, v in ev.get("verdicts", {}).items():
                node = st.nodes.get(aid)
                if not node:
                    continue
                for k in ("verdict", "reason", "note", "prior_art", "cf", "teaser",
                          "spark", "motifs", "kind", "feasibility", "nearest",
                          "kernel", "flags_cap"):
                    if k in v:
                        node[k] = v[k]
                if v.get("headline"):
                    node["display"] = v["headline"]
                if v.get("verdict") in ("keep", "salvage"):
                    node["status"] = "alive"
                else:
                    node["status"] = "pruned"
                    node["pruned_by"] = "critic"
                _hist(node, "critic", verdict=v.get("verdict"), reason=v.get("reason"))
            for fx in ev.get("headline_fixes", []):
                if fx.get("id") in st.nodes and fx.get("headline"):
                    st.nodes[fx["id"]]["display"] = fx["headline"]
            st.headline_fix_queue = list(ev.get("over_cap", []))
            if ev.get("call"):
                st.calls.append(dict(ev["call"], batch=ev.get("batch")))
        elif t == "shown":
            b = st.batches[ev["batch"]]
            b.shown = ev
            for aid in ev["ids"]:
                if aid in st.nodes:
                    st.nodes[aid]["shown"] = True
        elif t == "convergence":
            st.batches[ev["batch"]].convergence = ev
        elif t in ("user_keep", "user_kill", "user_revive"):
            for aid in ev["ids"]:
                node = st.nodes.get(aid)
                if not node or node["type"] != "apple":
                    continue
                if t == "user_keep":
                    node["status"] = "kept"
                elif t == "user_kill":
                    node["status"] = "pruned"
                    node["pruned_by"] = "user"
                    node["reason"] = "user"
                    node["note"] = ev.get("why") or "killed by you"
                else:
                    node["status"] = "alive"
                    node["revived"] = True
                _hist(node, t, why=ev.get("why"))
        elif t == "deepen":
            node = st.nodes.get(ev["id"])
            if node is not None:
                node["deepen"] = ev["detail"]
            if ev.get("call"):
                st.calls.append(dict(ev["call"], batch=ev.get("batch")))
        elif t == "note":
            st.notes.append(ev["text"])
    return st
