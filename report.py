"""Score a finished run with the hidden evaluator, total its cost, and draw the figures.

Usage: python report.py runs/<run-id>
"""
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import cadquery as cq
from PIL import Image, ImageDraw

import evaluator as ev
from build_reference import DIMS, build
from cadkit.render import CAMERAS, SIZE, render_view, tessellate

ROOT = Path(__file__).parent


def load(run_dir):
    run = json.loads((run_dir / "run.json").read_text())
    cands = json.loads((run_dir / "candidates.json").read_text())
    events = [json.loads(line) for line in (run_dir / "requests.jsonl").read_text().splitlines()]
    return run, cands, events


def usage_by_phase(events):
    keys = ("prompt_tokens", "uncached", "cached", "cache_write", "completion_tokens",
            "reasoning_tokens", "cost_usd", "seconds")
    table = defaultdict(lambda: defaultdict(float))
    for e in events:
        row = table[e["phase"]]
        if e["event"] == "request":
            row["requests"] += 1
            row["tool_calls"] += len(e["tool_calls"])
            for k in keys:
                row[k] += e[k]
        elif e["event"] == "execute":
            row["sandbox_seconds"] += e.get("seconds") or 0
        elif e["event"] == "retry":
            row["retries"] += 1
    total = defaultdict(float)
    for row in table.values():
        for k, v in row.items():
            total[k] += v
    table["total"] = total
    return {p: {k: round(v, 6) for k, v in row.items()} for p, row in table.items()}


def labeled(img, text):
    canvas = Image.new("RGB", (img.width, img.height + 34), "white")
    canvas.paste(img, (0, 34))
    ImageDraw.Draw(canvas).text((10, 10), text, fill=(20, 20, 20))
    return canvas


def view(step_path, cam):
    shape = cq.importers.importStep(str(step_path)).val()
    v, t = tessellate(shape)
    return render_view(v, t, CAMERAS[cam])


def strip(items, out_path):
    """items: list of (label, PIL image). Saves a horizontal strip."""
    tiles = [labeled(img, label) for label, img in items]
    sheet = Image.new("RGB", (sum(t.width for t in tiles), tiles[0].height), "white")
    x = 0
    for tile in tiles:
        sheet.paste(tile, (x, 0))
        x += tile.width
    sheet.save(out_path)
    return out_path


def main(run_dir):
    run_dir = Path(run_dir)
    run, cands, events = load(run_dir)
    for cid, c in cands.items():  # resolve paths relative to this run folder
        c["dir"] = str(run_dir / "candidates" / cid)
    ref_step = ROOT / "hidden" / "reference.step"
    ref = ev.load_mesh(ref_step)

    scores = {}
    for cid, c in cands.items():
        step = Path(c["dir"]) / "candidate.step"
        if c["report"].get("ok") and step.exists():
            scores[cid] = {"phase": c["phase"], **ev.score(step, ref)}
        else:
            scores[cid] = {"phase": c["phase"], "ran": False, "error_type": c["report"].get("error_type"),
                           "error": c["report"].get("error")}
        print(cid, c["phase"], scores[cid].get("checks_passed"), scores[cid].get("iou_absolute"),
              scores[cid].get("iou_normalized_64"), scores[cid].get("error_type", ""))

    phases = run["phases"]
    pre = phases.get("repair", {}).get("final")
    post = phases.get("edit", {}).get("final")
    edit = None
    if pre and post:
        pre_step = Path(cands[pre]["dir"]) / "candidate.step"
        post_step = Path(cands[post]["dir"]) / "candidate.step"
        edit = ev.score_edit(pre_step, post_step)
        with tempfile.TemporaryDirectory() as tmp:  # the reference with a 9 mm slot
            ref9 = Path(tmp) / "reference_9mm.step"
            cq.exporters.export(build(dict(DIMS, slot_width=9.0)), str(ref9))
            edit["iou_vs_edited_reference"] = round(
                ev.iou_absolute(ev.load_mesh(post_step), ev.load_mesh(ref9), ev.RULES["iou_pitch_mm"]), 4)
        print("edit", edit["checks_passed"], edit["checks"], "outside change mm3:",
              edit["outside_change_mm3"], "IoU vs 9 mm reference:", edit["iou_vs_edited_reference"])

    usage = usage_by_phase(events)
    print(json.dumps(usage, indent=1))

    # Figures (generated from the saved STEP files, same cameras as the run).
    figs = run_dir / "figures"
    figs.mkdir(exist_ok=True)
    c0 = phases["baseline"]["candidate"]
    items = [("Reference (hidden from Kimi)", view(ref_step, "view4_iso"))]
    if cands[c0]["report"].get("ok"):
        items.append((f"Single shot ({c0})", view(Path(cands[c0]["dir"]) / "candidate.step", "view4_iso")))
    if pre and pre != c0:
        items.append((f"After repairs ({pre})", view(Path(cands[pre]["dir"]) / "candidate.step", "view4_iso")))
    strip(items, figs / "attempts_iso.png")
    front = [("Reference (hidden from Kimi)", view(ref_step, "view1_front"))]
    for label, cid in (("Single shot", c0), ("After repairs", pre)):
        if cid and cands[cid]["report"].get("ok") and (cid != c0 or label == "Single shot"):
            front.append((f"{label} ({cid})", view(Path(cands[cid]["dir"]) / "candidate.step", "view1_front")))
    strip(front, figs / "attempts_front.png")
    if edit:
        crop = (SIZE // 8, SIZE // 8, 7 * SIZE // 8, 7 * SIZE // 8)
        strip([(f"Before edit ({pre}): slot {edit['pre']['slots'][0]['width'] if edit['pre']['slots'] else '?'} mm",
                view(Path(cands[pre]["dir"]) / "candidate.step", "view1_front").crop(crop)),
               (f"After edit ({post}): slot {edit['post']['slots'][0]['width'] if edit['post']['slots'] else '?'} mm",
                view(Path(cands[post]["dir"]) / "candidate.step", "view1_front").crop(crop))],
              figs / "edit_front.png")

    (run_dir / "results.json").write_text(json.dumps(
        {"scores": scores, "edit": edit, "usage": usage, "phases": phases}, indent=1))
    print("Results and figures written to", run_dir)


if __name__ == "__main__":
    main(sys.argv[1])
