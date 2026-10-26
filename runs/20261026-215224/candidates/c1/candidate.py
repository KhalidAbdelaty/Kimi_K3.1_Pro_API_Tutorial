# Overall dimensions
bracket_width = 60.0
bracket_depth = 40.0
bracket_height = 45.0

# Uniform plate thickness
base_thickness = 6.0
wall_thickness = 6.0

# Base mounting holes
mounting_hole_diameter = 6.0
mounting_hole_spacing = 34.0

# Vertical wall slot
slot_width = 9.0
slot_length = 20.0
slot_center_x = 0.0

# Derived feature locations
wall_center_y = bracket_depth / 2.0 - wall_thickness / 2.0
wall_front_y = bracket_depth / 2.0 - wall_thickness
base_front_y = -bracket_depth / 2.0
mounting_hole_y = (base_front_y + wall_front_y) / 2.0
slot_center_z = base_thickness + (bracket_height - base_thickness) / 2.0

# Horizontal base, centered about X and Y with its bottom at Z=0
base = (
    cq.Workplane("XY")
    .box(bracket_width, bracket_depth, base_thickness)
    .translate((0.0, 0.0, base_thickness / 2.0))
)

# Vertical rear wall
wall = (
    cq.Workplane("XY")
    .box(bracket_width, wall_thickness, bracket_height)
    .translate((0.0, wall_center_y, bracket_height / 2.0))
)

bracket = base.union(wall)

# Two vertical holes through the base
mounting_hole_points = [
    (-mounting_hole_spacing / 2.0, mounting_hole_y),
    (mounting_hole_spacing / 2.0, mounting_hole_y),
]

mounting_hole_cutters = (
    cq.Workplane("XY", origin=(0.0, 0.0, -1.0))
    .pushPoints(mounting_hole_points)
    .circle(mounting_hole_diameter / 2.0)
    .extrude(base_thickness + 2.0)
)

# Rounded-end vertical slot through the rear wall
slot_cutter = (
    cq.Workplane(
        "XZ",
        origin=(slot_center_x, wall_center_y, slot_center_z),
    )
    .slot2D(slot_length, slot_width, angle=90.0)
    .extrude(wall_thickness + 2.0, both=True)
)

result = bracket.cut(mounting_hole_cutters).cut(slot_cutter).clean()