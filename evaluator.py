"""Hidden evaluator. Kimi never sees this file, its inputs, or its outputs.

It runs after the agent has finished, on saved STEP files only, and its scores
are never used to steer or stop the agent.
"""
import json
import math
import sys
from pathlib import Path

import cadquery as cq
import numpy as np
import shapely
import trimesh

from cadkit.render import tessellate

ROOT = Path(__file__).parent
MANIFEST = json.loads((ROOT / "hidden" / "manifest.json").read_text())
GT = MANIFEST["dims"]

# Pass/fail rules, frozen before the first Kimi request (see hidden/eval_rules.json).
# Renders are 512 px over a 96 mm window: 1 px is about 0.19 mm. Dimensions the model
# must read from pixels get a few pixels of slack; stated values get tight limits.
RULES = {
    "width_mm": (60.0, 0.5),          # stated in the prompt
    "depth_mm": (40.0, 1.5),
    "height_mm": (45.0, 1.5),
    "thickness_mm": (6.0, 0.5),
    "hole_count": 2,
    "hole_diameter_mm": (6.5, 0.5),
    "hole_center_mm": 1.0,            # distance to the reference center
    "hole_spacing_mm": (34.0, 1.0),
    "slot_count": 1,
    "slot_width_mm": (6.0, 0.5),
    "slot_length_mm": (20.0, 1.5),
    "slot_center_mm": 1.0,            # X and Z each
    "iou_pitch_mm": 0.5,              # absolute-frame voxel IoU, no normalization
    "edit": {
        "slot_width_mm": (9.0, 0.1),  # stated in the edit request
        "unchanged_mm": 0.1,          # slot center and length versus pre-edit
        "preserved_mm": 0.05,         # bbox, thickness, holes versus pre-edit
        "outside_change_mm3": 1.0,    # changed volume outside the slot region
        "pitch_mm": 0.25,
        "region_margin_mm": 0.5,
    },
}


def load_mesh(step_path):
    shape = cq.importers.importStep(str(step_path)).val()
    v, t = tessellate(shape, tol=0.01, ang=0.05)
    return trimesh.Trimesh(v, t, process=True)


_AXES = {  # 3x3 rotation taking world coords to (u, v, w) with w along the normal
    "x": np.array([[0, 1, 0], [0, 0, 1], [1, 0, 0]], float),  # (y, z)
    "y": np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float),  # (x, z)
    "z": np.eye(3),                                             # (x, y)
}


def section(mesh, axis, value):
    """Cross-section polygons (with holes) in the plane axis=value, as 2D shapely."""
    normal = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis]
    origin = np.zeros(3)
    origin["xyz".index(axis)] = value
    path = mesh.section(plane_origin=origin, plane_normal=normal)
    if path is None:
        return []
    m = np.eye(4)
    m[:3, :3] = _AXES[axis]
    m[:3, 3] = -_AXES[axis] @ origin
    planar, _ = path.to_2D(to_2D=m)
    return list(planar.polygons_full)


def _largest(polys):
    return max(polys, key=lambda p: p.area) if polys else None


def measure(mesh):
    """Feature measurements on any candidate that follows the stated frame."""
    lo, hi = mesh.bounds
    out = {"bbox": {"min": lo.round(3).tolist(), "max": hi.round(3).tolist()},
           "size_mm": (hi - lo).round(3).tolist(), "volume_mm3": round(mesh.volume, 2)}

    base = _largest(section(mesh, "z", lo[2] + 1.0))      # 1 mm above the bottom
    holes = []
    if base is not None:
        for ring in base.interiors:
            hole = shapely.Polygon(ring)
            holes.append({"diameter": round(2 * math.sqrt(hole.area / math.pi), 3),
                          "center": [round(hole.centroid.x, 3), round(hole.centroid.y, 3)]})
    out["holes"] = sorted(holes, key=lambda h: h["center"][0])

    upright = _largest(section(mesh, "y", hi[1] - 1.0))   # 1 mm inside the back face
    slots = []
    if upright is not None:
        for ring in upright.interiors:
            x0, z0, x1, z1 = shapely.Polygon(ring).bounds
            slots.append({"width": round(x1 - x0, 3), "length": round(z1 - z0, 3),
                          "center": [round((x0 + x1) / 2, 3), round((z0 + z1) / 2, 3)]})
    out["slots"] = slots

    profile = _largest(section(mesh, "x", lo[0] + 3.0))   # L profile near the left end
    if profile is not None:
        y_front, z_top = lo[1] + 5.0, hi[2] - 5.0
        vert = profile.intersection(shapely.LineString([(y_front, lo[2] - 1), (y_front, hi[2] + 1)]))
        horz = profile.intersection(shapely.LineString([(lo[1] - 1, z_top), (hi[1] + 1, z_top)]))
        out["base_thickness"] = round(vert.length, 3)
        out["upright_thickness"] = round(horz.length, 3)
    return out


