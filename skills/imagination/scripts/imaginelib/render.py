"""Derived views: terminal text, tree.md and tree.html. Never the source of truth;
regenerated from the folded log after every step."""
import json
import os

GLYPH = {"kept": "★", "alive": "●", "pruned": "✕", "pending": "○", "wall": "▪"}


def title(st):
    return (st.problem or {}).get("title", "?")


def headline(n):
    return n.get("display") or n.get("headline") or ""


def batch_summary(st, b):
    ops = sorted({a["operator"] for a in b.plan["assignments"]})
    apples = [st.nodes[a["id"]] for a in (b.prefilter or {}).get("apples", []) if a["id"] in st.nodes]
    alive = sum(1 for a in apples if a["status"] in ("alive", "kept"))
    label = "grow %s" % b.plan["parent"] if b.kind == "grow" else "fresh"
    stage = b.stage()
    tail = "" if stage == "done" else "  [incomplete: next stage %s]" % stage
    return "%s · %s · %d ideas → %d alive · %d pressures%s" % (
        b.id, label, len(apples) or b.plan["n"], alive, len(ops), tail)


def plan_line(ctx_catalog, plan):
    names = {o["id"]: o["name"] for o in ctx_catalog["fresh"] + ctx_catalog["grow"]}
    ops = []
    for a in plan["assignments"]:
        nm = names.get(a["operator"], a["operator"])
        if nm not in ops:
            ops.append(nm)
    seeds = sum(1 for a in plan["assignments"] for s in a["seeds"] if s.get("track"))
    regs = []
    for a in plan["assignments"]:
        if a["register"] not in regs:
            regs.append(a["register"])
    kind = "Grow batch from %s" % plan["parent"] if plan["kind"] == "grow" else "Fresh batch"
    line = "%s %s: %d ideas; pressures %s; %d fresh seeds; tones %s" % (
        kind, plan["batch"], plan["n"], ", ".join(ops), seeds, ", ".join(regs[:4]) + ("…" if len(regs) > 4 else ""))
    if plan.get("banned_motifs"):
        line += "; banned motifs: " + ", ".join(plan["banned_motifs"])
    for c in plan.get("changes", []):
        line += "\n  " + c
    return line


def batch_report(st, bid):
    b = st.batches[bid]
    out = [batch_summary(st, b)]
    apples = [st.nodes[a["id"]] for a in b.prefilter["apples"]]
    alive = [a for a in apples if a["status"] in ("alive", "kept")]
    for a in alive:
        out.append("  %s %-4s %s" % (GLYPH[a["status"]], a["id"], headline(a)))
    if not alive:
        out.append("  (nothing survived)")
    killed = [a for a in apples if a["status"] == "pruned" and a.get("pruned_by") == "critic"]
    dups = [a for a in apples if a.get("pruned_by") == "code"]
    if killed:
        out.append("  killed, for the record:")
        for a in killed:
            out.append("    ✕ %-4s %s  [%s: %s]" % (a["id"], headline(a), a.get("reason"), a.get("note", "")))
    dropped = (b.prefilter or {}).get("dropped", 0)
    if dropped:
        out.append("  %d of %d assignments came back empty from the workers (not padded)." % (dropped, b.plan["n"]))
    if dups:
        out.append("  %d near-copies dropped by code before judging: %s" % (
            len(dups), ", ".join("%s~%s" % (a["id"], a.get("dup_of")) for a in dups)))
    n = len(apples)
    if n and len(alive) < 2:
        out.append("Weak batch: %d of %d survived. Say 'more' for a hard reshuffle." % (len(alive), n))
    if b.verdicts and b.verdicts.get("batch_note"):
        out.append("Critic: " + b.verdicts["batch_note"])
    conv = b.convergence or {}
    m = conv.get("metrics", {})
    n_dec = sum(1 for a in apples if isinstance(a.get("decoy"), dict) and a["decoy"].get("pass") is not None)
    if m.get("decoy_pass_rate") is not None and n_dec >= 4 and m["decoy_pass_rate"] < 0.34:
        out.append("Warning: decoy pass rate %d%% is at chance; seeds look decorative this batch."
                   % round(100 * m["decoy_pass_rate"]))
    if conv.get("message"):
        out.append(conv["message"])
    return out


