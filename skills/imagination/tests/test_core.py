"""Fast tests for the pure-code parts. Run: python3 -m unittest discover -s skills/imagination/tests"""
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)

from imaginelib import checks, compose, prompts  # noqa: E402
from imaginelib.store import Log, fold  # noqa: E402

FAKE = os.path.join(HERE, "fake_claude.py")
IMAGINE = os.path.join(SCRIPTS, "imagine.py")


def run(args, env_extra=None, check=True):
    env = dict(os.environ, IMAGINATION_CLAUDE_BIN=FAKE)
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, IMAGINE] + args, capture_output=True, text=True, env=env)
    if check and p.returncode != 0:
        raise AssertionError(p.stdout + p.stderr)
    return p


class TestPools(unittest.TestCase):
    def test_pools_unique_and_sized(self):
        pools = compose.load_pools()
        for name, items in pools.items():
            dupes = [k for k, v in Counter(items).items() if v > 1]
            self.assertEqual(dupes, [], name)
        self.assertGreaterEqual(len(pools["mechanisms"]), 500)
        self.assertGreaterEqual(len(pools["constraints"]), 120)
        self.assertGreaterEqual(len(pools["lenses"]), 120)
        self.assertGreaterEqual(len(pools["scales"]), 40)
        self.assertGreaterEqual(len(pools["registers"]), 15)

    def test_operator_pools_exist(self):
        cat = compose.load_catalog()
        pools = compose.load_pools()
        for op in cat["fresh"] + cat["grow"]:
            p = op.get("pool")
            self.assertTrue(not p or p in pools or p in compose.DYNAMIC, op["id"])


class TestComposition(unittest.TestCase):
    def setUp(self):
        self.cat = compose.load_catalog()
        self.ops = [o for o in self.cat["fresh"] if o["id"] != "excavation"]

    def test_spread_12(self):
        for _ in range(50):
            ops = compose.compose_operators(12, self.ops, Counter(), random.Random())
            c = Counter(ops)
            self.assertEqual(len(ops), 12)
            self.assertLessEqual(max(c.values()), 2)
            self.assertGreaterEqual(len(c), 5)

    def test_least_used_first(self):
        usage = Counter({o["id"]: 5 for o in self.ops})
        usage["subtraction"] = 0
        usage["inversion"] = 0
        ops = compose.compose_operators(6, self.ops, usage, random.Random())
        self.assertIn("subtraction", ops)
        self.assertIn("inversion", ops)

    def test_avoid_and_force(self):
        ops = compose.compose_operators(12, self.ops, Counter(), random.Random(),
                                        avoid={"collision", "inversion", "subtraction"},
                                        force=["brief_mutation"])
        self.assertNotIn("collision", ops)
        self.assertIn("brief_mutation", ops)

    def test_deal_distinct_within_worker(self):
        for n in (6, 12, 24):
            for _ in range(30):
                ops = compose.compose_operators(n, self.ops, Counter(), random.Random())
                sizes = compose.worker_sizes(n)
                workers = compose.deal(ops, sizes)
                self.assertEqual(sorted(i for w in workers for i in w), list(range(n)))
                for w in workers:
                    wops = [ops[i] for i in w]
                    self.assertEqual(len(wops), len(set(wops)), (n, wops))

    def test_no_seed_reuse_across_batches(self):
        with tempfile.TemporaryDirectory() as d:
            log = Log(os.path.join(d, "events.jsonl"))
            log.append("problem", slug="x", title="x")
            log.append("brief", text="b")
            log.append("wall_add", items=[{"id": "w1", "headline": "obvious thing", "source": "obvious"}])
            pools = compose.load_pools()
            for _ in range(6):
                st = fold(log.read())
                plan = compose.plan_batch(st, self.cat, pools, 24)
                log.append("batch_start", **plan)
            st = fold(log.read())
            self.assertTrue(all(v == 1 for v in st.used_seeds.values()), "a seed was reused")


class TestFoldAndResume(unittest.TestCase):
    def test_stage_progression_and_torn_line(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "events.jsonl")
            log = Log(path)
            log.append("problem", slug="x", title="x")
            log.append("batch_start", batch="b1", kind="fresh", n=2, workers=[[0], [1]], decoy=False,
                       assignments=[{"slot": 1, "operator": "collision", "register": "r", "seeds": []},
                                    {"slot": 2, "operator": "inversion", "register": "r", "seeds": []}])
            self.assertEqual(fold(log.read()).batches["b1"].stage(), "workers")
            log.append("ideas", batch="b1", worker=0, ideas={"1": {"headline": "h", "mechanism": "m", "bridge": ""}})
            with open(path, "a") as f:
                f.write('{"t": "ideas", "batch": "b1", "wor')  # torn write
            st = fold(log.read())
            self.assertEqual(st.batches["b1"].stage(), "workers")
            self.assertEqual(list(st.batches["b1"].ideas), [0])


