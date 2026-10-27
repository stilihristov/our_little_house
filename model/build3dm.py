"""Turn the scene dump from the web page into a Rhino .3dm with real solids, layers and colours."""
import json, math, sys
import rhino3dm as r

data = json.load(open(sys.argv[1]))
out = sys.argv[2]
m = r.File3dm()
m.Settings.ModelUnitSystem = r.UnitSystem.Meters

# three.js is Y-up, Rhino is Z-up: (x, y, z) -> (x, -z, y)
C = [[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]]

def xform(e):
    M = [[e[c * 4 + row] for c in range(4)] for row in range(4)]  # three stores matrices column-major
    T = [[sum(C[i][k] * M[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
    t = r.Transform(1.0)
    for i in range(4):
        for j in range(4):
            setattr(t, f"M{i}{j}", T[i][j])
    return t

def rgb(h):
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16), 255)

# layers: everything under one root, "A::B" becomes nested
LAYER_COLORS = {"Walls": "#efebe3", "Wall panels": "#b5452f", "Roof fragments": "#dcd5c8", "Structure": "#c8c0b1",
                "Garden column": "#3f6b4c", "Rooms": "#efebe3", "Furniture": "#1d1c1a"}
layer_index = {}
def layer(path):
    if path in layer_index:
        return layer_index[path]
    parent = path.rsplit("::", 1)[0] if "::" in path else "Our Little House"
    l = r.Layer()
    l.Name = path.split("::")[-1]
    l.Color = rgb(LAYER_COLORS.get(path.split("::")[0], "#888888"))
    if path != "Our Little House":
        l.ParentLayerId = m.Layers[layer(parent)].Id
    layer_index[path] = m.Layers.Add(l)
    return layer_index[path]
layer("Our Little House")

materials = {}
def material(h):
    if h not in materials:
        mat = r.Material()
        mat.Name = "plaster " + h
        mat.DiffuseColor = rgb(h)
        materials[h] = m.Materials.Add(mat)
    return materials[h]

def prism(radius, h, segs):
    # same vertex layout as three's CylinderGeometry (x = r·sin θ, z = r·cos θ), extruded along Z, then turned so Z becomes local Y
    pts = [r.Point3d(radius * math.sin(2 * math.pi * k / segs), -radius * math.cos(2 * math.pi * k / segs), -h / 2) for k in range(segs)]
    pl = r.Polyline(0)
    for q in pts + pts[:1]:
        pl.Add(q.X, q.Y, q.Z)
    ext = r.Extrusion.Create(pl.ToNurbsCurve(), h, True)
    g = ext.ToBrep(False)
    bb = g.GetBoundingBox()
    if abs(bb.Min.Z + h / 2) > 1e-6:  # extrusion went the other way: move it back onto the base
        g.Transform(r.Transform.Translation(0, 0, -h / 2 - bb.Min.Z))
    g.Transform(r.Transform.Rotation(-math.pi / 2, r.Vector3d(1, 0, 0), r.Point3d(0, 0, 0)))
    return g

counts = {}
for typ, par, mat, col, lay, name in data:
    if typ == "box":
        w, h, d = par
        g = r.Brep.CreateFromBoundingBox(r.BoundingBox(-w / 2, -h / 2, -d / 2, w / 2, h / 2, d / 2))
    elif typ == "cyl":
        rt, rb, h, segs = par
        if segs >= 12:
            # built along Z, then turned so its axis is three's local Y
            g = r.Cylinder(r.Circle(r.Point3d(0, 0, -h / 2), rb), h).ToBrep(True, True)
            g.Transform(r.Transform.Rotation(-math.pi / 2, r.Vector3d(1, 0, 0), r.Point3d(0, 0, 0)))
        else:
            g = prism(rb, h, int(segs))
    elif typ == "sphere":
        g = r.Sphere(r.Point3d(0, 0, 0), par[0]).ToBrep()
    else:
        continue
    g.Transform(xform(mat))
    a = r.ObjectAttributes()
    a.LayerIndex = layer(lay)
    a.Name = name
    a.ObjectColor = rgb(col)
    a.ColorSource = r.ObjectColorSource.ColorFromObject
    a.MaterialIndex = material(col)
    a.MaterialSource = r.ObjectMaterialSource.MaterialFromObject
    m.Objects.AddBrep(g, a)
    counts[lay] = counts.get(lay, 0) + 1

m.Write(out, 8)
print(sum(counts.values()), "objects", counts)