def lineage(st, aid):
    """Root -> wall it got past -> ancestors -> this -> children, as headlines."""
    n = st.nodes[aid]
    steps = ["? " + title(st)]
    if n["type"] == "wall":
        steps.append("%s %s (wall: %s)" % (aid, n["headline"], n["source"]))
        return steps
    chain = []
    cur = n
    while cur.get("parent"):
        cur = st.nodes[cur["parent"]]
        chain.append(cur)
    chain.reverse()
    first = chain[0] if chain else n
    past = None
    if first.get("nearest") in st.nodes:
        past = st.nodes[first["nearest"]]
    if past is None:
        w = next((s["text"] for s in first.get("seeds", []) if s["role"] == "wall"), None)
        if w:
            steps.append("▪ past: %s" % w)
    else:
        steps.append("%s past %s: %s" % (GLYPH.get(past["status"], "▪"), past["id"], headline(past)))
    for c in chain:
        steps.append("%s %s %s" % (GLYPH[c["status"]], c["id"], headline(c)))
    steps.append("%s %s %s   <- this" % (GLYPH[n["status"]], aid, headline(n)))
    kids = st.children(aid)
    for k in kids:
        steps.append("    ↳ %s %s %s" % (GLYPH[st.nodes[k]["status"]], k, headline(st.nodes[k])))
    return steps


def show_lines(st, aid, names):
    n = st.nodes[aid]
    if n["type"] == "wall":
        return ["%s  %s" % (aid, n["headline"]), "  wall node (%s)" % n["source"]] + ["  " + s for s in lineage(st, aid)]
    out = ["%s  %s" % (aid, headline(n))]
    status = n["status"] + (" (by %s: %s)" % (n.get("pruned_by"), n.get("reason")) if n["status"] == "pruned" else "")
    out.append("  status:    %s%s" % (status, " · grown" if st.children(aid) else ""))
    if n.get("teaser"):
        out.append("  teaser:    " + n["teaser"])
    out.append("  pressure:  %s  (tone: %s)" % (names.get(n["operator"], n["operator"]), n.get("register")))
    for s in n.get("seeds", []):
        out.append("  %-10s %s  [%s]" % (s["role"] + ":", s["text"], s["pool"]))
    out.append("  mechanism: " + n.get("mechanism", ""))
    out.append("  bridge:    " + (n.get("bridge") or ""))
    if n.get("spark"):
        out.append("  spark:     " + n["spark"])
    if n.get("kernel"):
        out.append("  kernel:    " + n["kernel"])
    d = n.get("decoy")
    if isinstance(d, dict):
        if d.get("pass") is None:
            out.append("  decoy:     n/a (%s)" % d.get("why", "no answer"))
        else:
            out.append("  decoy:     %s (blind reader picked %s, answer %s)" % (
                "pass" if d["pass"] else "fail", d.get("picked"), d.get("answer")))
    out.append("  critic:    %s / %s - %s" % (n.get("verdict", "-"), n.get("reason", "-"), n.get("note", "")))
    tags = []
    for k in ("kind", "feasibility"):
        if n.get(k):
            tags.append("%s=%s" % (k, n[k]))
    if n.get("motifs"):
        tags.append("motifs=" + "/".join(n["motifs"]))
    if tags:
        out.append("  tags:      " + "  ".join(tags))
    if n.get("prior_art"):
        out.append("  prior art: " + n["prior_art"])
    if n.get("cf"):
        out.append("  cf:        " + n["cf"])
    flags = (n.get("flags") or []) + (n.get("flags_cap") or [])
    if flags:
        out.append("  flags:     " + ", ".join(flags))
    if n.get("deepen"):
        dp = n["deepen"]
        out.append("  deepened:")
        out.append("    bridge:          " + dp.get("bridge", ""))
        out.append("    prototype first: " + dp.get("prototype_first", ""))
        out.append("    likely wrong:    " + dp.get("likely_wrong", ""))
        if dp.get("prior_art_to_check"):
            out.append("    check for:       " + "; ".join(dp["prior_art_to_check"]))
    out.append("  lineage:")
    out += ["    " + s for s in lineage(st, aid)]
    return out


