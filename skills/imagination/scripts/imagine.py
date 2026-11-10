#!/usr/bin/env python3
"""imagination v2 - an imagination helper for a stuck human.

Every command reads and appends to .imagination/<problem>/events.jsonl in the
current directory (override with --dir). Nothing is ever deleted.

  start --title T --brief-file F [--attempt X]...   new problem: wall + first batch
  more [--mutate]                                   hard-reshuffle batch
  run --batches N                                   unattended batches; stops on convergence or limit
  resume | ingest                                   finish anything interrupted / ingest agent replies
  keep IDS | kill IDS [why] | revive IDS            your verdicts
  grow ID [--n K]                                   grow offspring from an apple's spark
  show ID | list [--all] | tree [--all] | status    views (headline-first)
  deepen ID                                         full write-up for one apple (on request only)
  apply "keep a3 a9 ; kill a4 ; grow a7"            run a tray string from tree.html
  rebrief --brief-file F                            replace the brief (old one kept in the log)
  problems | use SLUG                               list problems / switch current problem

Sizes: --size small|medium|large (6 / 12 / 24 ideas) or --n K. --no-decoy skips the
decoy test. --backend headless|agent forces a path (default: auto).
Exit codes: 0 ok, 2 usage error, 3 agent prompts pending, 4 usage limit hit (resume later).
"""
import argparse
import fcntl
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from imaginelib import backend as be  # noqa: E402
from imaginelib import checks, compose, pipeline, render  # noqa: E402
from imaginelib.store import ID_RE, slugify  # noqa: E402


def out(*lines):
    for line in lines:
        print(line, flush=True)


def fail(msg, code=2):
    out("error: " + msg)
    sys.exit(code)


# ---- problem resolution -----------------------------------------------------------
def root_dir(args):
    return os.path.abspath(args.dir or os.environ.get("IMAGINATION_DIR") or os.path.join(os.getcwd(), ".imagination"))


def list_problems(root):
    if not os.path.isdir(root):
        return []
    return sorted(d for d in os.listdir(root) if os.path.exists(os.path.join(root, d, "events.jsonl")))


def current_slug(args, root):
    if getattr(args, "problem", None):
        return args.problem
    cur = os.path.join(root, "CURRENT")
    if os.path.exists(cur):
        s = open(cur, encoding="utf-8").read().strip()
        if s in list_problems(root):
            return s
    probs = list_problems(root)
    if len(probs) == 1:
        return probs[0]
    if not probs:
        fail("no problem yet. Start one: imagine.py start --title \"...\" --brief-file brief.txt")
    fail("several problems exist (%s); pass --problem SLUG or run: imagine.py use SLUG" % ", ".join(probs))


def set_current(root, slug):
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "CURRENT"), "w", encoding="utf-8") as f:
        f.write(slug + "\n")


