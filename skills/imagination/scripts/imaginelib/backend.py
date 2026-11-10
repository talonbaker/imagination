"""Two ways to make a model call, one interface.

headless: the script runs `claude -p` itself, lean (no tools, replaced system
          prompt, no session saved). About 1.4k tokens of fixed overhead per call.
agent:    fallback when `claude` is missing or the headless call fails. The
          script writes each prompt to pending/<key>.prompt.md and stops; the
          orchestrating session sends each as a subagent, saves the reply to
          pending/<key>.out, and runs `imagine.py ingest`. Same parsers either way.
"""
import json
import os
import shutil
import subprocess
import time

MODELS = {"gen": os.environ.get("IMAGINATION_GEN_MODEL", "haiku"),
          "judge": os.environ.get("IMAGINATION_JUDGE_MODEL", "sonnet")}

LIMIT_MARKERS = ("usage limit", "rate limit", "limit reached", "quota", "out of credits",
                 "credit balance", "429")


class Pending(Exception):
    """Raised by the agent path: prompts are waiting for the orchestrator."""

    def __init__(self, keys):
        super().__init__("pending: " + ", ".join(keys))
        self.keys = list(keys)


class UsageLimit(Exception):
    pass


class CallFailed(Exception):
    pass


def usage_record(kind, model, u, secs, backend):
    u = u or {}
    rec = {"call": kind, "model": model, "backend": backend,
           "in": u.get("input_tokens", 0), "cache_create": u.get("cache_creation_input_tokens", 0),
           "cache_read": u.get("cache_read_input_tokens", 0), "out": u.get("output_tokens", 0),
           "thinking": (u.get("output_tokens_details") or {}).get("thinking_tokens", 0),
           "secs": round(secs, 1)}
    rec["total"] = rec["in"] + rec["cache_create"] + rec["cache_read"] + rec["out"]
    return rec


class Headless:
    name = "headless"

    def __init__(self, workdir, claude_bin=None, use_schema=True, timeout=420):
        self.bin = claude_bin or os.environ.get("IMAGINATION_CLAUDE_BIN") or shutil.which("claude")
        self.workdir = workdir
        self.use_schema = use_schema
        self.timeout = timeout

    def available(self):
        return bool(self.bin)

    def _run(self, model, system, prompt, schema, env):
        cmd = [self.bin, "-p", "--model", model, "--no-session-persistence", "--tools", "",
               "--strict-mcp-config", "--disable-slash-commands",
               "--system-prompt", system, "--output-format", "json"]
        if schema is not None and self.use_schema:
            cmd += ["--json-schema", json.dumps(schema)]
        return subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              timeout=self.timeout, cwd=self.workdir, env=env)

    def call(self, key, kind, role, system, prompt, schema, parse):
        model = MODELS[role]
        last_err = None
        for attempt in range(3):
            env = dict(os.environ)
            if attempt == 2:
                # Last resort: some setups refuse a nested session. Not needed on the
                # harness this was built on, kept as a cheap retry.
                env.pop("CLAUDECODE", None)
            t0 = time.time()
            try:
                p = self._run(model, system, prompt, schema, env)
            except subprocess.TimeoutExpired:
                last_err = "timeout"
                continue
            secs = time.time() - t0
            out = (p.stdout or "").strip()
            try:
                d = json.loads(out) if out else {}
            except json.JSONDecodeError:
                d = {}
            text = d.get("result") or ""
            blob = (text + " " + (p.stderr or "") + " " + str(d.get("api_error_status") or "")).lower()
            if p.returncode != 0 or d.get("is_error"):
                if any(m in blob for m in LIMIT_MARKERS):
                    raise UsageLimit(blob.strip()[:300])
                last_err = "exit %s: %s" % (p.returncode, blob.strip()[:300])
                continue
            rec = usage_record(kind, model, d.get("usage"), secs, self.name)
            raw = d.get("structured_output") if d.get("structured_output") is not None else text
            try:
                return parse(raw), rec, raw
            except Exception as e:  # noqa: BLE001 - any parse failure gets a retry
                last_err = "parse: %s" % e
                if attempt == 0 and raw is not text and text:
                    try:
                        return parse(text), rec, text
                    except Exception:  # noqa: BLE001
                        pass
                continue
        raise CallFailed(last_err or "unknown failure")


class Agent:
    name = "agent"

    def __init__(self, pending_dir):
        self.dir = pending_dir

    def available(self):
        return True

    def paths(self, key):
        return (os.path.join(self.dir, key + ".prompt.md"), os.path.join(self.dir, key + ".out"))

    def call(self, key, kind, role, system, prompt, schema, parse):
        os.makedirs(self.dir, exist_ok=True)
        pin, pout = self.paths(key)
        if os.path.exists(pout):
            with open(pout, encoding="utf-8") as f:
                raw = f.read()
            obj = parse(raw)  # shared parser; raises if the reply is unusable
            rec = usage_record(kind, "subagent:" + MODELS[role], {}, 0, self.name)
            done = os.path.join(self.dir, "done")
            os.makedirs(done, exist_ok=True)
            for p in (pin, pout):
                if os.path.exists(p):
                    os.replace(p, os.path.join(done, os.path.basename(p)))
            return obj, rec, raw
        with open(pin, "w", encoding="utf-8") as f:
            f.write("<!-- imagination prompt. model: %s. Send everything below the line as the "
                    "subagent's whole task, with no tools. Save its reply verbatim to %s -->\n"
                    "---\n%s\n\n%s\n\nReply with ONLY a JSON value matching this schema, no prose:\n%s\n"
                    % (MODELS[role], os.path.basename(pout), system, prompt, json.dumps(schema)))
        raise Pending([key])
