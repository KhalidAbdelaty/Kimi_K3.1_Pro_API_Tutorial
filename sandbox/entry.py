"""Runs inside the sandbox container: execute candidate.py, export STEP, inspect it.

Everything reported here describes the candidate only. No reference data exists
in this container.
"""
import json
import os
import traceback
from collections import Counter

import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface

WORK = os.environ.get("CAD_WORK", "/work")


def to_shape(result):
    if isinstance(result, cq.Workplane):
        objs = [o for o in result.vals() if isinstance(o, cq.Shape)]
        if not objs:
            raise TypeError("result Workplane holds no shapes")
        return objs[0] if len(objs) == 1 else cq.Compound.makeCompound(objs)
    if isinstance(result, cq.Assembly):
        return result.toCompound()
    if isinstance(result, cq.Shape):
        return result
    raise TypeError(f"result has unsupported type {type(result).__name__}")


def axis_name(d):
    for name, v in (("X", d.X()), ("Y", d.Y()), ("Z", d.Z())):
        if abs(abs(v) - 1) < 1e-6:
            return name
    return "other"


def inspect(shape):
    bb = shape.BoundingBox()
    cylinders = Counter()
    for face in shape.Faces():
        if face.geomType() == "CYLINDER":
            cyl = BRepAdaptor_Surface(face.wrapped).Cylinder()
            cylinders[(axis_name(cyl.Axis().Direction()), round(cyl.Radius(), 3))] += 1
    return {
        "valid": shape.isValid(),
        "solids": len(shape.Solids()),
        "bbox_mm": {k: round(getattr(bb, k), 3)
                    for k in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")},
        "size_mm": {"x": round(bb.xlen, 3), "y": round(bb.ylen, 3), "z": round(bb.zlen, 3)},
        "volume_mm3": round(shape.Volume(), 2),
        "faces": len(shape.Faces()),
        "cylindrical_faces": [{"axis": a, "radius_mm": r, "count": n}
                              for (a, r), n in sorted(cylinders.items())],
    }


def main():
    report = {"ok": False}
    try:
        source = open(f"{WORK}/candidate.py", encoding="utf-8").read()
        namespace = {"cq": cq, "show_object": lambda *a, **k: None, "__name__": "candidate"}
        exec(compile(source, "candidate.py", "exec"), namespace)
        if "result" not in namespace:
            raise NameError("the program must assign the final part to a variable named `result`")
        shape = to_shape(namespace["result"])
        cq.exporters.export(shape, f"{WORK}/candidate.step")
        report = {"ok": True, **inspect(shape)}
    except Exception as exc:  # report, never crash silently
        tb = traceback.format_exc().strip().splitlines()
        report = {"ok": False, "error_type": type(exc).__name__,
                  "error": str(exc)[:400], "traceback_tail": tb[-8:]}
    with open(f"{WORK}/report.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh)


if __name__ == "__main__":
    main()
