"""Kimi K3.1 Pro CAD agent: reconstruct, repair, then edit one bracket.

Three phases in one conversation:
  baseline  one request, four images, no tools
  repair    tool loop: execute, inspect, render; at most 3 repairs after the first program that runs
  edit      widen the slot from 6 mm to 9 mm; at most 3 programs (the edit plus 2 corrections)

The hidden reference and the evaluator are never read here.
"""
import base64
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

from cadkit import runner

ROOT = Path(__file__).parent
MODEL = "kimi-k3.1-pro"
EFFORT = "high"                  # fixed for every request in the experiment
MAX_COMPLETION_TOKENS = 32_768   # reasoning plus answer, per request
REPAIR_BUDGET = 3                # repairs after the first program that runs
PRE_RUN_TRIES = 2                # extra tries if the first program does not run
EDIT_BUDGET = 3                  # programs allowed in the edit phase
MAX_REQUESTS = {"repair": 12, "edit": 8}
MIN_GAP_S = 21.0                 # this account allows 3 requests per minute
PRICE = {"input": 2.00, "cache_hit": 0.20, "cache_write_5m": 2.00, "output": 10.00}  # USD per 1M tokens

SYSTEM_PROMPT = """You are a CAD engineer who writes CadQuery 2.8 Python programs.
Rules for every program:
- Units are millimeters.
- Frame: X is the part's width (left to right in the front view), Y is depth with the front of the part toward -Y, and Z is up.
- Place the part so its bounding box is centered on X=0 and Y=0 and its bottom face sits on Z=0.
- `cq` is already imported. Use only cadquery and the math module. Do not read or write files, use the network, or call show_object or any viewer.
- Put every major dimension and feature position in a named variable at the top of the program, so one value changes one feature.
- Build a solid B-rep model, not a mesh.
- Assign the final part, a single solid, to a variable named `result`."""

BASELINE_PROMPT = """These four images show one mechanical part, a bracket. Each view uses orthographic projection, and all four use the same scale. The camera for each view is written at the top of the image, and a small axis triad sits in the lower-left corner.

The overall width of the part along X is 60 mm. No other dimension is given, so estimate the rest from the images.

Write one CadQuery program that rebuilds this part as an editable parametric model. Return the complete program in a single ```python code block."""

REPAIR_PROMPT = """Your program was saved as candidate c0. Execution result: {result}

Now check and improve it with these tools:
- execute_cad(code): run a complete program. Returns a new candidate id and whether it ran.
- inspect_cad(candidate_id): validity, solid count, bounding box, volume, and cylindrical faces of that candidate.
- render_cad(candidate_id): the candidate drawn from the same four cameras, framing, and scale as the reference images.

Compare your candidate with the reference images and fix specific differences by revising your existing program, not by starting over. After the first program that runs, you may execute at most {budget} revised programs. When you are satisfied, or the budget is used up, call submit_cad with the candidate you want to keep."""

EDIT_PROMPT = """Engineering change request, starting from your submitted candidate {cid}:
Increase the width of the vertical slot in the upright plate from 6 mm to 9 mm. Keep the slot's center position and its end-to-end length as they are in your model. Do not change the mounting holes, the plate thickness, or the outer dimensions.

Edit the slot parameter in your existing program instead of rebuilding the part. Use the same tools. You may execute at most {budget} programs for this change (the edit plus corrections), then call submit_cad."""

TOOLS = [
    {"type": "function", "function": {
        "name": "execute_cad",
        "description": "Run a complete CadQuery program in an isolated sandbox. Returns a candidate id, whether it ran, and a short error if it did not.",
        "parameters": {"type": "object", "properties": {
            "code": {"type": "string", "description": "The complete program. It must assign the final solid to `result`."}},
            "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "inspect_cad",
        "description": "Measure a candidate that ran: validity, solid count, bounding box, volume, and cylindrical faces.",
        "parameters": {"type": "object", "properties": {"candidate_id": {"type": "string"}},
                       "required": ["candidate_id"]}}},
    {"type": "function", "function": {
        "name": "render_cad",
        "description": "Render a candidate that ran from the same four cameras, framing, and scale as the reference images.",
        "parameters": {"type": "object", "properties": {"candidate_id": {"type": "string"}},
                       "required": ["candidate_id"]}}},
    {"type": "function", "function": {
        "name": "submit_cad",
        "description": "Finish this phase and keep the given candidate. It must have run and be one valid solid.",
        "parameters": {"type": "object", "properties": {
            "candidate_id": {"type": "string"},
            "summary": {"type": "string", "description": "One or two sentences on what changed and why."}},
            "required": ["candidate_id", "summary"]}}},
]


def image_part(path):
    data = base64.b64encode(Path(path).read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}


def extract_code(text):
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text or "", re.S)
    return blocks[-1].strip() if blocks else None