def list_lines(st, show_all=False):
    out = []
    for bid in st.batch_order:
        b = st.batches[bid]
        out.append(batch_summary(st, b))
        if not b.prefilter:
            continue
        hidden = 0
        for ap in b.prefilter["apples"]:
            a = st.nodes[ap["id"]]
            if a["status"] == "pruned" and not show_all:
                hidden += 1
                continue
            extra = ""
            if a["status"] == "pruned":
                extra = "  [%s%s]" % (a.get("reason"), "" if a.get("pruned_by") != "user" else ": " + (a.get("note") or ""))
            out.append("  %s %-4s %s%s" % (GLYPH[a["status"]], a["id"], headline(a), extra))
        if hidden:
            out.append("  (%d pruned hidden; list --all shows them)" % hidden)
    return out


# ---- tree.md --------------------------------------------------------------------
def tree_md(st, show_all=False):
    lines = ["# %s" % title(st), "", "Glyphs: ★ kept by you · ● alive · ✕ pruned · ▪ wall · ↳ grown", "",
             "? %s" % title(st)]
    lines.append("  ▪ Wall (%d)" % len(st.wall_ids))
    for w in st.wall_ids:
        n = st.nodes[w]
        lines.append("      ▪ %s %s%s" % (w, n["headline"], "" if n["source"] == "obvious" else "  (your attempt)"))

    def emit_batch(b, indent):
        lines.append("%s%s" % (indent, batch_summary(st, b)))
        if not b.prefilter:
            return
        pruned = 0
        for ap in b.prefilter["apples"]:
            a = st.nodes[ap["id"]]
            if a["status"] == "pruned" and not show_all:
                pruned += 1
                continue
            mark = " ↳" if st.children(a["id"]) else ""
            extra = "  [%s]" % a.get("reason") if a["status"] == "pruned" else ""
            lines.append("%s    %s %s %s%s%s" % (indent, GLYPH[a["status"]], a["id"], headline(a), extra, mark))
            for cb in st.batch_order:
                c = st.batches[cb]
                if c.kind == "grow" and c.plan.get("parent") == a["id"]:
                    emit_batch(c, indent + "        ")
        if pruned:
            lines.append("%s    ✕ %d pruned (tree --all)" % (indent, pruned))
    for bid in st.batch_order:
        b = st.batches[bid]
        if b.kind == "fresh":
            emit_batch(b, "  ")
    return "\n".join(lines) + "\n"


# ---- tree.html ----------------------------------------------------------------
def html_data(st, names=None):
    names = names or {}
    nodes = []
    for nid in st.wall_ids + st.apple_ids:
        n = st.nodes[nid]
        keep = {k: n.get(k) for k in ("id", "type", "status", "batch", "parent", "source", "operator",
                                      "register", "seeds", "mechanism", "bridge", "spark", "kernel",
                                      "teaser", "verdict", "reason", "note", "prior_art", "cf", "motifs",
                                      "kind", "feasibility", "nearest", "decoy", "flags", "pruned_by",
                                      "deepen") if n.get(k) is not None}
        keep["headline"] = headline(n)
        keep["lineage"] = lineage(st, nid)
        if n.get("operator"):
            keep["operator"] = names.get(n["operator"], n["operator"])
        nodes.append(keep)
    batches = []
    for bid in st.batch_order:
        b = st.batches[bid]
        batches.append({"id": bid, "kind": b.kind, "parent": b.plan.get("parent"),
                        "summary": batch_summary(st, b),
                        "banned": b.plan.get("banned_motifs", []),
                        "note": (b.verdicts or {}).get("batch_note", ""),
                        "convergence": (b.convergence or {}).get("message", ""),
                        "apples": [a["id"] for a in (b.prefilter or {}).get("apples", [])]})
    return {"title": title(st), "brief": st.brief, "nodes": nodes, "batches": batches}


def tree_html(st, names=None):
    data = json.dumps(html_data(st, names), ensure_ascii=False).replace("</", "<\\/")
    tpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tree_template.html")
    with open(tpl_path, encoding="utf-8") as f:
        tpl = f.read()
    return tpl.replace("/*DATA*/null", data).replace("{{TITLE}}", _esc(title(st)))


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def write_all(d, st, names=None):
    if not st.problem:
        return
    _atomic_write(os.path.join(d, "tree.md"), tree_md(st))
    _atomic_write(os.path.join(d, "tree.html"), tree_html(st, names))