def occupancy(mesh, lo, pitch, shape):
    """Solid occupancy on a regular grid, built from Z slices."""
    nx, ny, nz = shape
    xs = lo[0] + (np.arange(nx) + 0.5) * pitch
    ys = lo[1] + (np.arange(ny) + 0.5) * pitch
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    grid = np.zeros(shape, bool)
    for k in range(nz):
        z = lo[2] + (k + 0.5) * pitch
        if z <= mesh.bounds[0][2] or z >= mesh.bounds[1][2]:
            continue
        polys = section(mesh, "z", z)
        if polys:
            grid[:, :, k] = shapely.contains_xy(shapely.union_all(polys), gx, gy)
    return grid


def _grid_for(meshes, pitch, pad=1.0):
    lo = np.min([m.bounds[0] for m in meshes], axis=0) - pad
    hi = np.max([m.bounds[1] for m in meshes], axis=0) + pad
    lo = np.floor(lo / pitch) * pitch
    shape = tuple(np.ceil((hi - lo) / pitch).astype(int))
    return lo, shape


def iou_absolute(a, b, pitch):
    lo, shape = _grid_for([a, b], pitch)
    ga, gb = occupancy(a, lo, pitch, shape), occupancy(b, lo, pitch, shape)
    return float((ga & gb).sum() / max((ga | gb).sum(), 1))


def iou_normalized(a, b, n=64):
    """BenchCAD-style shape overlap: center each bbox, scale the longest side to 1.

    My own implementation of the idea, for comparison only. Not a BenchCAD score.
    """
    grids = []
    for m in (a, b):
        m = m.copy()
        lo, hi = m.bounds
        m.apply_translation(-(lo + hi) / 2)
        m.apply_scale(1.0 / (hi - lo).max())
        grids.append(occupancy(m, np.full(3, -0.5), 1.0 / n, (n, n, n)))
    ga, gb = grids
    return float((ga & gb).sum() / max((ga | gb).sum(), 1))


def _within(value, target_tol):
    target, tol = target_tol
    return value is not None and abs(value - target) <= tol


def score(step_path, reference_mesh):
    mesh = load_mesh(step_path)
    m = measure(mesh)
    size = m["size_mm"]
    checks = {
        "width": _within(size[0], RULES["width_mm"]),
        "depth": _within(size[1], RULES["depth_mm"]),
        "height": _within(size[2], RULES["height_mm"]),
        "base_thickness": _within(m.get("base_thickness"), RULES["thickness_mm"]),
        "upright_thickness": _within(m.get("upright_thickness"), RULES["thickness_mm"]),
        "hole_count": len(m["holes"]) == RULES["hole_count"],
        "slot_count": len(m["slots"]) == RULES["slot_count"],
    }
    ref_holes = [(-GT["hole_spacing"] / 2, GT["hole_center_y"]), (GT["hole_spacing"] / 2, GT["hole_center_y"])]
    if checks["hole_count"]:
        h0, h1 = m["holes"]
        checks["hole_diameters"] = all(_within(h["diameter"], RULES["hole_diameter_mm"]) for h in (h0, h1))
        errs = [math.dist(h["center"], r) for h, r in zip((h0, h1), ref_holes)]
        m["hole_center_errors_mm"] = [round(e, 3) for e in errs]
        checks["hole_centers"] = max(errs) <= RULES["hole_center_mm"]
        checks["hole_spacing"] = _within(h1["center"][0] - h0["center"][0], RULES["hole_spacing_mm"])
    if checks["slot_count"]:
        s = m["slots"][0]
        checks["slot_width"] = _within(s["width"], RULES["slot_width_mm"])
        checks["slot_length"] = _within(s["length"], RULES["slot_length_mm"])
        checks["slot_center"] = (abs(s["center"][0] - GT["slot_center_x"]) <= RULES["slot_center_mm"]
                                 and abs(s["center"][1] - GT["slot_center_z"]) <= RULES["slot_center_mm"])
    return {
        "measurements": m,
        "checks": checks,
        "checks_passed": f"{sum(checks.values())}/{len(checks)}",
        "iou_absolute": round(iou_absolute(mesh, reference_mesh, RULES["iou_pitch_mm"]), 4),
        "iou_normalized_64": round(iou_normalized(mesh, reference_mesh), 4),
    }