class Run:
    def __init__(self):
        load_dotenv(find_dotenv(usecwd=True))
        self.client = OpenAI(api_key=os.environ["MOONSHOT_API_KEY"],
                             base_url="https://api.moonshot.ai/v1", timeout=900, max_retries=0)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.dir = ROOT / "runs" / stamp
        self.dir.mkdir(parents=True)
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.candidates = {}
        self.phase = None
        self.last_start = 0.0
        self.log = self.dir / "requests.jsonl"
        self.meta = {"model": MODEL, "reasoning_effort": EFFORT,
                     "max_completion_tokens": MAX_COMPLETION_TOKENS, "started": stamp,
                     "openai_sdk": __import__("openai").__version__,
                     "frozen_hashes": (ROOT / "hidden" / "frozen_hashes.txt").read_text()
                     if (ROOT / "hidden" / "frozen_hashes.txt").exists() else None,
                     "phases": {}}

    # ---- API ---------------------------------------------------------------
    def chat(self, tools=None):
        """One Chat Completions request. Appends the full assistant message to history."""
        for attempt in range(4):
            wait = MIN_GAP_S - (time.time() - self.last_start)
            if wait > 0:
                time.sleep(wait)
            self.last_start = time.time()
            start = time.perf_counter()
            try:
                kwargs = dict(model=MODEL, reasoning_effort=EFFORT,
                              max_completion_tokens=MAX_COMPLETION_TOKENS, messages=self.messages)
                if tools:
                    kwargs["tools"] = tools
                resp = self.client.chat.completions.create(**kwargs)
                break
            except (RateLimitError, APIConnectionError) as exc:
                self._write({"phase": self.phase, "event": "retry", "error": type(exc).__name__,
                             "detail": str(exc)[:300]})
            except APIStatusError as exc:
                if exc.status_code < 500:
                    raise
                self._write({"phase": self.phase, "event": "retry", "error": exc.status_code})
        else:
            raise RuntimeError("request failed after retries")

        seconds = round(time.perf_counter() - start, 2)
        choice = resp.choices[0]
        message = choice.message.model_dump(exclude_none=True)  # keeps reasoning_content and tool_calls
        self.messages.append(message)

        u = resp.usage
        details = u.prompt_tokens_details.model_dump() if u.prompt_tokens_details else {}
        cached = details.get("cached_tokens") or 0
        written = details.get("cache_write_tokens") or 0
        uncached = u.prompt_tokens - cached - written
        reasoning = (u.completion_tokens_details.reasoning_tokens
                     if u.completion_tokens_details else 0) or 0
        cost = (uncached * PRICE["input"] + cached * PRICE["cache_hit"]
                + written * PRICE["cache_write_5m"] + u.completion_tokens * PRICE["output"]) / 1e6
        self._write({"phase": self.phase, "event": "request", "id": resp.id, "seconds": seconds,
                     "finish_reason": choice.finish_reason, "prompt_tokens": u.prompt_tokens,
                     "uncached": uncached, "cached": cached, "cache_write": written,
                     "completion_tokens": u.completion_tokens, "reasoning_tokens": reasoning,
                     "cost_usd": round(cost, 6),
                     "tool_calls": [t["function"]["name"] for t in message.get("tool_calls", [])]})
        return message, choice.finish_reason

    def _write(self, record):
        record["t"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        print(json.dumps(record))

    # ---- Tools (application-defined, run locally) ----------------------------
    def new_candidate(self, code):
        cid = f"c{len(self.candidates)}"
        work = self.dir / "candidates" / cid
        report = runner.execute(code, work)
        self.candidates[cid] = {"id": cid, "phase": self.phase, "dir": str(work), "report": report}
        self._write({"phase": self.phase, "event": "execute", "candidate": cid,
                     "ok": report.get("ok"), "valid": report.get("valid"),
                     "error_type": report.get("error_type"), "seconds": report.get("seconds")})
        return cid, report

    def tool_execute(self, args, state):
        if state["count_all"]:  # edit phase: every program counts
            if state["runs"] >= state["budget"]:
                return json.dumps({"error": f"Budget used up ({state['budget']} programs). "
                                   "Call submit_cad with one of: " + ", ".join(state["ids"])})
        elif state["first_ok"] is not None and state["repairs"] >= state["budget"]:
            return json.dumps({"error": f"Budget used up ({state['budget']} of {state['budget']} repairs). "
                               "Call submit_cad with one of: " + ", ".join(state["ids"])})
        elif state["first_ok"] is None and state["runs"] > PRE_RUN_TRIES:
            return json.dumps({"error": "No program has run within the allowed tries. Call submit_cad."})
        cid, report = self.new_candidate(args.get("code", ""))
        state["ids"].append(cid)
        state["runs"] += 1
        if state["first_ok"] is not None:
            state["repairs"] += 1
        elif report.get("ok"):
            state["first_ok"] = cid
        brief = {k: report[k] for k in ("ok", "error_type", "error", "traceback_tail") if k in report}
        if state["count_all"]:
            left = state["budget"] - state["runs"]
        else:
            left = state["budget"] - state["repairs"] if state["first_ok"] else None
        return json.dumps({"candidate_id": cid, **brief, "programs_left_after_this": left})

    def tool_inspect(self, args):
        cand = self.candidates.get(args.get("candidate_id"))
        if not cand or not cand["report"].get("ok"):
            return json.dumps({"error": "unknown candidate, or it did not run"})
        keys = ("valid", "solids", "bbox_mm", "size_mm", "volume_mm3", "faces", "cylindrical_faces")
        return json.dumps({k: cand["report"][k] for k in keys})

    def tool_render(self, args):
        cand = self.candidates.get(args.get("candidate_id"))
        if not cand or not cand["report"].get("ok"):
            return json.dumps({"error": "unknown candidate, or it did not run"})
        paths = runner.render(cand["dir"])
        parts = [{"type": "text", "text": f"Candidate {cand['id']}, same four cameras as the reference:"}]
        return parts + [image_part(p) for p in paths]

    def tool_submit(self, args, state):
        cand = self.candidates.get(args.get("candidate_id"))
        r = cand["report"] if cand else {}
        if not (r.get("ok") and r.get("valid") and r.get("solids") == 1):
            return json.dumps({"error": "submit a candidate that ran and is one valid solid"}), False
        state["submitted"] = cand["id"]
        state["summary"] = args.get("summary", "")
        return json.dumps({"accepted": cand["id"]}), True

    # ---- Phases --------------------------------------------------------------
    def baseline(self):
        self.phase = "baseline"
        t0 = time.perf_counter()
        images = [image_part(p) for p in sorted((ROOT / "inputs").glob("view*.png"))]
        self.messages.append({"role": "user", "content": images + [{"type": "text", "text": BASELINE_PROMPT}]})
        message, _ = self.chat()
        code = extract_code(message.get("content"))
        cid, report = self.new_candidate(code or "raise ValueError('no code block in the reply')")
        self.meta["phases"]["baseline"] = {"candidate": cid, "seconds": round(time.perf_counter() - t0, 1)}
        return cid, report

    def tool_loop(self, phase, opening, budget, first_ok, count_all=False):
        self.phase = phase
        t0 = time.perf_counter()
        state = {"budget": budget, "repairs": 0, "runs": 0, "first_ok": first_ok, "count_all": count_all,
                 "ids": [first_ok] if first_ok else [], "submitted": None, "summary": None}
        self.messages.append({"role": "user", "content": opening})
        stop = "request cap reached"
        for _ in range(MAX_REQUESTS[phase]):
            message, finish = self.chat(tools=TOOLS)
            calls = message.get("tool_calls") or []
            if not calls:
                stop = f"model replied without a tool call ({finish})"
                break
            done = False
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                if name == "execute_cad":
                    content = self.tool_execute(args, state)
                elif name == "inspect_cad":
                    content = self.tool_inspect(args)
                elif name == "render_cad":
                    content = self.tool_render(args)
                elif name == "submit_cad":
                    content, done = self.tool_submit(args, state)
                else:
                    content = json.dumps({"error": f"unknown tool {name}"})
                self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
            if done:
                stop = "submitted"
                break
        final = state["submitted"] or self._latest_valid(phase)
        self.meta["phases"][phase] = {"final": final, "stop": stop, "repairs": state["repairs"],
                                      "candidates": [c for c, v in self.candidates.items() if v["phase"] == phase],
                                      "summary": state["summary"], "seconds": round(time.perf_counter() - t0, 1)}
        self._write({"phase": phase, "event": "phase_end", **self.meta["phases"][phase]})
        return final

    def _latest_valid(self, phase):
        ok = [c for c, v in self.candidates.items() if v["phase"] == phase
              and v["report"].get("ok") and v["report"].get("valid") and v["report"].get("solids") == 1]
        return ok[-1] if ok else None

    def save(self):
        def scrub(msg):  # keep the transcript readable: hash images instead of storing base64 twice
            msg = dict(msg)
            if isinstance(msg.get("content"), list):
                parts = []
                for p in msg["content"]:
                    if p.get("type") == "image_url":
                        digest = hashlib.sha256(p["image_url"]["url"].encode()).hexdigest()[:16]
                        parts.append({"type": "image_url", "image_url": f"<png sha256:{digest}>"})
                    else:
                        parts.append(p)
                msg["content"] = parts
            return msg
        (self.dir / "messages.json").write_text(json.dumps([scrub(m) for m in self.messages], indent=1))
        (self.dir / "candidates.json").write_text(json.dumps(self.candidates, indent=1))
        (self.dir / "run.json").write_text(json.dumps(self.meta, indent=1))


def main():
    run = Run()
    try:
        c0, report = run.baseline()
        result = json.dumps({k: report[k] for k in ("ok", "error_type", "error") if k in report})
        first_ok = c0 if report.get("ok") else None
        final = run.tool_loop("repair", REPAIR_PROMPT.format(result=result, budget=REPAIR_BUDGET),
                              REPAIR_BUDGET, first_ok)
        if final:
            run.tool_loop("edit", EDIT_PROMPT.format(cid=final, budget=EDIT_BUDGET), EDIT_BUDGET, None,
                          count_all=True)
    finally:
        run.save()
    print("Run saved to", run.dir)


if __name__ == "__main__":
    main()
