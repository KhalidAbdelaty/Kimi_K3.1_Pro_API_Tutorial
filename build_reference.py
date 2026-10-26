"""Build the hidden ground-truth bracket and the four reference views.

Only inputs/ is ever shown to Kimi. hidden/ is the answer key for the evaluator.
"""
import hashlib
import json
from pathlib import Path

import cadquery as cq

from cadkit.render import render_all, contact_sheet

ROOT = Path(__file__).parent
HIDDEN = ROOT / "hidden"
INPUTS = ROOT / "inputs"

# Frozen fixture. Units: mm. Frame: X = width, Y = depth (front is -Y), Z = up.
# Origin: center of the bottom face's bounding box. The upright sits at the back (+Y).
DIMS = {
    "width": 60.0,
    "depth": 40.0,
    "height": 45.0,          # overall, including the base thickness
    "thickness": 6.0,        # base and upright
    "hole_diameter": 6.5,    # M6 clearance, through the base
    "hole_spacing": 34.0,    # center to center, along X
    "hole_center_y": -3.0,   # middle of the exposed base (Y from -20 to 14)
    "slot_width": 6.0,
    "slot_length": 20.0,     # end to end, vertical (along Z)
    "slot_center_x": 0.0,
    "slot_center_z": 25.5,   # middle of the exposed upright (Z from 6 to 45)
}


def build(d=DIMS):
    w, dep, h, t = d["width"], d["depth"], d["height"], d["thickness"]
    base = cq.Workplane("XY").box(w, dep, t, centered=(True, True, False))
    upright = (cq.Workplane("XY").center(0, dep / 2 - t / 2)
               .box(w, t, h, centered=(True, True, False)))
    body = base.union(upright)

    half = d["hole_spacing"] / 2
    holes = (cq.Workplane("XY")
             .pushPoints([(-half, d["hole_center_y"]), (half, d["hole_center_y"])])
             .circle(d["hole_diameter"] / 2).extrude(t))
    body = body.cut(holes)

    slot = (cq.Workplane("XZ", origin=(0, dep / 2 - t / 2, 0))
            .center(d["slot_center_x"], d["slot_center_z"])
            .slot2D(d["slot_length"], d["slot_width"], 90)
            .extrude(t, both=True))
    return body.cut(slot)


def validate(shape):
    bb = shape.BoundingBox()
    checks = {
        "solids": len(shape.Solids()),
        "valid": shape.isValid(),
        "bbox": [round(v, 4) for v in (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)],
        "volume_mm3": round(shape.Volume(), 2),
    }
    assert checks["solids"] == 1 and checks["valid"], checks
    assert checks["bbox"] == [-30.0, 30.0, -20.0, 20.0, 0.0, 45.0], checks
    return checks


if __name__ == "__main__":
    HIDDEN.mkdir(exist_ok=True)
    shape = build().val()
    checks = validate(shape)
    cq.exporters.export(build(), str(HIDDEN / "reference.step"))

    source = Path(__file__).read_bytes()
    manifest = {"dims": DIMS, "validation": checks,
                "source_sha256": hashlib.sha256(source).hexdigest()}
    (HIDDEN / "manifest.json").write_text(json.dumps(manifest, indent=2))

    views = render_all(shape, INPUTS)
    contact_sheet(views, HIDDEN / "reference_sheet.png", "Reference views sent to Kimi")
    print(json.dumps(checks, indent=2))
    print("Views:", *[p.name for p in views])
