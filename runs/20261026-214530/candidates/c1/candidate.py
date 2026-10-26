# Overall bracket dimensions
bracket_width = 60.0
bracket_depth = 40.0
bracket_height = 45.0
material_thickness = 6.0

# Vertical back plate location
back_plate_center_y = bracket_depth / 2 - material_thickness / 2

# Base mounting holes
hole_diameter = 6.5
hole_spacing = 34.0
hole_center_y = -3.0
hole_x_positions = (-hole_spacing / 2, hole_spacing / 2)

# Vertical rounded slot through the back plate
slot_width = 9.0
slot_length = 20.0
slot_center_x = 0.0
slot_center_z = 25.5

# Horizontal base, centered in X and Y with its bottom at Z=0
base = (
    cq.Workplane("XY")
    .box(
        bracket_width,
        bracket_depth,
        material_thickness,
        centered=(True, True, False),
    )
)

# Upright plate at the rear (+Y) edge
back_plate = (
    cq.Workplane("XY")
    .box(
        bracket_width,
        material_thickness,
        bracket_height - material_thickness,
        centered=(True, True, False),
    )
    .translate(
        (
            0,
            back_plate_center_y,
            material_thickness,
        )
    )
)

part = base.union(back_plate)

# Drill the two mounting holes vertically through the base
hole_cutter = (
    cq.Workplane("XY", origin=(0, 0, -1.0))
    .pushPoints([(x, hole_center_y) for x in hole_x_positions])
    .circle(hole_diameter / 2)
    .extrude(material_thickness + 2.0)
)
part = part.cut(hole_cutter)

# Cut the vertical obround slot through the upright plate
slot_cutter = (
    cq.Workplane("XZ", origin=(0, back_plate_center_y, 0))
    .center(slot_center_x, slot_center_z)
    .slot2D(slot_length, slot_width, angle=90)
    .extrude(material_thickness, both=True)
)
part = part.cut(slot_cutter)

result = part