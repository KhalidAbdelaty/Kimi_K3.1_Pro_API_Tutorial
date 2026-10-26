# All dimensions are in millimeters.

# Overall envelope
width = 60.0
depth = 40.0
height = 45.0

# L-bracket section
base_thickness = 6.0
wall_thickness = 6.0
wall_center_y = depth / 2.0 - wall_thickness / 2.0
wall_front_y = depth / 2.0 - wall_thickness

# Vertical mounting slot
slot_center_x = 0.0
slot_length = 20.0
slot_width = 9.0
slot_center_z = base_thickness + (height - base_thickness) / 2.0

# Base mounting holes
hole_diameter = 6.5
hole_spacing = 34.0
hole_center_y = (-depth / 2.0 + wall_front_y) / 2.0
hole_points = [
    (-hole_spacing / 2.0, hole_center_y),
    ( hole_spacing / 2.0, hole_center_y),
]

# Boolean cutters extend slightly beyond the material.
cut_margin = 1.0

base = cq.Workplane("XY").box(
    width,
    depth,
    base_thickness,
    centered=(True, True, False),
)

wall = (
    cq.Workplane("XY")
    .box(
        width,
        wall_thickness,
        height,
        centered=(True, True, False),
    )
    .translate((0.0, wall_center_y, 0.0))
)

bracket = base.union(wall)

hole_cutter = (
    cq.Workplane("XY", origin=(0.0, 0.0, -cut_margin))
    .pushPoints(hole_points)
    .circle(hole_diameter / 2.0)
    .extrude(base_thickness + 2.0 * cut_margin)
)

slot_cutter = (
    cq.Workplane("XZ", origin=(0.0, wall_center_y, 0.0))
    .center(slot_center_x, slot_center_z)
    .slot2D(slot_length, slot_width, angle=90.0)
    .extrude(wall_thickness + 2.0 * cut_margin, both=True)
)

result = bracket.cut(hole_cutter).cut(slot_cutter).clean()
