"""Controls for the evaluator: what voxel IoU says about shapes that are clearly wrong.

Run from the project folder: python -m probes.evaluator_controls
"""
import tempfile
from pathlib import Path

import cadquery as cq

import evaluator as ev
from build_reference import build

ref = ev.load_mesh(ev.ROOT / "hidden" / "reference.step")
with tempfile.TemporaryDirectory() as tmp:
    plain = Path(tmp) / "plain_l.step"     # right outline, no holes, no slot
    base = cq.Workplane("XY").box(60, 40, 6, centered=(True, True, False))
    wall = cq.Workplane("XY").center(0, 17).box(60, 6, 45, centered=(True, True, False))
    cq.exporters.export(base.union(wall), str(plain))
    scaled = Path(tmp) / "scaled.step"     # the exact part, 20% too big
    cq.exporters.export(build().val().scale(1.2), str(scaled))
    for name, step in (("plain L, no features", plain), ("exact part scaled 1.2x", scaled)):
        r = ev.score(step, ref)
        print(f"{name}: checks {r['checks_passed']}, absolute IoU {r['iou_absolute']}, "
              f"normalized IoU {r['iou_normalized_64']}")