class TestChecks(unittest.TestCase):
    def test_near_duplicate(self):
        prior = [{"id": "a1", "headline": "Rent Your Own Shadow",
                  "mechanism": "People rent out their shadow by the hour to strangers who need shade at bus stops."}]
        same = {"id": "a2", "headline": "Shadow Rental Hours",
                "mechanism": "Strangers rent people's shadows by the hour for shade at bus stops."}
        diff = {"id": "a3", "headline": "Queue Becomes Choir",
                "mechanism": "Everyone waiting in line must sing their place number; gaps are audible."}
        self.assertEqual(checks.near_duplicate(same, prior), "a1")
        self.assertIsNone(checks.near_duplicate(diff, prior))

    def test_headline_caps(self):
        h, t = checks.cap_headline("Rent Your Own Shadow")
        self.assertEqual((h, t), ("Rent Your Own Shadow", False))
        h, t = checks.cap_headline("The Mortgage Choir: a bank where every loan is sung aloud weekly forever")
        self.assertTrue(t)
        self.assertLessEqual(len(h.split()), checks.HEADLINE_MAX_WORDS)
        self.assertEqual(h, "The Mortgage Choir")
        long = " ".join(["word"] * 40)
        tz, tt = checks.cap_teaser(long)
        self.assertTrue(tt)
        self.assertLessEqual(len(tz.split()), checks.TEASER_MAX_WORDS)

    def test_smooth_talk_flags(self):
        f = checks.bridge_flags("This mirrors the harmony of the ecosystem.", ["a delta abandons its own channel"], "x")
        self.assertTrue(any(x.startswith("smooth") for x in f))
        self.assertIn("bridge-unanchored", f)
        f = checks.bridge_flags("The seed's abandoned channel becomes the idea's retired queue lane.",
                                ["a delta builds outward then abandons its own channel"], "x")
        self.assertEqual(f, [])

    def test_mask(self):
        m = checks.mask_seed_words("The reef grows on dead skeletons of old tickets.",
                                   ["reefs grow on the skeletons of their own dead"])
        self.assertNotIn("skeleton", m.lower())
        self.assertIn("tickets", m)

    def test_convergence(self):
        mk = lambda i, motif, words: {"id": "a%d" % i, "headline": words, "mechanism": words,
                                      "motifs": [motif], "operator": "collision", "status": "alive"}
        words = ("lantern tide ledger moth furnace orchard pigeon quarry anvil velvet glacier harbor "
                 "thimble saddle comet marrow bellows cinder walrus juniper kettle").split()
        conv = [mk(i, "upkeep/decay", words[i] + " " + words[i + 1]) for i in range(7)] + \
               [mk(10 + i, words[i + 8], words[i + 8] + " " + words[i + 9]) for i in range(5)]
        r = checks.convergence(conv, [])
        self.assertTrue(r["converging"])
        self.assertIn("theme", r["signals"])
        self.assertIn("upkeep", checks.convergence_message(r))
        varied = [mk(i, words[i], words[i] + " " + words[(i + 7) % 21]) for i in range(12)]
        self.assertFalse(checks.convergence(varied, [])["converging"])

    def test_extract_json(self):
        self.assertEqual(prompts.extract_json('sure! ```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(prompts.extract_json('noise {"a": {"b": "}"}} tail'), {"a": {"b": "}"}})
        ideas = prompts.parse_ideas('{"ideas":[{"slot":1,"headline":"H","mechanism":"M","bridge":"B"},'
                                    '{"slot":9,"headline":"x","mechanism":"y","bridge":""}]}', {1, 2})
        self.assertEqual(list(ideas), [1])


class TestEndToEndOffline(unittest.TestCase):
    """Whole pipeline against the fake CLI: start, more, kill/revive, grow, resume."""

    def test_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            run(["start", "--dir", d, "--title", "Offline", "--brief", "b", "--size", "small"])
            p = run(["more", "--dir", d, "--size", "small"])
            self.assertIn("Fresh batch b2", p.stdout)
            run(["kill", "--dir", d, "a1", "too", "cute"])
            run(["revive", "--dir", d, "a1"])
            run(["keep", "--dir", d, "a1"])
            p = run(["grow", "--dir", d, "a1", "--n", "4"])
            self.assertIn("grow a1", p.stdout)
            events = [json.loads(x) for x in open(os.path.join(d, "offline", "events.jsonl"))]
            self.assertTrue(any(e["t"] == "decoy" and e["results"] for e in events))
            # interrupted batch: plan recorded, no workers yet -> resume finishes it
            st = fold(Log(os.path.join(d, "offline", "events.jsonl")).read())
            plan = compose.plan_batch(st, compose.load_catalog(), compose.load_pools(), 6)
            Log(os.path.join(d, "offline", "events.jsonl")).append("batch_start", **plan)
            p = run(["resume", "--dir", d])
            self.assertIn("Resuming %s" % plan["batch"], p.stdout)
            self.assertTrue(os.path.exists(os.path.join(d, "offline", "tree.html")))
            p = run(["more", "--dir", d, "--size", "small"], env_extra={"FAKE_LIMIT": "1"}, check=False)
            self.assertEqual(p.returncode, 4)


if __name__ == "__main__":
    unittest.main()