def score_edit(pre_step, post_step):
    """Did the edit change the slot width to 9 mm and leave everything else alone?"""
    e = RULES["edit"]
    pre, post = load_mesh(pre_step), load_mesh(post_step)
    a, b = measure(pre), measure(post)
    out = {"pre": a, "post": b, "checks": {}}
    c = out["checks"]
    c["slot_count"] = len(a["slots"]) == 1 and len(b["slots"]) == 1
    if c["slot_count"]:
        sa, sb = a["slots"][0], b["slots"][0]
        c["slot_width_9mm"] = _within(sb["width"], e["slot_width_mm"])
        c["slot_center_kept"] = math.dist(sa["center"], sb["center"]) <= e["unchanged_mm"]
        c["slot_length_kept"] = abs(sa["length"] - sb["length"]) <= e["unchanged_mm"]
    tol = e["preserved_mm"]
    c["bbox_kept"] = np.allclose(a["bbox"]["min"] + a["bbox"]["max"], b["bbox"]["min"] + b["bbox"]["max"], atol=tol)
    c["thickness_kept"] = (abs(a.get("base_thickness", 0) - b.get("base_thickness", -1)) <= tol
                           and abs(a.get("upright_thickness", 0) - b.get("upright_thickness", -1)) <= tol)
    c["holes_kept"] = (len(a["holes"]) == len(b["holes"]) and all(
        abs(ha["diameter"] - hb["diameter"]) <= tol and math.dist(ha["center"], hb["center"]) <= tol
        for ha, hb in zip(a["holes"], b["holes"])))

    # Volume that changed outside the allowed slot region (pre-edit slot, widened to 9 mm).
    pitch = e["pitch_mm"]
    lo, shape = _grid_for([pre, post], pitch)
    g_pre, g_post = occupancy(pre, lo, pitch, shape), occupancy(post, lo, pitch, shape)
    xs = lo[0] + (np.arange(shape[0]) + 0.5) * pitch
    zs = lo[2] + (np.arange(shape[2]) + 0.5) * pitch
    region = np.zeros(shape, bool)
    if c["slot_count"]:
        cx, cz = a["slots"][0]["center"]
        half_w = e["slot_width_mm"][0] / 2 + e["region_margin_mm"]
        half_l = a["slots"][0]["length"] / 2 + e["region_margin_mm"]
        in_x = np.abs(xs - cx) <= half_w
        in_z = np.abs(zs - cz) <= half_l
        region[np.ix_(in_x, np.ones(shape[1], bool), in_z)] = True
    changed = (g_pre ^ g_post) & ~region
    out["outside_change_mm3"] = round(float(changed.sum() * pitch ** 3), 3)
    c["nothing_else_changed"] = out["outside_change_mm3"] <= e["outside_change_mm3"]
    out["checks_passed"] = f"{sum(c.values())}/{len(c)}"
    return out


def freeze_rules():
    path = ROOT / "hidden" / "eval_rules.json"
    path.write_text(json.dumps(RULES, indent=2))
    return path


if __name__ == "__main__":
    # python evaluator.py freeze | python evaluator.py score path/to/candidate.step
    cmd = sys.argv[1]
    if cmd == "freeze":
        print("Rules written to", freeze_rules())
    elif cmd == "score":
        ref = load_mesh(ROOT / "hidden" / "reference.step")
        print(json.dumps(score(sys.argv[2], ref), indent=2))
