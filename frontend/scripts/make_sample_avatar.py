"""Generate the sample avatar assets used to test .glb support (no external downloads, no licences).

    python scripts/make_sample_avatar.py   # from frontend/

Writes:
  public/avatars/sample-bot.glb    skinned humanoid with Mixamo/RPM-style bone names
                                   (Hips, Spine, Neck, Head, LeftArm, RightArm) and RPM-style
                                   morph targets (mouthOpen, eyeBlinkLeft, eyeBlinkRight)
  public/avatars/sample-anims.glb  animation-only file whose bones use the Mixamo prefix
                                   (mixamorig:Hips ...), clips: Idle, Typing, Talking, Thinking, Sitting

This mirrors the real-world setup: avatar from Ready Player Me / Avaturn, clips from Mixamo.
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "public" / "avatars"

# bone name, parent index, local translation (bind pose)
BONES = [
    ("Hips", -1, (0.0, 0.95, 0.0)),
    ("Spine", 0, (0.0, 0.15, 0.0)),
    ("Neck", 1, (0.0, 0.45, 0.0)),
    ("Head", 2, (0.0, 0.08, 0.0)),
    ("LeftArm", 1, (0.30, 0.38, 0.0)),
    ("RightArm", 1, (-0.30, 0.38, 0.0)),
]


def world_pos(i: int) -> tuple[float, float, float]:
    name, parent, t = BONES[i]
    if parent < 0:
        return t
    p = world_pos(parent)
    return (p[0] + t[0], p[1] + t[1], p[2] + t[2])


class Buffer:
    def __init__(self):
        self.data = bytearray()
        self.views: list[dict] = []
        self.accessors: list[dict] = []

    def add(self, fmt: str, rows: list, comp: int, typ: str, minmax: bool = False, target: int | None = None) -> int:
        while len(self.data) % 4:
            self.data += b"\0"
        start = len(self.data)
        for r in rows:
            self.data += struct.pack("<" + fmt, *(r if isinstance(r, (list, tuple)) else [r]))
        view = {"buffer": 0, "byteOffset": start, "byteLength": len(self.data) - start}
        if target:
            view["target"] = target
        self.views.append(view)
        acc = {"bufferView": len(self.views) - 1, "componentType": comp, "count": len(rows), "type": typ}
        if minmax:
            n = len(rows[0]) if isinstance(rows[0], (list, tuple)) else 1
            cols = [[(r[k] if n > 1 else r) for r in rows] for k in range(n)]
            acc["min"], acc["max"] = [min(c) for c in cols], [max(c) for c in cols]
        self.accessors.append(acc)
        return len(self.accessors) - 1


FLOAT, UBYTE, USHORT = 5126, 5121, 5123
FACES = [  # normal, 4 corners as (sx, sy, sz) signs
    ((1, 0, 0), [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]),
    ((-1, 0, 0), [(-1, -1, 1), (-1, 1, 1), (-1, 1, -1), (-1, -1, -1)]),
    ((0, 1, 0), [(-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)]),
    ((0, -1, 0), [(-1, -1, 1), (-1, -1, -1), (1, -1, -1), (1, -1, 1)]),
    ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
    ((0, 0, -1), [(1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1)]),
]


def box(lo, hi, joint):
    """24 vertices / 36 indices for an axis-aligned box bound to one joint."""
    c = [(lo[i] + hi[i]) / 2 for i in range(3)]
    h = [(hi[i] - lo[i]) / 2 for i in range(3)]
    pos, nor, idx = [], [], []
    for n, corners in FACES:
        base = len(pos)
        for s in corners:
            pos.append(tuple(c[i] + s[i] * h[i] for i in range(3)))
            nor.append(n)
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return pos, nor, idx, joint


def merge(parts):
    pos, nor, idx, joints = [], [], [], []
    for p, n, i, j in parts:
        off = len(pos)
        pos += p
        nor += n
        idx += [k + off for k in i]
        joints += [j] * len(p)
    return pos, nor, idx, joints


def primitive(buf: Buffer, parts, material: int, targets: list[list] | None = None) -> dict:
    pos, nor, idx, joints = merge(parts)
    prim = {
        "attributes": {
            "POSITION": buf.add("3f", pos, FLOAT, "VEC3", minmax=True, target=34962),
            "NORMAL": buf.add("3f", nor, FLOAT, "VEC3", target=34962),
            "JOINTS_0": buf.add("4B", [(j, 0, 0, 0) for j in joints], UBYTE, "VEC4", target=34962),
            "WEIGHTS_0": buf.add("4f", [(1.0, 0, 0, 0) for _ in joints], FLOAT, "VEC4", target=34962),
        },
        "indices": buf.add("H", idx, USHORT, "SCALAR", target=34963),
        "material": material,
    }
    if targets:
        prim["targets"] = [{"POSITION": buf.add("3f", t, FLOAT, "VEC3", minmax=True)} for t in targets]
    return prim


def morph(parts, which: set[int], fn) -> list:
    """Position deltas: apply fn(vertex) to vertices of the selected parts, zero elsewhere."""
    deltas = []
    for k, (p, _n, _i, _j) in enumerate(parts):
        for v in p:
            deltas.append(fn(v) if k in which else (0.0, 0.0, 0.0))
    return deltas


def write_glb(path: Path, gltf: dict, buf: Buffer) -> None:
    gltf["buffers"] = [{"byteLength": len(buf.data)}]
    gltf["bufferViews"], gltf["accessors"] = buf.views, buf.accessors
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    bin_ = bytes(buf.data) + b"\0" * (-len(buf.data) % 4)
    total = 12 + 8 + len(js) + 8 + len(bin_)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<I4s", len(js), b"JSON") + js
        + struct.pack("<I4s", len(bin_), b"BIN\0") + bin_
    )


def skeleton_nodes(prefix: str = "") -> list[dict]:
    nodes = [{"name": prefix + n, "translation": list(t)} for n, _p, t in BONES]
    for i, (_n, parent, _t) in enumerate(BONES):
        if parent >= 0:
            nodes[parent].setdefault("children", []).append(i)
    return nodes


def make_avatar() -> None:
    buf = Buffer()
    J = {n: i for i, (n, _p, _t) in enumerate(BONES)}
    body = [
        box((-0.20, 0.00, -0.11), (-0.03, 0.92, 0.11), J["Hips"]),   # right leg
        box((0.03, 0.00, -0.11), (0.20, 0.92, 0.11), J["Hips"]),     # left leg
        box((-0.24, 0.88, -0.14), (0.24, 1.10, 0.14), J["Hips"]),    # pelvis
        box((-0.27, 1.10, -0.15), (0.27, 1.56, 0.15), J["Spine"]),   # torso
        box((0.24, 0.84, -0.08), (0.36, 1.50, 0.08), J["LeftArm"]),
        box((-0.36, 0.84, -0.08), (-0.24, 1.50, 0.08), J["RightArm"]),
        box((-0.06, 1.55, -0.06), (0.06, 1.64, 0.06), J["Neck"]),
    ]
    head = [box((-0.20, 1.63, -0.19), (0.20, 2.02, 0.19), J["Head"])]
    face = [
        box((0.06, 1.84, 0.19), (0.13, 1.90, 0.205), J["Head"]),     # left eye (+x is the avatar's left)
        box((-0.13, 1.84, 0.19), (-0.06, 1.90, 0.205), J["Head"]),   # right eye
        box((-0.08, 1.71, 0.19), (0.08, 1.74, 0.205), J["Head"]),    # mouth
    ]
    face_targets = [
        morph(face, {2}, lambda v: (0.0, -0.06 if v[1] < 1.725 else 0.0, 0.0)),  # mouthOpen: drop the lower lip
        morph(face, {0}, lambda v: (0.0, (1.87 - v[1]) * 0.9, 0.0)),            # eyeBlinkLeft: squash the eye
        morph(face, {1}, lambda v: (0.0, (1.87 - v[1]) * 0.9, 0.0)),            # eyeBlinkRight
    ]

    inv_bind = []
    for i in range(len(BONES)):
        x, y, z = world_pos(i)
        inv_bind.append((1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -x, -y, -z, 1))

    nodes = skeleton_nodes()
    n_bones = len(nodes)
    nodes += [
        {"name": "Body", "mesh": 0, "skin": 0},
        {"name": "Wolf3D_Head", "mesh": 1, "skin": 0},
        {"name": "Face", "mesh": 2, "skin": 0},
        {"name": "Armature", "children": [0]},
    ]
    gltf = {
        "asset": {"version": "2.0", "generator": "ai-virtual-office make_sample_avatar.py"},
        "scene": 0,
        "scenes": [{"nodes": [n_bones + 3, n_bones, n_bones + 1, n_bones + 2]}],
        "nodes": nodes,
        "skins": [{"joints": list(range(n_bones)), "skeleton": 0,
                   "inverseBindMatrices": buf.add("16f", inv_bind, FLOAT, "MAT4")}],
        "materials": [
            {"name": "Suit", "pbrMetallicRoughness": {"baseColorFactor": [0.13, 0.35, 0.55, 1], "metallicFactor": 0.2, "roughnessFactor": 0.6}},
            {"name": "Skin", "pbrMetallicRoughness": {"baseColorFactor": [0.95, 0.78, 0.63, 1], "metallicFactor": 0, "roughnessFactor": 0.8}},
            {"name": "FaceDark", "pbrMetallicRoughness": {"baseColorFactor": [0.05, 0.05, 0.07, 1], "metallicFactor": 0, "roughnessFactor": 0.5},
             "emissiveFactor": [0.05, 0.9, 0.45]},
        ],
        "meshes": [
            {"name": "Body", "primitives": [primitive(buf, body, 0)]},
            {"name": "Head", "primitives": [primitive(buf, head, 1)]},
            {"name": "Face", "primitives": [primitive(buf, face, 2, face_targets)],
             "weights": [0, 0, 0], "extras": {"targetNames": ["mouthOpen", "eyeBlinkLeft", "eyeBlinkRight"]}},
        ],
    }
    write_glb(OUT / "sample-bot.glb", gltf, buf)


def quat_axis(axis, deg):
    a = math.radians(deg) / 2
    s = math.sin(a)
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(a))


X, Y, Z = (1, 0, 0), (0, 1, 0), (0, 0, 1)


def make_animations() -> None:
    buf = Buffer()
    nodes = skeleton_nodes(prefix="mixamorig:")
    idx = {n: i for i, (n, _p, _t) in enumerate(BONES)}
    animations = []

    def clip(name: str, duration: float, tracks: dict[str, callable], steps: int = 24) -> None:
        times = [duration * k / steps for k in range(steps + 1)]
        tin = buf.add("f", times, FLOAT, "SCALAR", minmax=True)
        samplers, channels = [], []
        for bone, fn in tracks.items():
            values = [fn(t / duration * 2 * math.pi) for t in times]
            samplers.append({"input": tin, "output": buf.add("4f", values, FLOAT, "VEC4"), "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": idx[bone], "path": "rotation"}})
        animations.append({"name": name, "samplers": samplers, "channels": channels})

    clip("Idle", 3.0, {
        "Spine": lambda p: quat_axis(Z, 2.5 * math.sin(p)),
        "Head": lambda p: quat_axis(Y, 8 * math.sin(p)),
        "LeftArm": lambda p: quat_axis(Z, 4 + 2 * math.sin(p)),
        "RightArm": lambda p: quat_axis(Z, -4 - 2 * math.sin(p)),
    })
    clip("Typing", 0.5, {
        "LeftArm": lambda p: quat_axis(X, -70 + 6 * math.sin(p)),
        "RightArm": lambda p: quat_axis(X, -70 + 6 * math.cos(p)),
        "Head": lambda p: quat_axis(X, 12),
        "Spine": lambda p: quat_axis(X, 8),
    })
    clip("Talking", 1.6, {
        "RightArm": lambda p: quat_axis(X, -55 + 25 * math.sin(p)),
        "LeftArm": lambda p: quat_axis(Z, 8 + 6 * math.sin(p * 2)),
        "Head": lambda p: quat_axis(X, 6 * math.sin(p * 2)),
        "Spine": lambda p: quat_axis(Y, 6 * math.sin(p)),
    })
    clip("Thinking", 2.5, {
        "RightArm": lambda p: quat_axis(X, -140),
        "Head": lambda p: quat_axis(Z, 12 + 4 * math.sin(p)),
        "LeftArm": lambda p: quat_axis(X, -20),
    })
    clip("Sitting", 2.0, {
        "Spine": lambda p: quat_axis(X, 4 + 1.5 * math.sin(p)),
        "LeftArm": lambda p: quat_axis(X, -35),
        "RightArm": lambda p: quat_axis(X, -35),
    })

    gltf = {
        "asset": {"version": "2.0", "generator": "ai-virtual-office make_sample_avatar.py"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": nodes,
        "animations": animations,
    }
    write_glb(OUT / "sample-anims.glb", gltf, buf)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    make_avatar()
    make_animations()
    for f in ("sample-bot.glb", "sample-anims.glb"):
        print(f, (OUT / f).stat().st_size, "bytes")
