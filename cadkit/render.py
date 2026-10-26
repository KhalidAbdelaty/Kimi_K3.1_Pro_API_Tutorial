"""Fixed-camera orthographic renderer.

The reference images and every candidate render use the same cameras, the same
framing, and the same scale. Framing is fixed (no auto-fit), so a part that is
too big, too small, or in the wrong place looks wrong instead of being
silently re-centered.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

# Camera manifest, frozen before the first Kimi request.
TARGET = np.array([0.0, 0.0, 22.5])  # world point at the image center (mm)
VIEW_MM = 96.0                        # visible window width and height (mm)
SIZE = 512                            # output image size (px)
SUPERSAMPLE = 2                       # render at 2x, then downsample

CAMERAS = {
    "view1_front": dict(forward=(0, 1, 0), up=(0, 0, 1),
                        label="View 1: front, camera on -Y looking +Y"),
    "view2_top": dict(forward=(0, 0, -1), up=(0, 1, 0),
                      label="View 2: top, camera on +Z looking down"),
    "view3_right": dict(forward=(-1, 0, 0), up=(0, 0, 1),
                        label="View 3: right, camera on +X looking -X"),
    "view4_iso": dict(forward=(-1, 1, -1), up=(0, 0, 1),
                      label="View 4: isometric, camera at (+X, -Y, +Z)"),
}


def _basis(forward, up):
    f = np.asarray(forward, float)
    f /= np.linalg.norm(f)
    r = np.cross(f, np.asarray(up, float))
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return f, r, u


def tessellate(shape, tol=0.02, ang=0.1):
    """Return (vertices Nx3, triangles Mx3) for a CadQuery Shape."""
    verts, tris = shape.tessellate(tol, ang)
    v = np.array([(p.x, p.y, p.z) for p in verts], float)
    t = np.array(tris, int)
    return v, t


def render_view(verts, tris, camera):
    f, r, u = _basis(camera["forward"], camera["up"])
    n = SIZE * SUPERSAMPLE
    px_per_mm = n / VIEW_MM

    rel = verts - TARGET
    sx = (rel @ r) * px_per_mm + n / 2
    sy = n / 2 - (rel @ u) * px_per_mm
    depth = rel @ f  # larger = farther from the camera

    zbuf = np.full((n, n), np.inf)
    shade = np.ones((n, n))
    nbuf = np.zeros((n, n, 3))

    light = -f * 0.55 + u * 0.65 - r * 0.35
    light /= np.linalg.norm(light)

    for a, b, c in tris:
        x = sx[[a, b, c]]
        y = sy[[a, b, c]]
        z = depth[[a, b, c]]
        x0, x1 = int(max(np.floor(x.min()), 0)), int(min(np.ceil(x.max()), n - 1))
        y0, y1 = int(max(np.floor(y.min()), 0)), int(min(np.ceil(y.max()), n - 1))
        if x0 > x1 or y0 > y1:
            continue
        area = (x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0])
        if abs(area) < 1e-12:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((x[1] - gx) * (y[2] - gy) - (x[2] - gx) * (y[1] - gy)) / area
        w1 = ((x[2] - gx) * (y[0] - gy) - (x[0] - gx) * (y[2] - gy)) / area
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        zz = w0 * z[0] + w1 * z[1] + w2 * z[2]
        sub = zbuf[y0:y1 + 1, x0:x1 + 1]
        hit = inside & (zz < sub)
        if not hit.any():
            continue
        normal = np.cross(verts[b] - verts[a], verts[c] - verts[a])
        normal /= np.linalg.norm(normal) + 1e-12
        if normal @ f > 0:  # make the normal face the camera
            normal = -normal
        lum = 0.38 + 0.62 * max(0.0, float(normal @ light))
        sub[hit] = zz[hit]
        shade[y0:y1 + 1, x0:x1 + 1][hit] = lum
        nbuf[y0:y1 + 1, x0:x1 + 1][hit] = normal

    # Feature lines from depth jumps, normal creases, and silhouettes.
    covered = np.isfinite(zbuf)
    zfill = np.where(covered, zbuf, 1e6)
    edge = np.zeros((n, n), bool)
    for dy, dx in ((0, 1), (1, 0)):
        z2 = np.roll(zfill, (-dy, -dx), (0, 1))
        n2 = np.roll(nbuf, (-dy, -dx), (0, 1))
        c2 = np.roll(covered, (-dy, -dx), (0, 1))
        jump = np.abs(zfill - z2) > 0.6
        crease = (covered & c2) & ((nbuf * n2).sum(-1) < np.cos(np.radians(35)))
        edge |= jump | crease | (covered != c2)

    base = np.array([176, 196, 214], float)  # light steel blue
    rgb = np.ones((n, n, 3)) * 255.0
    rgb[covered] = base * shade[covered, None]
    rgb[edge] = (40, 40, 40)

    img = Image.fromarray(rgb.clip(0, 255).astype(np.uint8)).resize((SIZE, SIZE), Image.LANCZOS)
    _annotate(img, camera, f, r, u)
    return img


def _annotate(img, camera, f, r, u):
    draw = ImageDraw.Draw(img)
    draw.text((8, 6), camera["label"], fill=(90, 90, 90))
    # Small axis triad in the lower-left corner: X red, Y green, Z blue.
    origin = np.array([40.0, SIZE - 40.0])
    for axis, color, name in (((1, 0, 0), (200, 40, 40), "X"),
                              ((0, 1, 0), (40, 150, 40), "Y"),
                              ((0, 0, 1), (40, 70, 200), "Z")):
        a = np.array(axis, float)
        d = np.array([a @ r, -(a @ u)]) * 26
        if np.linalg.norm(d) < 4:  # axis points at the camera
            draw.text(tuple(origin + (4, 4)), name, fill=color)
            continue
        end = origin + d
        draw.line([tuple(origin), tuple(end)], fill=color, width=2)
        draw.text(tuple(end + d / np.linalg.norm(d) * 6 - (3, 5)), name, fill=color)


def render_all(shape, out_dir):
    """Render all four fixed views of a shape and return the PNG paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    verts, tris = tessellate(shape)
    paths = []
    for name, cam in CAMERAS.items():
        path = out_dir / f"{name}.png"
        render_view(verts, tris, cam).save(path)
        paths.append(path)
    return paths


def contact_sheet(paths, out_path, title=None):
    """Tile four renders into one 2x2 image (for the article, not for Kimi)."""
    tiles = [Image.open(p) for p in paths]
    pad = 40 if title else 0
    sheet = Image.new("RGB", (SIZE * 2, SIZE * 2 + pad), "white")
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % 2) * SIZE, pad + (i // 2) * SIZE))
    if title:
        ImageDraw.Draw(sheet).text((12, 12), title, fill=(30, 30, 30))
    sheet.save(out_path)
    return out_path