def parse_thresholds(s):
    th = {}
    for part in (s or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            th[k.strip()] = float(v)
    return th


def make_ctx(args, slug=None):
    root = root_dir(args)
    slug = slug or current_slug(args, root)
    return pipeline.Ctx(root, slug, prefer=args.backend, out=out,
                        thresholds=parse_thresholds(args.thresholds), use_schema=not args.no_schema)


class RunLock:
    def __init__(self, ctx):
        self.path = os.path.join(ctx.dir, "run.lock")

    def __enter__(self):
        self.f = open(self.path, "a+")
        try:
            fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fail("another batch is running on this problem right now; wait for it or check `status`.")
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def size_of(args, default="medium"):
    if getattr(args, "n", None):
        return max(1, min(60, args.n))
    return compose.SIZES[getattr(args, "size", None) or default]


# ---- reporting ----------------------------------------------------------------------
def cost_line(st, bid):
    calls = [c for c in st.calls if c.get("batch") == bid]
    if not calls:
        return None
    by = {}
    for c in calls:
        by.setdefault(c["call"], 0)
        by[c["call"]] += c["total"]
    path = calls[-1].get("backend", "?")
    tot = sum(by.values())
    if path == "agent":
        return "Path: agent (subagents; token use not visible to the script)."
    return "Path: %s · batch tokens %s (%s)" % (
        path, "{:,}".format(tot), ", ".join("%s %s" % (k, "{:,}".format(v)) for k, v in by.items()))


def report_batch(ctx, bid):
    st = ctx.state()
    out(*render.batch_report(st, bid))
    c = cost_line(st, bid)
    if c:
        out(c)


def narrow_space(st):
    """True when the last two fresh batches both converged and the second already had
    a tactic change applied."""
    lb = st.last_fresh_batches(2)
    if len(lb) < 2:
        return False
    a, b = lb[0], lb[1]  # a = latest
    return (bool(a.convergence and a.convergence.get("converging"))
            and bool(b.convergence and b.convergence.get("converging"))
            and any("tactic change" in c for c in a.plan.get("changes", [])))


NARROW_MSG = ("Stopping: two batches in a row converged even after switching tactics. The space looks "
              "narrow under this brief. Options: `more --mutate` (half the batch restates the problem "
              "itself), or rewrite the brief (`rebrief --brief-file F`), or grow a kept apple.")


def handle_pending(ctx, e):
    pdir = ctx.agent.dir
    out("AGENT PATH: %d prompt(s) waiting in %s" % (len(e.keys), pdir))
    for k in e.keys:
        out("  %s.prompt.md  ->  save reply as %s.out" % (k, k))
    out("For each file: spawn a subagent (the model named on its first line, no tools) whose whole task "
        "is the text below the '---' line; save its reply verbatim as the .out file. Send them in parallel. "
        "Then run: imagine.py ingest" + (" --problem %s" % ctx.slug))
    sys.exit(3)


def handle_limit(e):
    out("Stopped: the model call hit a usage limit (%s)." % str(e)[:160],
        "Everything up to the last finished call is saved. When your allowance resets, start a session "
        "and say '/imagination resume'. This skill cannot wake itself up.")
    sys.exit(4)


def run_one_batch(ctx, n, kind="fresh", parent=None, mutate=False, decoy=True):
    plan = pipeline.start_batch(ctx, n, kind=kind, parent=parent, mutate=mutate, decoy=decoy)
    out(render.plan_line(ctx.catalog, plan))
    pipeline.advance(ctx, plan["batch"])
    report_batch(ctx, plan["batch"])
    return plan["batch"]


def with_ctx(args, slug=None):
    ctx = make_ctx(args, slug)
    guarded_ctx[0] = ctx
    return ctx


guarded_ctx = [None]


def protect(fn):
    def wrap(args):
        try:
            return fn(args)
        except be.Pending as e:
            handle_pending(guarded_ctx[0], e)
        except be.UsageLimit as e:
            handle_limit(e)
    return wrap


def finish_incomplete(ctx):
    st = ctx.state()
    inc = st.incomplete_batches()
    for b in inc:
        out("Resuming %s at stage '%s' (finished work is kept, not regenerated)." % (b.id, b.stage()))
        pipeline.advance(ctx, b.id)
        report_batch(ctx, b.id)
    return len(inc)


# ---- commands -------------------------------------------------------------------------
@protect
def cmd_start(args):
    root = root_dir(args)
    if args.brief_file:
        brief = open(args.brief_file, encoding="utf-8").read().strip()
    elif args.brief:
        brief = args.brief.strip()
    else:
        fail("start needs --brief-file F or --brief TEXT")
    slug = args.problem or slugify(args.title)
    existed = slug in list_problems(root)
    ctx = with_ctx(args, slug)
    set_current(root, slug)
    with RunLock(ctx):
        st = ctx.state()
        if existed:
            out("Problem '%s' already exists; resuming it instead of starting over." % slug)
            if brief and brief != st.brief:
                ctx.log.append("brief", text=brief)
                out("The brief you passed differs from the stored one; the new brief is now active (old one kept).")
            if args.attempt:
                n = st.next_wall_num()
                ctx.log.append("wall_add", items=[{"id": "w%d" % (n + i), "headline": checks.cap_headline(a)[0],
                                                   "source": "attempt"} for i, a in enumerate(args.attempt)])
            pipeline.ensure_wall(ctx)
            if not finish_incomplete(ctx):
                out(*render.list_lines(ctx.state()))
                out("Say 'more' for a fresh batch.")
            return
        ctx.log.append("problem", slug=slug, title=args.title)
        ctx.log.append("brief", text=brief)
        if args.attempt:
            ctx.log.append("wall_add", items=[{"id": "w%d" % (i + 1), "headline": checks.cap_headline(a)[0],
                                               "source": "attempt"} for i, a in enumerate(args.attempt)])
        if not args.no_batch:
            ctx.log.append("queued", n=size_of(args), decoy=not args.no_decoy)
        out("Problem: %s  (state in %s)" % (slug, ctx.dir))
        out("Path: %s" % ctx.path_name())
        pipeline.ensure_wall(ctx)
        st = ctx.state()
        out("Wall: %d obvious answers%s." % (sum(1 for w in st.wall_ids if st.nodes[w]["source"] == "obvious"),
                                             " + %d of your attempts" % len(args.attempt) if args.attempt else ""))
        if not args.no_batch:
            run_one_batch(ctx, size_of(args), decoy=not args.no_decoy)
        out("Tree: " + os.path.join(ctx.dir, "tree.html"))


@protect
def cmd_more(args):
    ctx = with_ctx(args)
    with RunLock(ctx):
        finish_incomplete(ctx)
        run_one_batch(ctx, size_of(args), mutate=args.mutate, decoy=not args.no_decoy)
        if narrow_space(ctx.state()):
            out(NARROW_MSG)


@protect
def cmd_run(args):
    ctx = with_ctx(args)
    with RunLock(ctx):
        finish_incomplete(ctx)
        for i in range(args.batches):
            out("--- unattended batch %d of %d ---" % (i + 1, args.batches))
            run_one_batch(ctx, size_of(args), decoy=not args.no_decoy)
            if narrow_space(ctx.state()):
                out(NARROW_MSG)
                return
        out("Unattended run finished. Tree: " + os.path.join(ctx.dir, "tree.html"))


@protect
def cmd_resume(args):
    ctx = with_ctx(args)
    with RunLock(ctx):
        st = ctx.state()
        if not any(st.nodes[w]["source"] == "obvious" for w in st.wall_ids):
            pipeline.ensure_wall(ctx)
        n_done = finish_incomplete(ctx)
        st = ctx.state()
        if st.queued:
            out("Starting the batch that was asked for before the interruption.")
            run_one_batch(ctx, st.queued["n"], decoy=st.queued.get("decoy", True))
            n_done += 1
        if not n_done:
            out("Nothing was interrupted. Current state:")
            out(*render.list_lines(ctx.state()))


def split_ids(tokens):
    ids, why = [], []
    for t in tokens:
        for piece in re.split(r"[,\s]+", t):
            if ID_RE.match(piece.lower()):
                ids.append(piece.lower())
            elif piece:
                why.append(piece)
    return ids, " ".join(why)


def _verdict(args, kind):
    ctx = with_ctx(args)
    st = ctx.state()
    ids, why = split_ids(args.ids)
    good = [i for i in ids if i in st.nodes and st.nodes[i]["type"] == "apple"]
    bad = [i for i in ids if i not in good]
    if bad:
        out("unknown or non-apple ids ignored: " + ", ".join(bad))
    if not good:
        fail("no apple ids given")
    data = {"ids": good}
    if kind == "user_kill" and why:
        data["why"] = why
    ctx.log.append(kind, **data)
    ctx.render()
    st = ctx.state()
    verb = {"user_keep": "kept", "user_kill": "killed", "user_revive": "revived"}[kind]
    for i in good:
        out("%s %s %s %s" % (render.GLYPH[st.nodes[i]["status"]], verb, i, render.headline(st.nodes[i])))


def cmd_keep(args):
    _verdict(args, "user_keep")


def cmd_kill(args):
    _verdict(args, "user_kill")


def cmd_revive(args):
    _verdict(args, "user_revive")


@protect
def cmd_grow(args):
    ctx = with_ctx(args)
    st = ctx.state()
    aid = args.id.lower()
    if aid not in st.nodes or st.nodes[aid]["type"] != "apple":
        fail("unknown apple " + args.id)
    if not (st.nodes[aid].get("spark") or st.nodes[aid].get("kernel")):
        out("note: %s has no critic spark yet; growing from its mechanism instead." % aid)
    with RunLock(ctx):
        finish_incomplete(ctx)
        run_one_batch(ctx, args.n or 6, kind="grow", parent=aid, decoy=not args.no_decoy)


def names(ctx):
    return {o["id"]: o["name"] for o in ctx.catalog["fresh"] + ctx.catalog["grow"]}


def cmd_show(args):
    ctx = with_ctx(args)
    st = ctx.state()
    for raw in args.ids:
        aid = raw.lower()
        if aid not in st.nodes:
            out("unknown id " + raw)
            continue
        out(*render.show_lines(st, aid, names(ctx)))


def cmd_list(args):
    ctx = with_ctx(args)
    st = ctx.state()
    out("%s  (%d apples, %d alive, %d kept)" % (st.problem["title"], len(st.apple_ids),
                                                 len(st.apples({"alive"})), len(st.apples({"kept"}))))
    out(*render.list_lines(st, show_all=args.all))


def cmd_tree(args):
    ctx = with_ctx(args)
    st = ctx.state()
    ctx.render()
    out(render.tree_md(st, show_all=args.all))
    out("HTML tree (read-only; open in a browser): " + os.path.join(ctx.dir, "tree.html"))


def cmd_status(args):
    ctx = with_ctx(args)
    st = ctx.state()
    out("Problem: %s  [%s]" % (st.problem["title"], ctx.slug))
    out("Path: %s  (claude CLI %s)" % (ctx.path_name(), "found" if ctx.headless.available() else "not found"))
    out("Wall: %d  Apples: %d  alive %d  kept %d  pruned %d" % (
        len(st.wall_ids), len(st.apple_ids), len(st.apples({"alive"})), len(st.apples({"kept"})),
        len(st.apples({"pruned"}))))
    for bid in st.batch_order:
        out("  " + render.batch_summary(st, st.batches[bid]))
    inc = st.incomplete_batches()
    if inc:
        out("Interrupted: %s. Run `resume` to finish." % ", ".join("%s (at %s)" % (b.id, b.stage()) for b in inc))
    pend = [f for f in os.listdir(ctx.agent.dir)] if os.path.isdir(ctx.agent.dir) else []
    pend = [f for f in pend if f.endswith(".prompt.md")]
    if pend:
        out("Agent prompts waiting: %d (in %s)" % (len(pend), ctx.agent.dir))
    by = {}
    for c in st.calls:
        k = c["call"]
        by.setdefault(k, [0, 0])
        by[k][0] += 1
        by[k][1] += c["total"]
    if by:
        out("Tokens so far: " + ", ".join("%s %d calls %s" % (k, v[0], "{:,}".format(v[1])) for k, v in by.items())
            + "  = %s" % "{:,}".format(sum(v[1] for v in by.values())))
    used = sum(st.used_seeds.values())
    reused = sum(v - 1 for v in st.used_seeds.values() if v > 1)
    out("Seeds drawn: %d, distinct %d, reused %d" % (used, len(st.used_seeds), reused))


@protect
def cmd_deepen(args):
    ctx = with_ctx(args)
    st = ctx.state()
    aid = args.id.lower()
    if aid not in st.nodes or st.nodes[aid]["type"] != "apple":
        fail("unknown apple " + args.id)
    pipeline.deepen(ctx, aid, " -> ".join(render.lineage(st, aid)))
    ctx.render()
    out(*render.show_lines(ctx.state(), aid, names(ctx)))


def cmd_problems(args):
    root = root_dir(args)
    cur = open(os.path.join(root, "CURRENT")).read().strip() if os.path.exists(os.path.join(root, "CURRENT")) else None
    probs = list_problems(root)
    if not probs:
        out("No problems under " + root)
    for p in probs:
        out("%s %s" % ("*" if p == cur else " ", p))


def cmd_use(args):
    root = root_dir(args)
    if args.slug not in list_problems(root):
        fail("no problem named " + args.slug)
    set_current(root, args.slug)
    out("Current problem: " + args.slug)


def cmd_rebrief(args):
    ctx = with_ctx(args)
    text = open(args.brief_file, encoding="utf-8").read().strip() if args.brief_file else (args.brief or "").strip()
    if not text:
        fail("rebrief needs --brief-file F or --brief TEXT")
    ctx.log.append("brief", text=text)
    out("Brief replaced (the old one stays in the log). The wall stays; say 'more' for a batch under the new brief.")


def cmd_apply(args):
    text = " ".join(args.commands)
    for part in [p.strip() for p in text.split(";") if p.strip()]:
        toks = part.split()
        verb, rest = toks[0].lower(), toks[1:]
        sub = argparse.Namespace(**vars(args))
        if verb in ("keep", "kill", "revive"):
            sub.ids = rest
            {"keep": cmd_keep, "kill": cmd_kill, "revive": cmd_revive}[verb](sub)
        elif verb == "grow":
            for g in rest:
                if ID_RE.match(g.lower()):
                    sub.id, sub.n, sub.no_decoy = g, None, False
                    cmd_grow(sub)
        elif verb == "show":
            sub.ids = rest
            cmd_show(sub)
        else:
            out("skipped unknown command: " + part)


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", help="state root (default ./.imagination)")
    common.add_argument("--problem", help="problem slug (default: current)")
    common.add_argument("--backend", choices=["auto", "headless", "agent"], default="auto")
    common.add_argument("--thresholds", help="convergence thresholds, e.g. theme_share=0.3,cluster_share=0.3")
    common.add_argument("--no-schema", action="store_true", help="do not pass --json-schema to claude -p")
    sizing = argparse.ArgumentParser(add_help=False)
    sizing.add_argument("--size", choices=sorted(compose.SIZES))
    sizing.add_argument("--n", type=int, help="explicit number of ideas")
    sizing.add_argument("--no-decoy", action="store_true", help="skip the decoy test")

    p = argparse.ArgumentParser(prog="imagine.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("start", parents=[common, sizing], help="new problem (or resume if it exists)")
    s.add_argument("--title", required=True)
    s.add_argument("--brief-file")
    s.add_argument("--brief")
    s.add_argument("--attempt", action="append", default=[], help="something already tried (repeatable)")
    s.add_argument("--no-batch", action="store_true", help="only build the wall")
    s.set_defaults(fn=cmd_start)
    s = sp.add_parser("more", parents=[common, sizing], help="hard-reshuffle batch")
    s.add_argument("--mutate", action="store_true", help="half the batch restates the problem")
    s.set_defaults(fn=cmd_more)
    s = sp.add_parser("run", parents=[common, sizing], help="unattended batches")
    s.add_argument("--batches", type=int, default=3)
    s.set_defaults(fn=cmd_run)
    for name in ("resume", "ingest"):
        sp.add_parser(name, parents=[common], help="finish interrupted work / ingest agent replies").set_defaults(fn=cmd_resume)
    for name, fn in (("keep", cmd_keep), ("kill", cmd_kill), ("revive", cmd_revive)):
        s = sp.add_parser(name, parents=[common], help="%s apples by id" % name)
        s.add_argument("ids", nargs="+")
        s.set_defaults(fn=fn)
    s = sp.add_parser("grow", parents=[common, sizing], help="grow offspring from an apple's spark")
    s.add_argument("id")
    s.set_defaults(fn=cmd_grow)
    s = sp.add_parser("show", parents=[common], help="what is behind a headline")
    s.add_argument("ids", nargs="+")
    s.set_defaults(fn=cmd_show)
    s = sp.add_parser("list", parents=[common], help="headlines by batch")
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_list)
    s = sp.add_parser("tree", parents=[common], help="print tree.md, write tree.html")
    s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_tree)
    sp.add_parser("status", parents=[common]).set_defaults(fn=cmd_status)
    s = sp.add_parser("deepen", parents=[common], help="full write-up for one apple")
    s.add_argument("id")
    s.set_defaults(fn=cmd_deepen)
    sp.add_parser("problems", parents=[common]).set_defaults(fn=cmd_problems)
    s = sp.add_parser("use", parents=[common])
    s.add_argument("slug")
    s.set_defaults(fn=cmd_use)
    s = sp.add_parser("rebrief", parents=[common])
    s.add_argument("--brief-file")
    s.add_argument("--brief")
    s.set_defaults(fn=cmd_rebrief)
    s = sp.add_parser("apply", parents=[common], help="run a tray string: 'keep a3 ; kill a4 ; grow a7'")
    s.add_argument("commands", nargs="+")
    s.set_defaults(fn=cmd_apply)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    for attr in ("size", "n", "no_decoy"):
        if not hasattr(args, attr):
            setattr(args, attr, None if attr != "no_decoy" else False)
    try:
        args.fn(args)
    except KeyboardInterrupt:
        out("", "Interrupted. Everything finished before the interruption is saved; run `resume` to finish the batch.")
        sys.exit(130)


if __name__ == "__main__":
    main()
