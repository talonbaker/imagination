"""Free, code-only checks: tokens, near-duplicates, smooth-talk heuristics,
headline caps, and the convergence metric. No model calls here."""
import re
from collections import Counter

STOP = set("""a an the and or but if then else of to in on at by for with from into onto
over under up down out off as is are was were be been being it its it's this that these
those there their they them he she his her you your we our us i me my not no nor so than
too very can could will would should may might must do does did done have has had having
each every any all some more most such only own same other just also which who whom what
when where why how about through while because until again once both few here ever
idea ideas user users people person thing things way make makes made get gets use uses
used one two three new like""".split())

SMOOTH_WORDS = ["balance", "harmony", "harmonious", "flow", "flows", "emergent", "emerges",
                "synergy", "synergies", "ecosystem", "mirrors", "mirror", "just like",
                "similar to", "resonates", "resonance", "echoes", "embodies", "essence",
                "holistic", "symbiotic", "organic", "interconnected", "journey", "dance",
                "tapestry", "alchemy", "metaphor", "spirit of", "captures the"]

HEADLINE_MAX_WORDS = 8
HEADLINE_MAX_CHARS = 56
TEASER_MAX_WORDS = 25


def stem(w):
    for suf in ("ings", "ing", "ers", "er", "ies", "ied", "ed", "es", "s", "ly"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokens(text):
    words = re.findall(r"[a-z][a-z'\-]+", (text or "").lower())
    return {stem(w.strip("'-")) for w in words if w not in STOP and len(w) > 2}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def idea_tokens(headline, mechanism):
    return tokens(headline) | tokens(mechanism)


DUP_THRESHOLD = 0.45
HEADLINE_DUP_THRESHOLD = 0.75


def near_duplicate(cand, priors):
    """Return the id of the prior this candidate lexically duplicates, or None.

    cand/priors: dicts with id, headline, mechanism. Wall nodes have only a
    headline, so they are compared on headline alone."""
    ct = idea_tokens(cand["headline"], cand.get("mechanism", ""))
    ch = tokens(cand["headline"])
    best, best_s = None, 0.0
    for p in priors:
        if p.get("mechanism"):
            s = jaccard(ct, idea_tokens(p["headline"], p["mechanism"]))
            if s >= DUP_THRESHOLD and s > best_s:
                best, best_s = p["id"], s
        ph = tokens(p["headline"])
        if len(ch) >= 3 and len(ph) >= 3:
            s = jaccard(ch, ph)
            if s >= HEADLINE_DUP_THRESHOLD and s > best_s:
                best, best_s = p["id"], s
    return best


def bridge_flags(bridge, seed_texts, mechanism):
    """Heuristic flags; evidence for the critic, never a kill."""
    flags = []
    low = (bridge or "").lower()
    hits = [w for w in SMOOTH_WORDS if re.search(r"\b" + re.escape(w) + r"\b", low)]
    if hits:
        flags.append("smooth:" + ",".join(hits[:3]))
    if seed_texts:
        st = set()
        for s in seed_texts:
            st |= tokens(s)
        if st and not (tokens(bridge) & st):
            flags.append("bridge-unanchored")
        mech_words = re.findall(r"[a-z]+", (mechanism or "").lower())
        for s in seed_texts:
            sw = re.findall(r"[a-z]+", s.lower())
            grams = {" ".join(sw[i:i + 5]) for i in range(max(0, len(sw) - 4))}
            mtext = " ".join(mech_words)
            if any(g and g in mtext for g in grams):
                flags.append("seed-quoted")
                break
    if not (bridge or "").strip():
        flags.append("no-bridge")
    return flags


def word_count(s):
    return len((s or "").split())


def cap_headline(h):
    """Return (headline, trimmed_flag). Trim at the first clause break, then by words."""
    h = " ".join((h or "").split()).strip(" .")
    if word_count(h) <= HEADLINE_MAX_WORDS and len(h) <= HEADLINE_MAX_CHARS:
        return h, False
    first = re.split(r"\s*[:;,(\u2014]\s*|\s+-\s+|(?<=[.!?])\s+", h)[0].strip(" .")
    if 3 <= word_count(first) <= HEADLINE_MAX_WORDS and len(first) <= HEADLINE_MAX_CHARS:
        return first, True
    words = h.split()[:HEADLINE_MAX_WORDS]
    while words and len(" ".join(words)) > HEADLINE_MAX_CHARS:
        words.pop()
    return " ".join(words), True


def cap_teaser(t):
    t = " ".join((t or "").split())
    w = t.split()
    if len(w) <= TEASER_MAX_WORDS:
        return t, False
    return " ".join(w[:TEASER_MAX_WORDS]).rstrip(",;:") + "…", True


def mask_seed_words(mechanism, seed_texts):
    """Mask every content word the mechanism shares with any candidate seed, so the
    decoy test measures structure, not vocabulary."""
    banned = set()
    for s in seed_texts:
        banned |= tokens(s)

    def repl(m):
        w = m.group(0)
        return "▢" if stem(w.lower()) in banned and w.lower() not in STOP else w
    return re.sub(r"[A-Za-z][A-Za-z'\-]+", repl, mechanism or "")


# ---- convergence -------------------------------------------------------
THRESHOLDS = {
    "theme_share": 0.5,      # share of ideas sharing one motif token
    "cluster_share": 0.4,    # share of ideas in the largest lexical cluster
    "prev_overlap": 0.67,    # share of this batch's recurring themes seen in the last two batches
    "dup_rate": 0.3,         # share of ideas pruned by code as duplicates
    "kind_share": 0.7,       # share of judged ideas of one kind (device, ritual, ...)
    "kind_min": 4,           # ... and at least this many of them
    "cluster_link": 0.22,    # jaccard that links two ideas into a cluster
    "min_ideas": 5,
}


def motif_tokens(motifs):
    out = set()
    for m in motifs or []:
        out |= tokens(m.replace("/", " "))
    return out


def theme_counts(apples):
    c = Counter()
    for a in apples:
        for tok in motif_tokens(a.get("motifs")):
            c[tok] += 1
    return c


def theme_label(apples, tok):
    labels = Counter()
    for a in apples:
        for m in a.get("motifs") or []:
            if tok in motif_tokens([m]):
                labels[m.lower()] += 1
    return labels.most_common(1)[0][0] if labels else tok


def largest_cluster(apples, link):
    toks = [idea_tokens(a.get("headline", ""), a.get("mechanism", "")) for a in apples]
    n = len(toks)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            if jaccard(toks[i], toks[j]) >= link:
                parent[find(i)] = find(j)
    sizes = Counter(find(i) for i in range(n))
    return max(sizes.values()) if sizes else 0


def convergence(batch_apples, prev_batches_apples, critic_flag=False, thresholds=None):
    """batch_apples: all apples of this batch (incl. code-pruned).
    prev_batches_apples: list of apple lists for up to two previous fresh batches.
    Returns a dict of metrics, the triggered signals, and the themes to ban."""
    th = dict(THRESHOLDS)
    th.update(thresholds or {})
    n = len(batch_apples)
    judged = [a for a in batch_apples if a.get("motifs")]
    m = {"n": n}
    signals = []
    tc = theme_counts(judged)
    top_tok, top_n = (tc.most_common(1)[0] if tc else (None, 0))
    m["theme_share"] = round(top_n / len(judged), 2) if judged else 0.0
    m["top_theme"] = theme_label(judged, top_tok) if top_tok else None
    m["top_theme_n"] = top_n
    recurring = {t for t, c in tc.items() if c >= 2}
    prev = Counter()
    for pb in prev_batches_apples:
        prev.update(theme_counts([a for a in pb if a.get("motifs")]))
    prev_rec = {t for t, c in prev.items() if c >= 2}
    m["prev_overlap"] = round(len(recurring & prev_rec) / len(recurring), 2) if recurring else 0.0
    m["cluster_share"] = round(largest_cluster(batch_apples, th["cluster_link"]) / n, 2) if n else 0.0
    dups = sum(1 for a in batch_apples if a.get("pruned_by") == "code")
    m["dup_rate"] = round(dups / n, 2) if n else 0.0
    ops = Counter(a.get("operator") for a in batch_apples)
    m["operators_used"] = len(ops)
    kinds = Counter(a.get("kind") for a in judged if a.get("kind"))
    top_kind, top_kind_n = kinds.most_common(1)[0] if kinds else (None, 0)
    m["kind_share"] = round(top_kind_n / len(judged), 2) if judged else 0.0
    m["top_kind"] = top_kind
    alive = sum(1 for a in batch_apples if a.get("status") in ("alive", "kept"))
    m["keep_rate"] = round(alive / n, 2) if n else 0.0
    dec = [a["decoy"]["pass"] for a in batch_apples
           if isinstance(a.get("decoy"), dict) and a["decoy"].get("pass") is not None]
    m["decoy_pass_rate"] = round(sum(dec) / len(dec), 2) if dec else None
    if n >= th["min_ideas"]:
        if judged and m["theme_share"] >= th["theme_share"] and top_n >= 3:
            signals.append("theme")
        if m["cluster_share"] >= th["cluster_share"]:
            signals.append("cluster")
        if len(recurring) >= 2 and m["prev_overlap"] >= th["prev_overlap"]:
            signals.append("repeat")
        if m["dup_rate"] >= th["dup_rate"]:
            signals.append("duplicates")
        if judged and m["kind_share"] >= th["kind_share"] and top_kind_n >= th["kind_min"]:
            signals.append("kind")
    if critic_flag:
        signals.append("critic")
    # the critic's opinion alone is not enough; it needs one measured signal too
    converging = bool([s for s in signals if s != "critic"]) or (
        "critic" in signals and n >= th["min_ideas"] and m["theme_share"] >= th["theme_share"] * 0.75)
    ban = []
    for t, c in tc.most_common(6):
        lab = theme_label(judged, t)
        if c >= 2 and lab not in ban:
            ban.append(lab)
    ban = ban[:4]
    return {"metrics": m, "signals": signals, "converging": converging, "ban": ban}


def convergence_message(res):
    m = res["metrics"]
    parts = []
    if "theme" in res["signals"] or "critic" in res["signals"]:
        parts.append("%d of %d ideas circle '%s'" % (m["top_theme_n"], m["n"], m["top_theme"]))
    if "cluster" in res["signals"]:
        parts.append("%d%% of the batch is one lexical cluster" % round(100 * m["cluster_share"]))
    if "repeat" in res["signals"]:
        parts.append("most recurring themes repeat the last two batches")
    if "kind" in res["signals"]:
        parts.append("%d%% of ideas are the same kind ('%s')" % (round(100 * m["kind_share"]), m["top_kind"]))
    if "duplicates" in res["signals"]:
        parts.append("%d%% were near-copies of earlier ideas" % round(100 * m["dup_rate"]))
    ban = ", ".join(res["ban"][:4]) or "the top themes"
    return ("Convergence: %s. Switching operators and banning %s for the next batch."
            % ("; ".join(parts) or "the batch is circling one theme", ban))
