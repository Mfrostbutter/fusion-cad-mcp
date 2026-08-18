# Fusion MCP Patterns

Copy-ready Python for `fusion_mcp_execute` scripts. Every snippet assumes the standard `run()` wrapper:

```python
import adsk.core, adsk.fusion

def run(_context: str):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    # paste snippet here
```

Internal units are cm. `ValueInput.createByString('30 mm')` accepts unit suffixes and Fusion converts.

## Table of contents

1. Idempotent user-parameter add
2. Parametric box from a sketched rectangle
3. Construction plane offset from origin plane
4. Multi-profile cut (n cells in one feature)
5. Cut through unknown depth
6. Symmetric extrude (centered on sketch plane)
7. Tapered extrude (cone, legacy countersink approach)
8. Holes via HoleFeatureInput (preferred over sketch+cut)
9. Fillet by current UI selection
10. Edit existing fillet radius (no rebuild needed)
11. Read parameter values for sketch math
12. Bounding box sanity check (always after extrudes)
13. Clean rebuild without losing parameters
14. Export to STL / 3MF / STEP
15. API documentation lookup (before guessing signatures)
16. Screenshot defaults
17. Document search
18. Partial-height interior features via top-shave cut
19. Targeted delete-and-rebuild
20. Force camera fit-view from script
21. Save viewport snapshot to disk
22. Doc state sanity-check (read-only opener)
23. Stepped solid via Join extrude (body + lip flange)
24. Volume sanity check (spec vs actual)
25. Countersink hole via HoleFeatureInput
26. Print all resolved parameter values
27. Constrained parametric ellipse
28. Off-center constrained rectangle (edge-anchored)
29. Constrained parametric circle
30. Constrained rectangle on yZ plane (G5-aware)
31. Re-anchor an origin-pinned sketch entity
32. Edge finding by geometry (fillet/chamfer without UI selection)
33. Replicate features via Mirror (vs Rectangular Pattern)
34. Parametric clearance via composed expressions
35. OffsetStartDefinition for extrude start offset
36. Multi-body cut via participantBodies
37. Composite body via NewBody + Join with overlap
38. Bodies to components, preserving world position
39. As-built joints (revolute hinge + slider)
40. Joint limits
41. Internal travel-stop for a print-in-place slider
42. Reorient a grounded jointed assembly for print/export
43. Sketch constraint anti-patterns
44. Print-in-place hinge via captive cone-tapered cylinder
45. Two-part snap hinge with mating nub-in-cavity
46. Sweep along path with horizontal lines as dimensional scaffolding
47. Loft with guide rails via Intersect + Projection Link
48. Chamfer a circular edge via Revolve-Cut (workaround)
49. Modeled threads on Hole + Thread Offset for chamfer collision
50. Fillet-before-Shell ordering rule
51. Import SVG artwork and place it centred on a face
51b. Embossed sketch text sized to fit a face
52. Single-swap colour-change emboss (icon plane on top of a flat slab)
53. Smooth offset band along a bezier centreline (fitted spline, not polyline)
54. Detail-by-subtraction: draw detail as geometry, filter the profiles
54b. Keyed tab + socket that survives a flat print
55. Trace a silhouette from a screenshot (pixel table to mm)
56. Variant matrix from one design: name the axes into the filename
57. Fit artwork to a print: measure the gaps, not the strokes
58. Leaning cut groove (flute) via a perpendicular construction plane
59. Pattern on Path (when the seed really is perpendicular to the path)
60. Restore-by-join: terminate a field of cuts on a clean boundary
61. Framed fluted panel (plinth, top ring, corner posts, mating pads)
62. Vertical dovetail interlock between stacked or abutting modules
63. Sheared prism via loft (a leaning body with a flat base)
64. Through-cut lattice: one seed cuts two opposite walls
65. Rectangular pattern direction: retry by volume, never by reasoning
66. Verify a slip fit by measurement, not by interference
67. Design variants as suppressible cut blocks in ONE document
68. Verify an opening count by face arithmetic, not by looking
69. Analytic cell decomposition, handed to Fusion as three-point arcs
70. Jittered polygon seed: a constrained N-gon Fusion will actually accept
71. Generated silhouette: draw offline, gate offline, hand Fusion finished loops
72. Classify arrangement profiles by a guaranteed interior point
73. Rebuild one mid-timeline feature in place, not appended
74. Self-supporting ramp as a loft between two XY-plane profiles
75. Nozzle-relative printability gates for flat-plate art

## 1. Idempotent user-parameter add

Make every script safe to re-run.

```python
param_defs = [
    ('length', '220 mm', 'mm', ''),
    ('width',  '148 mm', 'mm', ''),
    ('height', '38 mm',  'mm', ''),
    ('wall',   '3 mm',   'mm', ''),
    ('floor_t', '3 mm',  'mm', ''),      # NOT 'floor' -- reserved, see below
    ('total_height',
     'base_height + air_gap + 2 * floor_thickness',
     'mm', 'COMPUTED'),
]

params = design.userParameters
for name, expr, unit, comment in param_defs:
    if not params.itemByName(name):
        params.add(name, adsk.core.ValueInput.createByString(expr), unit, comment)
```

Expressions can reference other params directly.

**Reserved names.** `userParameters.add` rejects any name that collides with a built-in expression
function, raising `RuntimeError: 3 : param name is not valid`. `floor` is the one that bites in
practice, because it is the natural name for a tray's floor thickness. Avoid: `floor`, `ceil`,
`abs`, `min`, `max`, `mod`, `round`, `sign`, `sqrt`, `pi`, `e`, and the trig names. Suffix instead:
`floor_t`, `min_gap`. Verified 2026-07-31: `floor` REJECTED, `floor_t` / `wall` / `corner_r` accepted.

## 2. Parametric box from a sketched rectangle

A fully constrained centered rectangle: every line shows BLACK in the UI, the browser shows a lock badge, and the box resizes correctly when `length`/`width` change. `addCenterPointRectangle` creates only the four lines, NOT the constraints, so add them explicitly. Never ship a raw-vertex sketch for geometry that should stay parametric (see Sketch constraint anti-patterns, section 43).

```python
P = adsk.core.Point3D.create

sk = root.sketches.add(root.xYConstructionPlane)
sk.name = 'outer'
sk.isComputeDeferred = True

# 1. Geometry only (the API adds no constraints here)
rect = sk.sketchCurves.sketchLines.addCenterPointRectangle(
    P(0, 0, 0), P(2.5, 2.5, 0))   # initial size; dimensions will drive the final size
L_top, L_left, L_bot, L_right = rect.item(0), rect.item(1), rect.item(2), rect.item(3)
sk.isComputeDeferred = False

# 2. Find SW corner (point shared by the left and bottom edges)
sw_pt = None
for sp in [L_left.startSketchPoint, L_left.endSketchPoint]:
    for sp2 in [L_bot.startSketchPoint, L_bot.endSketchPoint]:
        if sp.geometry.x == sp2.geometry.x and sp.geometry.y == sp2.geometry.y:
            sw_pt = sp; break
    if sw_pt: break

# 3. Geometric constraints lock the rectangle shape
gc = sk.geometricConstraints
gc.addHorizontal(L_top); gc.addHorizontal(L_bot)
gc.addVertical(L_left);  gc.addVertical(L_right)

# 4. Size + position-from-origin dimensions
sd = sk.sketchDimensions
DO = adsk.fusion.DimensionOrientations

dim_w = sd.addDistanceDimension(L_top.startSketchPoint, L_top.endSketchPoint,
    DO.HorizontalDimensionOrientation, P(0, 3, 0))
dim_w.parameter.expression = 'length'

dim_d = sd.addDistanceDimension(L_left.startSketchPoint, L_left.endSketchPoint,
    DO.VerticalDimensionOrientation, P(-4, 0, 0))
dim_d.parameter.expression = 'width'

dim_sw_x = sd.addDistanceDimension(sk.originPoint, sw_pt,
    DO.HorizontalDimensionOrientation, P(-2, -3, 0))
dim_sw_x.parameter.expression = 'length / 2'   # math expr binds first try

dim_sw_y = sd.addDistanceDimension(sk.originPoint, sw_pt,
    DO.VerticalDimensionOrientation, P(-4.5, -1, 0))
dim_sw_y.parameter.expression = 'width / 2'

# 5. G6 workaround: re-assign bare param names so they bind parametrically
dim_w.parameter.expression = 'length'
dim_d.parameter.expression = 'width'

assert sk.isFullyConstrained
for d in sk.sketchDimensions:
    assert d.parameter.dependencyParameters.count > 0, \
        f"dim {d.parameter.expression} did not bind to a user param"
assert sk.profiles.count == 1, f"expected 1 profile, got {sk.profiles.count}"

extrudes = root.features.extrudeFeatures
ext_in = extrudes.createInput(sk.profiles.item(0),
    adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
ext_in.setDistanceExtent(False, adsk.core.ValueInput.createByString('height'))
feat = extrudes.add(ext_in)
feat.name = 'body_solid'
feat.bodies.item(0).name = 'main'
```

Four geometric constraints + four dimensions produce a sketch that survives a parametric cascade (verified: `length` 70 to 90 mm updated all dependent geometry with no re-solve). The re-assign in step 5 is the bare-name binding workaround (see "may not bind on first assignment" in gotchas.md). Always assert `isFullyConstrained` AND check `dependencyParameters` after closing the sketch; the API flag alone can read True while the UI still treats the sketch as under-constrained. `isComputeDeferred = True` before bulk line adds matters for >10 vertices; below that it is optional.

## 3. Construction plane offset from origin plane

```python
pi = root.constructionPlanes.createInput()
pi.setByOffset(root.xYConstructionPlane,
               adsk.core.ValueInput.createByString('height'))
plane = root.constructionPlanes.add(pi)
plane.name = 'top_plane'
```

## 4. Multi-profile cut (n cells in one feature)

After sketching multiple closed rectangles on a plane:

```python
profs = adsk.core.ObjectCollection.create()
for i in range(sk.profiles.count):
    profs.add(sk.profiles.item(i))

cut_in = extrudes.createInput(profs,
    adsk.fusion.FeatureOperations.CutFeatureOperation)
ext_def = adsk.fusion.DistanceExtentDefinition.create(
    adsk.core.ValueInput.createByString('height - floor'))
cut_in.setOneSideExtent(ext_def,
    adsk.fusion.ExtentDirections.NegativeExtentDirection)
cut_in.participantBodies = [body]
feat = extrudes.add(cut_in)
feat.name = 'pockets'
```

## 5. Cut through unknown depth

When geometry below the sketch plane has variable depth (gussets, flanges, dividers):

```python
cut_in.setAllExtent(adsk.fusion.ExtentDirections.NegativeExtentDirection)
```

Valid for cut and intersect operations only. This pattern fixes counterbore cuts that get blocked by intermediate geometry the script does not know about.

## 6. Symmetric extrude (centered on sketch plane)

```python
ext_in.setSymmetricExtent(
    adsk.core.ValueInput.createByString('length'),
    True)  # True = value is TOTAL extent, not half
```

## 7. Tapered extrude (cone, legacy countersink approach)

```python
ext_def = adsk.fusion.DistanceExtentDefinition.create(
    adsk.core.ValueInput.createByString('cs_depth'))
taper_vi = adsk.core.ValueInput.createByString('-cs_angle / 2')  # negative = inward
cut_in.setOneSideExtent(ext_def,
    adsk.fusion.ExtentDirections.NegativeExtentDirection,
    taper_vi)
```

For real countersinks, prefer `HoleFeatures.createCountersinkInput` (see section 8).

## 8. Holes via HoleFeatureInput (preferred over sketch+cut)

HoleFeature is parametric, named, editable in the timeline, and cleaner than two extruded cuts. Use over sketch+extrude-cut for any standard hole.

### 8a. Simple through-hole

```python
holes = root.features.holeFeatures
hi = holes.createSimpleInput(adsk.core.ValueInput.createByString('4.2 mm'))
center = adsk.core.Point3D.create(2.5, 2.5, 1.0)  # cm
hi.setPositionByPoint(top_face, center)
hi.setDistanceExtent(adsk.core.ValueInput.createByString('10 mm'))
holes.add(hi)
```

### 8b. Counterbored hole

```python
holes = root.features.holeFeatures
hi = holes.createCounterboreInput(
    adsk.core.ValueInput.createByString('4 mm'),   # hole dia
    adsk.core.ValueInput.createByString('8 mm'),   # cbore dia
    adsk.core.ValueInput.createByString('3 mm'))   # cbore depth
center = adsk.core.Point3D.create(2.5, 2.5, 1.0)
hi.setPositionByPoint(top_face, center)
hi.setDistanceExtent(adsk.core.ValueInput.createByString('10 mm'))
holes.add(hi)
```

Direction is implicit from the face normal passed to `setPositionByPoint`. No explicit `ExtentDirections` argument needed for `setDistanceExtent` here.

## 9. Fillet by current UI selection

When the user has selected edges in Fusion UI before asking Claude to fillet them:

```python
sel = adsk.core.Application.get().userInterface.activeSelections
edges = [sel.item(i).entity for i in range(sel.count)
         if isinstance(sel.item(i).entity, adsk.fusion.BRepEdge)]

fi = root.features.filletFeatures.createInput()
fi.isRollingBall = True  # matches user expectation for blends
ec = adsk.core.ObjectCollection.create()
for e in edges:
    ec.add(e)
fi.addConstantRadiusEdgeSet(ec,
    adsk.core.ValueInput.createByString('8 mm'),
    False)  # False = no tangent chain propagation
feat = root.features.filletFeatures.add(fi)
feat.name = 'edge_fillet_8mm'
```

## 10. Edit existing fillet radius (no rebuild needed)

```python
for f in root.features.filletFeatures:
    if 'edge_fillet' in f.name:
        f.edgeSets.item(0).radius.expression = '10 mm'
        f.name = 'edge_fillet_10mm'
        break
```

Inline radius edit. Cheaper than delete and recreate.

## 11. Read parameter values for sketch math

```python
def p(name):
    return design.userParameters.itemByName(name).value  # returns CM

reach = p('arm_reach')   # if param=30mm, reach == 3.0 (cm)
# Point3D.create(reach, 0, 0) also takes cm. Math is consistent.
```

Only multiply by 10 when printing dimensions for human display.

## 12. Bounding box sanity check (always after extrudes)

```python
bb = body.boundingBox
print(f"X: {bb.minPoint.x*10:.2f} to {bb.maxPoint.x*10:.2f} mm")
print(f"Y: {bb.minPoint.y*10:.2f} to {bb.maxPoint.y*10:.2f} mm")
print(f"Z: {bb.minPoint.z*10:.2f} to {bb.maxPoint.z*10:.2f} mm")
```

Screenshots can deceive on orientation. Bounding box per axis is ground truth.

## 13. Clean rebuild without losing parameters

```python
while root.bRepBodies.count > 0:  root.bRepBodies.item(0).deleteMe()
while root.sketches.count > 0:    root.sketches.item(0).deleteMe()
while root.features.count > 0:    root.features.item(0).deleteMe()
```

Use this instead of `update(undo)` to reset geometry while keeping `userParameters`. Safer than undo because parameters are preserved. For changes that only touch a subset of features (e.g. re-laying out cavities while keeping the body+lip), prefer the targeted delete-and-rebuild in section 19.

## 14. Export to STL / 3MF / STEP

All four formats verified working. Always absolute paths with forward slashes; ensure parent directory exists.

### 14a. STL

```python
import os
out_dir = 'C:/path/to/your/exports'
os.makedirs(out_dir, exist_ok=True)

body = design.rootComponent.bRepBodies.itemByName('main')
em = design.exportManager
opts = em.createSTLExportOptions(body, f'{out_dir}/part.stl')
opts.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
opts.unitType = adsk.fusion.DistanceUnits.MillimeterDistanceUnits
em.execute(opts)
```

Refinement options: `MeshRefinementLow`, `MeshRefinementMedium`, `MeshRefinementHigh`. Only affects curved geometry; flat boxes produce identical files at any setting. Use `High` for production exports; the cost on flat-dominated geometry is zero, the benefit on curves is real. Set `unitType` explicitly so STL scale does not depend on document defaults; the API corpus lists `STLExportOptions.unitType` as a read/write `DistanceUnits` property.

### 14b. 3MF (color + multi-body capable)

```python
opts = em.createC3MFExportOptions(body, f'{out_dir}/part.3mf')
em.execute(opts)
```

Note the capital `C` in `createC3MFExportOptions`. Common signature-guess miss.

### 14c. STEP (component-scoped, not body-scoped)

```python
opts = em.createSTEPExportOptions(f'{out_dir}/part.step', design.rootComponent)
em.execute(opts)
```

Pass a sub-component to scope down; pass `design.rootComponent` for the whole doc.

### Export warnings

- Overwrite is SILENT. If preserving prior exports matters, add a version suffix.
- Relative paths fail with `RuntimeError: 3 : The selected folder does not exist.`
- Protected paths fail with `RuntimeError: 3 : The selected folder is not accessible.`
- Forward slashes work on Windows. Backslashes also work but forward is cleanest.

## 15. API documentation lookup (before guessing signatures)

Always set `apiCategory`. Null or omitted returns success with empty data (silent failure).

```json
{ "queryType": "apiDocumentation",
  "searchPattern": "createSTLExportOptions",
  "apiCategory": "member" }
```

- `member`: best for one named function. Returns signature and docstring.
- `class`: best for exploring an unknown class. Returns properties and functions.
- `all`: best when unsure. Returns everything matching.

Searches accept regex but plain substrings work. Multi-class hits (e.g. `setAllExtent` exists on 4 classes) help locate ownership.

## 16. Screenshot defaults

```json
{ "queryType": "screenshot",
  "width": 800, "height": 600,
  "direction": "current",
  "transparentBackground": true }
```

Run the fit-view block from section 20 BEFORE every screenshot. Without it, results are unreliable:

- `direction: "current"` auto-fits in the common case but stops auto-fitting on Untitled docs and right after script-driven feature additions.
- Named directions (`iso-top-right`, `top`, `right`, `front`) only set orientation; they NEVER auto-fit. If the camera was moved by a prior script, you get an empty frame with a navy background.

Background: `transparentBackground: true` gives a true transparent PNG for compositing. `transparentBackground: false` gives the Fusion workspace background (medium gray-blue with content, dark navy if empty).

## 17. Document search

Use when looking for a specific design (fuzzy, cross-project):

```json
{ "queryType": "document",
  "operation": "search",
  "name": "my-part-name" }
```

Matches case-insensitively. Treats `-` and `_` as equivalent. No project param needed.

Use `document/recent` for "what was I working on?" workflows. Use `document/open` to confirm active-doc state before destructive operations.

## 18. Partial-height interior features via top-shave cut

When dividers (or any interior wall) should stop short of the rim, leaving a common open bay across the top, add a second cut that shaves the top of the existing walls. Additive feature, foundation stays intact.

```python
# Compute divider rectangles from existing param values (read at script time)
cl    = p('compartment_length')
dt    = p('divider_thickness')
cw    = p('cavity_width')
cav_l = p('cavity_length')

# 2 dividers between 3 compartments
d1_x0 = -cav_l/2 + cl
d1_x1 =  d1_x0 + dt
d2_x0 =  cav_l/2 - cl - dt
d2_x1 =  d2_x0 + dt
y0, y1 = -cw/2, cw/2

sk = root.sketches.add(tray_top_plane)
sk.name = 'divider_tops'
sk.isComputeDeferred = True
for x0, x1 in [(d1_x0, d1_x1), (d2_x0, d2_x1)]:
    pts = [P(x0,y0,0), P(x1,y0,0), P(x1,y1,0), P(x0,y1,0)]
    for i in range(4):
        sk.sketchCurves.sketchLines.addByTwoPoints(pts[i], pts[(i+1)%4])
sk.isComputeDeferred = False
assert sk.profiles.count == 2

profs = adsk.core.ObjectCollection.create()
for i in range(sk.profiles.count): profs.add(sk.profiles.item(i))

cut_in = extrudes.createInput(profs,
    adsk.fusion.FeatureOperations.CutFeatureOperation)
ext_def = adsk.fusion.DistanceExtentDefinition.create(
    adsk.core.ValueInput.createByString('divider_top_offset'))
cut_in.setOneSideExtent(ext_def,
    adsk.fusion.ExtentDirections.NegativeExtentDirection)
cut_in.participantBodies = [body]
feat = extrudes.add(cut_in)
feat.name = 'divider_top_shave'
```

Verification math: volume change = (n_dividers) x (divider_thickness) x (cavity_width) x (offset_amount). For 2 x 3mm x 182mm x 20mm = 21.84 cm^3.

Caveat: the X positions in the sketch are computed from current param values at script time, not driven by sketch dimensions. Changing `divider_thickness`, `compartment_count`, or `cavity_length` later will not auto-update; re-run the script.

## 19. Targeted delete-and-rebuild

When changing layout fundamentally but keeping the body+lip foundation, delete only the cavity-shaping features by name, then rebuild. Faster than the section 13 "delete everything" approach when only the layout changes.

```python
# Delete in dependency order: cut features first, then sketches
to_delete_features = ['divider_top_shave', 'compartment_cavities']
to_delete_sketches = ['divider_tops', 'compartments']

for fname in to_delete_features:
    for i in range(root.features.count - 1, -1, -1):
        f = root.features.item(i)
        try:
            if f.name == fname:
                f.deleteMe()
                break
        except Exception:
            pass

for sname in to_delete_sketches:
    for sk in list(root.sketches):
        if sk.name == sname:
            sk.deleteMe()
            break

# Verify body returned to its pre-cut solid state
body = root.bRepBodies.itemByName('tray')
print(f"naked body volume: {body.volume:.2f} cm^3 (should match the solid math)")
```

Verification gate: print body volume after deletion. Should match the math for the body without any cavities (body_lower + lip_flange volumes). If off, something didn't delete cleanly.

Naming requirement: every feature MUST have a unique meaningful name. Without names, delete-by-name fails and you fall back to walking by index, which is fragile.

## 20. Force camera fit-view from script

Reliably frames the body for a screenshot. Closes the camera-control gap previously documented in gotchas.md.

```python
vp = app.activeViewport
vp.fit()
cam = vp.camera
cam.viewOrientation = adsk.core.ViewOrientations.IsoTopRightViewOrientation
cam.isFitView = True
vp.camera = cam
vp.refresh()
```

After this, `read` screenshot with `direction: "current"` produces a properly framed isometric. Named directions on their own do NOT reliably auto-fit; the camera position is whatever the last operation left behind.

Available orientations:

- `IsoTopRightViewOrientation`, `IsoTopLeftViewOrientation`, `IsoBottomLeftViewOrientation`, `IsoBottomRightViewOrientation`
- `FrontViewOrientation`, `BackViewOrientation`, `LeftViewOrientation`, `RightViewOrientation`
- `TopViewOrientation`, `BottomViewOrientation`

Run this block before every screenshot for consistent framing across design iterations.

## 21. Save viewport snapshot to disk

Save the current viewport as a PNG directly to a project path. Bypasses the base64 round-trip of `read` screenshot. Useful for capturing preview images straight into a project's docs folder.

```python
import os

docs_dir = 'C:/path/to/your/docs'
os.makedirs(docs_dir, exist_ok=True)

vp = app.activeViewport
preview_path = f'{docs_dir}/preview-isometric.png'
ok = vp.saveAsImageFile(preview_path, 1600, 1200)
print(f"viewport saved: {ok} -> {preview_path}")
```

Combines well with section 20 (force fit-view) before the save call. Returns `True` on success, `False` on failure. Overwrites silently like other Fusion exports.

## 22. Doc state sanity-check (read-only opener)

Run this BEFORE any modification on an unfamiliar doc. Fastest way to know what you're walking into.

```python
print(f"bodies={root.bRepBodies.count} sketches={root.sketches.count} "
      f"features={root.features.count} units={design.unitsManager.defaultLengthUnits}")
print(f"params={design.userParameters.count} "
      f"planes={root.constructionPlanes.count}")
print(f"doc.isSaved={app.activeDocument.isSaved} "
      f"doc.isModified={app.activeDocument.isModified}")
```

Tells you: is the doc empty, what state are bodies and sketches in, do existing params match what your script expects, is the doc saved (so MCP `save` will work) or Untitled (must SaveAs via UI first).

Pair with `print('PARAMS:', [p.name for p in design.userParameters])` when you suspect a prior script left params you should re-use rather than re-add.

## 23. Stepped solid via Join extrude (body + lip flange)

For tray/insert geometry that has a body section dropping into an opening plus a wider lip flange resting on top. Both sketches use the constrained centered-rectangle approach from section 2 (no raw vertices), via a small helper so body and lip get the identical parametric treatment.

```python
P = adsk.core.Point3D.create
DO = adsk.fusion.DimensionOrientations

def constrained_centered_rect(sk, w_expr, d_expr):
    """Fully constrained rectangle centered on the sketch origin, driven by two param expressions."""
    sk.isComputeDeferred = True
    rect = sk.sketchCurves.sketchLines.addCenterPointRectangle(
        P(0, 0, 0), P(2.5, 2.5, 0))
    L_top, L_left, L_bot, L_right = rect.item(0), rect.item(1), rect.item(2), rect.item(3)
    sk.isComputeDeferred = False

    sw_pt = None
    for sp in [L_left.startSketchPoint, L_left.endSketchPoint]:
        for sp2 in [L_bot.startSketchPoint, L_bot.endSketchPoint]:
            if sp.geometry.x == sp2.geometry.x and sp.geometry.y == sp2.geometry.y:
                sw_pt = sp; break
        if sw_pt: break

    gc = sk.geometricConstraints
    gc.addHorizontal(L_top); gc.addHorizontal(L_bot)
    gc.addVertical(L_left);  gc.addVertical(L_right)

    sd = sk.sketchDimensions
    dim_w = sd.addDistanceDimension(L_top.startSketchPoint, L_top.endSketchPoint,
        DO.HorizontalDimensionOrientation, P(0, 3, 0))
    dim_d = sd.addDistanceDimension(L_left.startSketchPoint, L_left.endSketchPoint,
        DO.VerticalDimensionOrientation, P(-4, 0, 0))
    dim_x = sd.addDistanceDimension(sk.originPoint, sw_pt,
        DO.HorizontalDimensionOrientation, P(-2, -3, 0))
    dim_y = sd.addDistanceDimension(sk.originPoint, sw_pt,
        DO.VerticalDimensionOrientation, P(-4.5, -1, 0))
    dim_x.parameter.expression = '(%s) / 2' % w_expr   # math expr, binds first try
    dim_y.parameter.expression = '(%s) / 2' % d_expr
    dim_w.parameter.expression = '(%s) + 0 mm' % w_expr   # compound expr binds first try (avoids G6 bare-name freeze)
    dim_d.parameter.expression = '(%s) + 0 mm' % d_expr
    assert sk.isFullyConstrained
    assert sk.profiles.count == 1, f"expected 1 profile, got {sk.profiles.count}"
    return sk

extrudes = root.features.extrudeFeatures

# 1. Body lower: constrained rect driven by body_length/body_width, extrude up by body_height
sk_body = root.sketches.add(root.xYConstructionPlane)
sk_body.name = 'body_outer'
constrained_centered_rect(sk_body, 'body_length', 'body_width')

ext_in = extrudes.createInput(sk_body.profiles.item(0),
    adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
ext_in.setDistanceExtent(False, adsk.core.ValueInput.createByString('body_height'))
feat = extrudes.add(ext_in)
feat.name = 'body_lower'
body = feat.bodies.item(0)
body.name = 'tray'

# 2. Construction plane at body top
pi = root.constructionPlanes.createInput()
pi.setByOffset(root.xYConstructionPlane,
               adsk.core.ValueInput.createByString('body_height'))
body_top_plane = root.constructionPlanes.add(pi)
body_top_plane.name = 'body_top_plane'

# 3. Lip flange: wider constrained rect on the body-top plane, JOIN extrude up by lip_height
sk_lip = root.sketches.add(body_top_plane)
sk_lip.name = 'lip_outer'
constrained_centered_rect(sk_lip, 'tray_outer_length', 'tray_outer_width')

lip_in = extrudes.createInput(sk_lip.profiles.item(0),
    adsk.fusion.FeatureOperations.JoinFeatureOperation)
lip_in.setDistanceExtent(False, adsk.core.ValueInput.createByString('lip_height'))
lip_in.participantBodies = [body]   # join target, required (see gotchas.md)
feat = extrudes.add(lip_in)
feat.name = 'lip_flange'
```

Result: single combined body, footprint `body_length x body_width` from z=0 to z=body_height, transitioning to `tray_outer_length x tray_outer_width` at the top for the lip portion. Both sketches are fully constrained, so changing any of the four footprint params cascades correctly. Bambu Studio prints this floor-down with no supports for the 90-degree lip step (short overhangs bridge cleanly).

## 24. Volume sanity check (spec vs actual)

Body volume is in cm^3. Compare against the spec's solid-envelope-minus-cavities math to catch missing cuts or doubled extrusions.

```python
body = root.bRepBodies.itemByName('tray')
print(f"body.volume = {body.volume:.2f} cm^3")
# Cross-check: solid envelope - removed cavities
# e.g. tray = body_box + lip_box - 3 * compartment_box
```

If actual is significantly off from spec math, something is wrong (missed cut, doubled body, wrong participantBody). Catches problems screenshots miss.

CAVEAT: `body.volume` is the geometric solid volume. It is NOT a filament weight estimate. Slicer infill, walls, top/bottom layers, and supports all change the actual print weight by a factor of 2-5x downward from solid volume. Always slice and read grams from the slicer before pricing.

## 25. Countersink hole via HoleFeatureInput

Companion to section 8a (simple) and 8b (counterbore). For screws with conical heads (M3 flat-head, M4 wood screws):

```python
holes = root.features.holeFeatures
hi = holes.createCountersinkInput(
    adsk.core.ValueInput.createByString('4.2 mm'),   # hole dia (shank clearance)
    adsk.core.ValueInput.createByString('8.4 mm'),   # csink dia (head width)
    adsk.core.ValueInput.createByString('82 deg'))   # csink angle (82 deg = #6 wood, 90 deg = metric flat)
center = adsk.core.Point3D.create(2.5, 2.5, 1.0)
hi.setPositionByPoint(top_face, center)
hi.setDistanceExtent(adsk.core.ValueInput.createByString('10 mm'))
holes.add(hi)
```

Common cone angles: 82 degrees (US wood/sheet metal #4-#12), 90 degrees (metric flat head ISO 10642), 100 degrees (US aircraft/military). When in doubt, look up the screw spec.

## 26. Print all resolved parameter values

After idempotent param add (section 1), confirm computed expressions resolve to what you expect:

```python
for pname in [d[0] for d in param_defs]:
    pv = design.userParameters.itemByName(pname)
    print(f"  {pname:30s} expr={pv.expression:40s} value={pv.value*10:.3f} mm")
```

Catches:
- Expression typos that silently default a computed value to 0
- Missing prerequisite params (referencing an undefined name returns a Fusion eval error, but only when triggered)
- Order-of-add issues (a computed param that references a param not yet added)

Run this once after param add, before any body-adding feature that uses a computed value.

## 27. Constrained parametric ellipse

For dispense holes, slots, or any ellipse aligned to world axes. 5 DOFs, 5 constraints.

```python
sk = root.sketches.add(root.xYConstructionPlane)
sk.name = 'dispense_oval'

el = sk.sketchCurves.sketchEllipses.add(
    P(0, 0, 0),       # center (initial position)
    P(1.0, 0, 0),     # major axis end (10mm along X)
    P(0, 0.75, 0))    # any point on the ellipse (defines minor radius)

gc = sk.geometricConstraints
gc.addCoincident(el.centerSketchPoint, sk.originPoint)    # lock center
gc.addHorizontal(el.majorAxisLine)                        # lock major axis direction

sd = sk.sketchDimensions
dim_maj = sd.addEllipseMajorRadiusDimension(el, P(2, 0, 0))
dim_maj.parameter.expression = 'oval_x / 2'    # math expr, binds first try
dim_min = sd.addEllipseMinorRadiusDimension(el, P(0, 1.5, 0))
dim_min.parameter.expression = 'oval_y / 2'

assert sk.isFullyConstrained
```

API points worth knowing: `SketchEllipse.centerSketchPoint` (locatable center), `SketchEllipse.majorAxisLine` (constrain it horizontal/vertical to lock orientation), and `addEllipseMajorRadiusDimension` / `addEllipseMinorRadiusDimension(ellipse, textPoint)`. The third arg to `SketchEllipses.add()` is any point on the curve; it sets the minor radius implicitly.

## 28. Off-center constrained rectangle (edge-anchored)

Same as section 2 but anchor a meaningful corner to a derived expression instead of centering on origin, so the rectangle TRACKS a reference (e.g. a body edge) when params change.

```python
rect = sk.sketchCurves.sketchLines.addCenterPointRectangle(
    P(0.5, 0, 0), P(3.5, 1.1, 0))
L_top, L_left, L_bot, L_right = rect.item(0), rect.item(1), rect.item(2), rect.item(3)

ne_pt = ...  # NE corner: same shared-point lookup as section 2, on top + right edges

gc.addHorizontal(L_top); gc.addHorizontal(L_bot)
gc.addVertical(L_left);  gc.addVertical(L_right)

dim_w = sd.addDistanceDimension(..., DO.HorizontalDimensionOrientation, ...)
dim_w.parameter.expression = 'slot_len'
dim_d = sd.addDistanceDimension(..., DO.VerticalDimensionOrientation, ...)
dim_d.parameter.expression = 'slot_narrow_w'

# Anchor the NE corner to the body edge: if body_width changes, the slot follows the edge
dim_ne_x = sd.addDistanceDimension(sk.originPoint, ne_pt,
    DO.HorizontalDimensionOrientation, ...)
dim_ne_x.parameter.expression = 'body_width / 2'
dim_ne_y = sd.addDistanceDimension(sk.originPoint, ne_pt,
    DO.VerticalDimensionOrientation, ...)
dim_ne_y.parameter.expression = 'slot_narrow_w / 2'

dim_w.parameter.expression = 'slot_len'         # G6 re-assign
dim_d.parameter.expression = 'slot_narrow_w'
```

Choose the anchor corner by what the part should track. Verified cascade: `body_width` 70 to 90 mm moved the slot NE corner 35 to 45 mm (followed the edge) while the slot length stayed 60 mm.

## 29. Constrained parametric circle

Simplest closed curve. 3 DOFs (center X, center Y, radius).

```python
c = sk.sketchCurves.sketchCircles.addByCenterRadius(P(0, 0, 0), 0.25)  # radius in cm
gc.addCoincident(c.centerSketchPoint, sk.originPoint)         # locks center (2 DOFs)
dim_d = sd.addDiameterDimension(c, P(0.5, 0.5, 0))            # locks radius (1 DOF)
dim_d.parameter.expression = 'knuckle_dia'
assert sk.isFullyConstrained
```

For an off-center circle, replace `addCoincident` with two distance dimensions (Horizontal + Vertical) from origin to `c.centerSketchPoint`, like section 2's corner anchor. Note: `addDiameterDimension` bound a bare param name on FIRST try, so the section-2 G6 re-assign is not needed here (the binding bug appears specific to `addDistanceDimension`). `addRadialDimension(circle, textPoint)` is the radius-based alternative.

## 30. Constrained rectangle on yZ plane (G5-aware)

Same constraint pattern as section 28, on `yZConstructionPlane`. The only thing that changes is the G5 axis mapping: sketch X = NEGATIVE world Z, sketch Y = POSITIVE world Y (see gotchas.md). Account for that when choosing sketch coordinates.

```python
sk = root.sketches.add(root.yZConstructionPlane)
sk.name = 'clip_outer'

# Target: clip top at world Z=80, body face at world Y=20, clip out to Y=32
# Per G5: sketch X = -world Z (so X = -80..-30), sketch Y = +world Y (so Y = 20..32)
rect = sk.sketchCurves.sketchLines.addCenterPointRectangle(
    P(-5.5, 2.7, 0), P(-3.0, 3.4, 0))   # initial geometry, cm
L0, L1, L2, L3 = rect.item(0), rect.item(1), rect.item(2), rect.item(3)

# Classify lines by which sketch axis they run along
h_lines = [L for L in [L0,L1,L2,L3]
           if abs(L.startSketchPoint.geometry.y - L.endSketchPoint.geometry.y) < 0.01]
v_lines = [L for L in [L0,L1,L2,L3]
           if abs(L.startSketchPoint.geometry.x - L.endSketchPoint.geometry.x) < 0.01]

gc = sk.geometricConstraints
for L in h_lines: gc.addHorizontal(L)
for L in v_lines: gc.addVertical(L)

# ... size dims (math exprs bind first try) + an anchor dim on the known corner ...
# anchor example: top-of-body at body face = world Z=80, Y=20
dim_ax.parameter.expression = 'body_height'        # sketch X anchor
dim_ay.parameter.expression = 'body_depth / 2'     # sketch Y anchor
dim_ax.parameter.expression = 'body_height'        # G6 re-assign on the bare-name dim
assert sk.isFullyConstrained
```

Reminder: before committing yZ coordinates, drop one test `sketchPoint` and read `worldGeometry` to confirm the G5 mapping (gotchas.md "Habit for any non-XY plane"). Saves a re-orientation debug cycle.

## 31. Re-anchor an origin-pinned sketch entity

To move a sketch entity that is coincident-locked to the origin (e.g. relocate an oval from centered to a parametric offset) without rebuilding the sketch:

1. Delete the center-to-origin coincident constraint (match it by the origin's `entityToken`; the origin usually participates in only that one coincident).
2. `sk.move(collection, translationMatrix)` to pre-position the entity on the correct side.
3. Re-lock: `addHorizontalPoints(origin, center)` locks Y, then a horizontal distance dimension to a param locks X. (`addVerticalPoints` is the X-lock analogue.)

Distance dimensions are MAGNITUDE / unsigned, so pre-move the entity to the correct side first (step 2); the solver keeps it where you put it. Not assembly-specific, but it pairs with the components workflow (section 38) when relocating features after componentizing.

## 32. Edge finding by geometry (fillet/chamfer without UI selection)

To fillet or chamfer specific edges programmatically (e.g. internal corners after a cut), find edges by geometric properties instead of UI selection.

```python
target_edges = []
for edge in body.edges:
    g = edge.geometry
    if not isinstance(g, adsk.core.Line3D):
        continue
    sp, ep = g.startPoint, g.endPoint
    if abs(sp.y - ep.y) > 0.01 or abs(sp.z - ep.z) > 0.01:   # edge runs along X = const Y, const Z
        continue
    y, z = sp.y, sp.z   # cm
    if abs(z - 7.7) < 0.01 and (abs(y - 2.3) < 0.01 or abs(y - 2.9) < 0.01):
        target_edges.append(edge)

fillets = root.features.filletFeatures
fi = fillets.createInput()
fi.isRollingBall = True
ec = adsk.core.ObjectCollection.create()
for e in target_edges: ec.add(e)
fi.addConstantRadiusEdgeSet(ec,
    adsk.core.ValueInput.createByString('clip_fillet_r'), False)   # False = no tangent chain
fillets.add(fi)
```

Chamfer is the same selection feeding `chamfers.createInput(ec, False)` then `ci.setToEqualDistance(ValueInput.createByString('clip_chamfer'))`. A 0.01 cm (0.1mm) tolerance is reliable; keep geometric checks in cm to match internal units.

Volume math (use it as the post-selection sanity check, see section 24):
- Fillet on a CONCAVE edge ADDS material; on a CONVEX edge REMOVES material. Chamfer on a convex edge removes.
- Concave fillet, edge length L, radius r: volume added approx L * r^2 * (1 - pi/4) = L * r^2 * 0.2146.
- Convex chamfer, edge length L, equal distance d: volume removed = L * d^2 / 2.
- Verified on the clip build: 2 fillets (r=2mm, L=40mm) + 2 chamfers (d=1.5mm, L=40mm) gave net -21.3 mm^3 (added 68.7, removed 90); observed -21.33 mm^3.

## 33. Replicate features via Mirror (vs Rectangular Pattern)

To replicate a Join or Cut extrude across a symmetry plane, prefer `MirrorFeatures` over `RectangularPatternFeatures`. Mirror preserves the source operation type (Join stays Join, Cut stays Cut) and targets the same `participantBodies` correctly. `RectangularPattern` with symmetric direction misbehaves on Join extrudes (gotchas.md).

```python
mirror_feats = root.features.mirrorFeatures
input_entities = adsk.core.ObjectCollection.create()
input_entities.add(some_join_extrude_feature)
mi = mirror_feats.createInput(input_entities, root.yZConstructionPlane)
mfeat = mirror_feats.add(mi)
mfeat.name = 'my_mirror_feature'
```

Verified (V7): mirrored a body knuckle Join (X=+20 to X=-20) and lid knuckle pair (X=+10 to X=-10), plus CUT mirrors (body notch, lid notch) preserving each cut's `participantBodies`. No new disconnected bodies; volume deltas matched the source exactly.

Notes:
- The source feature is not moved; Mirror creates a new feature alongside it.
- For non-symmetric layouts (e.g. knuckles at -20, 0, +20): place the +20 instance manually on an offset construction plane, Mirror it to -20, and build the center (X=0) as its own feature.

## 34. Parametric clearance via composed expressions

When a clearance value appears in many cut/feature dimensions (print-in-place mechanisms, snap fits, sliding parts), define it ONCE as a param and reference it through composed expressions everywhere. The whole assembly then tunes from one knob.

```python
params.add('knuckle_clearance', ValueInput.createByString('0.2 mm'), 'mm', '')
params.add('pin_dia',           ValueInput.createByString('3 mm'),   'mm', '')
params.add('knuckle_dia',       ValueInput.createByString('5 mm'),   'mm', '')
params.add('knuckle_len',       ValueInput.createByString('8 mm'),   'mm', '')

# Body notch dia (clears lid knuckle + clearance on each side):
dim.parameter.expression = 'knuckle_dia + 2 * knuckle_clearance'   # = 5.4mm
# Body notch length (clears knuckle X extent + clearance each side):
ext_in.setSymmetricExtent(
    ValueInput.createByString('knuckle_len + 2 * knuckle_clearance'), True)   # = 8.4mm
# Pin bore dia:
dim.parameter.expression = 'pin_dia + 2 * knuckle_clearance'   # = 3.4mm
```

Why it matters: single source of truth (bump `knuckle_clearance` 0.2 to 0.3mm and every clearance cut plus the pin bore expand in one pass); the `+ 2 *` makes DIAMETRAL vs radial clearance explicit; the intent is self-documenting in the expression. Name clearance categories when motion types differ:

```python
params.add('rotational_clearance', ValueInput.createByString('0.2 mm'), 'mm', 'between rotating parts')
params.add('sliding_clearance',    ValueInput.createByString('0.15 mm'), 'mm', 'between sliding parts')
params.add('z_layer_clearance',    ValueInput.createByString('0.2 mm'), 'mm', 'between stacked parts at the layer interface')
```

The single-knob technique is sound and geometry-verified (6 clearance cuts + 1 pin bore on one test part all driven from one param, volume math to <1mm^3).

PRINTER-VERIFIED CORRECTION (captured slider+hinge test part, Bambu): the values 0.2mm rotational / 0.3mm Z / 1mm Y were TOO TIGHT for a captured print-in-place mechanism. The moving parts FUSED to the housing on the first layer (welded, never freed). The expression technique is unchanged; the takeaway is the values and the approach for this class of part:

- For print-in-place capture on FDM, these clearances are not enough. Expect to go looser, and validate at the printer before committing (geometry-verified is not print-verified).
- Preferred path for this class: print SEPARATE parts on one plate with ASSEMBLY clearances (looser, tunable, sandable after the fact) rather than captured-in-place. Componentize first (section 38), then export the parts laid out separately. Use a separate printed or filament/steel-rod pin through the hinge knuckles rather than a print-in-place knuckle.

## 35. OffsetStartDefinition for extrude start offset

When an extrude must start OFFSET from its sketch plane, use `startExtent = OffsetStartDefinition.create(ValueInput)`. Avoids an extra construction plane and keeps the sketch on a clean principal plane.

```python
sk = root.sketches.add(root.yZConstructionPlane)   # sketch at world X=0
# ... build profile ...

ext_in = extrudes.createInput(sk.profiles.item(0),
    adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
ext_in.startExtent = adsk.fusion.OffsetStartDefinition.create(
    adsk.core.ValueInput.createByString('body_width/2 - slot_len'))   # start at X=-25, parametric
ext_def = adsk.fusion.DistanceExtentDefinition.create(
    adsk.core.ValueInput.createByString('slider_len'))
ext_in.setOneSideExtent(ext_def, adsk.fusion.ExtentDirections.PositiveExtentDirection)
feat = extrudes.add(ext_in)
```

Sign convention: the offset is interpreted along the sketch normal. For yZ the normal is +X, so positive offset moves +X. Verified: `body_width/2 - slot_len` = -25 (body_width=70, slot_len=60) placed the start at X=-25, profile at X=0 unchanged, extrude landing at X=-25..+45. Double-verified across two sessions (slider head, plus stop_fin/stop_relief in section 41). Open question: works on principal planes; not yet confirmed on offset construction planes (should, since it operates in the sketch normal).

## 36. Multi-body cut via participantBodies

A single Cut extrude can cut several bodies at once by listing them in `participantBodies`. One timeline feature, guaranteed coaxial across all listed bodies.

```python
ext_in = extrudes.createInput(sk.profiles.item(0),
    adsk.fusion.FeatureOperations.CutFeatureOperation)
ext_in.setSymmetricExtent(adsk.core.ValueInput.createByString('pin_bore_len'), True)
ext_in.participantBodies = [body, lid]   # cuts both in one feature
feat = extrudes.add(ext_in)
feat.name = 'pin_bore'
```

Each body's volume drops by the portion of the cut intersecting it, independently, no double-counting. Verified on the test part's pin bore: a ~472 mm^3 cylinder removed 231 mm^3 from body and 170 mm^3 from lid, each matching per-body geometry. Use for pin bores through interleaved parts, dowel holes, slots crossing both halves of a hinge. NOT for joins: `JoinFeatureOperation` is one-to-one (one participant body); multi-body joins are not meaningful.

## 37. Composite body via NewBody + Join with overlap

To build one body from simple primitives (T-section, L-section, stepped profile), extrude each shape and Join them rather than constructing a complex closed polygon. Avoids the closed-polygon constraint issues in section 43.

```python
# 1. First primitive as NewBody, named
ext_in_1 = extrudes.createInput(sketch_a.profiles.item(0),
    adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
# ... set extent ...
feat_1 = extrudes.add(ext_in_1)
composite_body = feat_1.bodies.item(0)
composite_body.name = 'slider'

# 2. Second primitive as Join, targeting the body from step 1
ext_in_2 = extrudes.createInput(sketch_b.profiles.item(0),
    adsk.fusion.FeatureOperations.JoinFeatureOperation)
# ... set extent, overlapping step 1's range by 0.05-0.1mm ...
ext_in_2.participantBodies = [composite_body]
extrudes.add(ext_in_2)
```

Critical: Join needs NON-ZERO volume overlap. Bodies that merely touch at a planar face are not guaranteed to join. Design a tiny intentional overlap (0.05-0.1mm). Verified on the test part's slider: head (Z=1.0..2.4) + neck (Z=0..1.1, 0.1mm into the head) joined to one 4183.2 mm^3 body, exact. Each primitive is independently constrained via section 2/30, far easier than an 8-vertex T-polygon. Variant: a symmetric Join across a body face (half inside for the join, half outside) adds an external protrusion, e.g. a finger grab.

## 38. Bodies to components, preserving world position

Fusion joints operate on COMPONENTS (occurrences), not bodies. A body-only design must be restructured into components before any joint or motion work. This is the enabler for sections 39-42 AND for exporting separate parts laid out on one plate.

```python
occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())  # identity transform
occ.component.name = 'holder_body'
root.bRepBodies.itemByName('body').moveToComponent(occ)   # fetch FRESH each time; moving mutates the collection
root.bRepBodies.itemByName('pin').moveToComponent(occ)    # several bodies can share a component
occ.isGrounded = True                                     # anchor the fixed base
```

- Identity occurrence transform preserves world position EXACTLY (bboxes to 0.01mm).
- After conversion `root.bRepBodies.count == 0`; reach bodies as proxies via `occ.bRepBodies.itemByName(...)`.
- Historical features stay in the root timeline and remain parametrically editable.
- NEW features can be added to sub-components after conversion (sketch on the sub-component's own `xYConstructionPlane`, which equals world for an identity occurrence). Verified: built a fin in one component and a relief cut in another, both parametric, after componentizing.

Verified: 4 bodies became 3 components (holder_body [body + pin, grounded], lid, slider).

## 39. As-built joints (revolute hinge + slider)

As-built joints define motion between two occurrences IN THEIR CURRENT POSITIONS (no repositioning needed).

```python
ji = root.asBuiltJoints.createInput(occurrenceOne, occurrenceTwo, jointGeometry)
ji.setAsRevoluteJointMotion(direction)   # or setAsSliderJointMotion(direction)
j = root.asBuiltJoints.add(ji); j.name = 'hinge_revolute'
```

Geometry and direction:
- `JointGeometry.createByNonPlanarFace(cylFace, adsk.fusion.JointKeyPointTypes.MiddleKeyPoint)` -> frame Z = cylinder axis (use for a hinge).
- `JointGeometry.createByPlanarFace(face, None, adsk.fusion.JointKeyPointTypes.CenterKeyPoint)` -> frame Z = face normal (use for a slider).
- `JointDirections` (X/Y/Z/Custom) are relative to the JOINT GEOMETRY frame, not world. Build the geometry so the desired axis is frame Z, then use `ZAxisJointDirection`.
- occurrenceTwo's geometry (e.g. a pin inside the grounded body) is valid for positioning.

Driving the joint (V11): `jointMotion` value props are read/write. `RevoluteJointMotion.rotationValue` is radians; `SliderJointMotion.slideValue` is cm. Re-fetch the body proxy after driving to read the updated bbox. CAUTION: a recompute resets driven joints (gotchas.md "Driving a joint does not persist through a recompute"); always re-drive as the final step before screenshot or export.

## 40. Joint limits

Constrain motion to the physically valid range.

This uses the stable `JointLimits` object exposed from joint-motion classes (`SliderJointMotion.slideLimits`, `RevoluteJointMotion.rotationLimits`, etc.; API corpus says introduced July 2015). Do not confuse this with the newer preview `AssemblyConstraint` API.

```python
lim = js.jointMotion.slideLimits          # rotationLimits for a revolute joint
lim.isMinimumValueEnabled = True; lim.minimumValue = 0.0
lim.isMaximumValueEnabled = True; lim.maximumValue = 2.0   # cm (sliders); radians (revolute)
lim.isRestValueEnabled  = True; lim.restValue  = 0.0
```

Units are joint units: cm for sliders, radians for revolute. Setting `restValue` is the mitigation for the joint-drive-reset gotcha. IMPORTANT: a joint limit is a MOTION-STUDY constraint only, NOT a physical stop in the printed part. For a real mechanical stop, see section 41.

## 41. Internal travel-stop for a print-in-place slider

UNPROVEN technique (geometry-verified only; never exercised on a working print, because the test print fused, see section 34). Recorded for the captured-slider case it was designed for; it is NOT the recommended approach if you print separate parts.

A hard mechanical stop so a printed slider physically cannot pass its open position (the joint limit in section 40 is CAD-only). A fin on the MOVING part (Join) rides in a relief pocket cut into the FIXED part (Cut); the pocket's far wall is the stop. Solves "the head covers the stop location when closed" by putting the fin in a sliver above the head that the head never occupies.

Test-part values: stop_fin (Join to slider) box X=10..13, Y=+/-4, Z=2.3..3.0 (0.1mm into head top for the join); stop_relief (Cut from body) X=9..33, Y=+/-5, Z=2.5..3.3, with the +X wall at 33 = fin leading edge (13) + travel (20). Clearances Y +/-1, Z 0.3, -X 1mm. Both are offset-start extrudes (section 35); both sketches fully constrained. Hard stop at 20mm verified in CAD; volumes exact (+14.40, -192.00 mm^3).

Two caveats before reusing this:
- Designed for print-in-place CAPTURE. The whole fin-in-relief design only makes sense for a captured slider. If you print separate parts (the recommended path for this class, section 34), retention changes to a snap-in detent, an end cap, or a removable stop.
- Unproven on a real print. The fused first print never let the catch be tested. Treat the geometry as a starting point, not a validated mechanism.

## 42. Reorient a grounded jointed assembly for print/export

To rotate a whole assembly for print orientation without breaking joints or grounding, transform the GROUNDED BASE occurrence and let the joints carry the children.

```python
import math
# 1. Neutralize driven joints first (so transforms are known).
jh.jointMotion.rotationValue = 0.0; js.jointMotion.slideValue = 0.0
# 2. Unground the base, set its transform2 to the desired world transform.
occ_body.isGrounded = False
M = adsk.core.Matrix3D.create()
M.setToRotation(math.pi, adsk.core.Vector3D.create(1,0,0), adsk.core.Point3D.create(0,0,0))  # 180 deg about world X
M.translation = adsk.core.Vector3D.create(0, 0, dz_cm)   # seat: dz = -(assembly minZ after rotation)
occ_body.transform2 = M
occ_body.isGrounded = True                               # re-anchor in the new orientation
# 3. Re-drive joints LAST (grounding triggers a recompute that resets driven values).
jh.jointMotion.rotationValue = math.radians(180); js.jointMotion.slideValue = 0.0
```

Verified on the test part (V12):
- Moving the grounded base via `transform2` drags the jointed children rigidly; relative poses are preserved so the as-built joints stay satisfied. Lid and slider followed a 180-degree X flip with no child transforms set.
- Setting an ABSOLUTE `transform2` cleanly REPLACES the orientation; reassign a fresh matrix to switch poses.
- `Matrix3D.setToRotation(angle, axis, origin)`; `Matrix3D.translation` is a read/write `Vector3D` applied AFTER the rotation, giving a clean flip + seat.
- Seat on plate: after rotation, assembly minZ = -(extent that rotated to the bottom). Set `M.translation.z = -minZ`, measuring minZ across proxy bboxes WITH joints in their final driven pose (an open lid changes the lowest point).
- Re-ground, then drive joints AFTER grounding. Always re-drive joints as the LAST step before screenshot or export.

Print-orientation note: keep a print-in-place hinge axis HORIZONTAL on the bed (gotchas.md). On the test part the hinge axis is world X; the 180-degree X flip keeps it horizontal, while a side-lay via -90 deg about Y would make it vertical and was rejected.

## 43. Sketch constraint anti-patterns

Avoid these; each one produces a sketch the API reports as constrained while the UI disagrees (or otherwise wastes effort). Use the section 2 corner-anchor approach instead.

- **Diagonal construction line + midpoint centering.** Draw a SW-to-NE diagonal, `addMidPoint(origin, diagonal)`, then H/V + size dims. `isFullyConstrained` reads True, but the UI shows blue lines / no lock badge. Root cause: sign ambiguity, the corners can satisfy all constraints in any of 4 quadrant assignments. Section 2's positive distance dimensions to a SPECIFIC corner remove the ambiguity.
- **Assuming `addCenterPointRectangle` adds constraints.** The UI Center Rectangle tool adds H/V/symmetric automatically; the API call creates ONLY the four lines. Add constraints manually (section 2).
- **`sketch.project()` on an in-plane construction axis.** `sketch.project(root.xConstructionAxis)` on an XY sketch returns an empty collection (the axis is already in-plane). Cannot use it to import a model axis as a symmetry reference; draw and dimension a construction line, or use the corner-anchor pattern.
- **Symmetric constraints with manually-drawn axis lines.** Anchoring axis-line start points to origin and using `addSymmetry` leaves the axis lines' END points (their lengths) as free DOFs, so `isFullyConstrained` stays False. Adding length dims fixes it but buys nothing. Use section 2 instead.
- **RectangularPattern with `isSymmetricInDirectionOne` for Join extrudes.** Produces wrong/disconnected bodies (gotchas.md). Use Mirror (section 33) or place instances manually.

## 44. Print-in-place hinge via captive cone-tapered cylinder

UNPROVEN by us (geometry only; the one print-in-place hinge we attempted fused, see gotchas G "print-in-place at tight clearances"). Recorded with source-video clearance recipe so a future attempt has a baseline.

Mechanism: one continuous body containing two flanges joined by a captive cylindrical knuckle. The knuckle prints WITHOUT supports because the geometry leading up to it on the bed side is tapered at the printer's overhang limit (~55°), and the cap on the opposite side is a -35° tapered cone instead of a full overhang. Walls of the two flanges are separated from the cylinder/cone by Offset Face to create the running clearance.

Source: What-Make-Art Fusion print-in-place hinge tutorial 2026-05-31. Recipe parameters reused verbatim where the speaker stated them with conviction:

```python
# Side-profile sketch on the side plane:
# - Two 90 mm x 8 mm rectangles flanking the origin (the two hinge halves before joining).
# - A vertical-tangent 16 mm circle centered above the origin (the knuckle).
# - Two tangent lines from the rectangle top corners up to the circle at 55 degrees.
#   The 55 degree value is the safe overhang for most FDM printers; the
#   speaker hedged 40-60 deg based on printer. Tune per printer.
overhang_deg   = 55      # adjust to printer (40 conservative, 60 aggressive)
knuckle_dia    = 16      # mm; speaker emphasizes "make it big" for strength
flange_len     = 90      # mm each side
flange_height  = 8       # mm

# Extrude flange-1 + circle + flange-2 ONE DIRECTION 15 mm. New Body.
# Then re-show the sketch and extrude the LEFT flange face alone 30 mm. Join.
# Result: one body with a stepped flange, ready for the cap.

# Cap (cone) on top of the cylinder, opposite side:
# Project the knuckle circle into a new sketch on the +X end face. Draw an
# 8 mm center circle (knuckle_dia / 2 -- half the knuckle diameter is the rule).
cap_dia        = 8       # = knuckle_dia / 2
cap_extrude    = 4       # mm; "about half the diameter" per source
cap_taper_deg  = -35     # negative taper makes a cone that prints without overhang
# Extrude the 8 mm circle 4 mm with -35 degree taper, Join.

# Now extrude the FULL side-profile sketch including the second flange,
# 30 mm, NEW BODY. This gives a second body that the next step turns into
# the other half of the hinge.

# Combine: target = body 2, tool = body 1, operation = cut, Keep Tools = True.

# Offset Face to add running clearance:
#   On body 1, select ALL faces that will touch body 2's mating surfaces,
#   set offset = -0.3 mm.  Then select the cone face, offset = -0.2 mm.
#   (Cone tighter -> less play in the hinge.)
#   Repeat the same offsets on body 2's mating faces.
clear_flat = -0.3   # mm; flat-face running clearance
clear_cone = -0.2   # mm; tighter cone clearance for less play

# Mirror across the center plane joining both bodies into a 2-body unit
# (Create > Mirror, operation = Join).

# Fillets + chamfer for print quality:
#   - Fillet every edge EXCEPT the bed-facing ones, at 0.8 mm (= 2x a 0.4 mm
#     nozzle). 1.2 mm if you want it more rounded.
#   - Chamfer the bottom face that contacts the build plate, 0.8 mm.
fillet_r = 0.8     # = 2 x nozzle_dia (0.4 mm nozzle)
chamfer_bed = 0.8

# Final check: Inspect > Section Analysis on a face perpendicular to the
# hinge axis. Slide the section plane through the part to confirm no walls
# are touching anywhere along the axis.
```

Print-orientation rule (gotchas.md): the hinge axis MUST be parallel to the build plate. Laying the part with the hinge axis vertical turns the running-clearance gaps into horizontal layer planes that fuse on FDM. Section 42 covers reorienting a grounded jointed assembly for this.

If your printer's overhang limit is unknown: print the geometry at 55deg first; if the underside of the cylinder shows sag/strings, lower to 50 or 45 and reprint. Don't go below 40deg without a reason -- below that the cylinder becomes structurally short and weak at the hinge axis.

## 45. Two-part snap hinge with mating nub-in-cavity

UNPROVEN by us. Recorded for the assembly-after-print case where the captive print-in-place approach (section 44) is undesirable (e.g., needs to disassemble, larger hinges where a captured cylinder would be too tall to print well, or the box geometry already has 2 separately printed halves).

Mechanism: two SEPARATE printed bodies, each with a flange + cylindrical knuckle. One knuckle has a centered nub extruded out; the other has a matching cavity. The nub snaps into the cavity when the parts are pressed together, forming a pin joint that pivots.

Source: Product Design Online Day 20 (2026-06-01 transcript, 9-minute tutorial). Recipe:

```python
# Two box halves placed side-by-side via JOINT (not Move).
# Joint Offset sized to the hinge: 4.5 mm flange + 8 mm knuckle dia
# leaves 0.5 mm gap on each side within a 9 mm offset.
joint_offset      = 9     # mm; preserved across box parameter changes
flange_len        = 4.5   # mm; line from top corner outward on the side-face sketch
knuckle_dia       = 8     # mm; circle centered on end of flange line
flange_depth      = 5     # mm; extrude depth of the side-profile flange body
side_gap          = 0.5   # mm; derived: (joint_offset - flange_len - knuckle_dia/2) per side

# OUTER hinge (built into box-bottom component):
# 1. Sketch on outer side face: 4.5 mm horizontal line from top corner;
#    8 mm center circle on line end; tangent angled line from bottom corner.
# 2. Extrude the two profiles 5 mm one direction, New Body (so Mirror works).
# 3. New sketch on the inner face of the outer hinge. Project the outer
#    circle line with Projection Link CHECKED.
# 4. Center circle 4 mm on the PROJECTED center point.
nub_dia           = 4     # mm
nub_depth         = 3.8   # mm; <5 so it does not protrude past inner flange
nub_taper_deg     = -12   # source range: -10 to -14; speaker hedged
nub_edge_fillet   = 1     # mm; prevents the nub from binding inside the cavity
# 5. Extrude the 4 mm circle 3.8 mm, taper -12 deg, Join.
# 6. Fillet the nub's outer edge 1 mm.

# INNER hinge (built into box-top component):
# 7. New sketch on the box-top side facing the outer hinge. Project the
#    hinge profile edge.
# 8. Center circle starting from the PROJECTED point only (no diameter dim
#    so the inner circle inherits from the outer; this is what makes the
#    inner sketch parametric).
# 9. Horizontal line connecting circle to box; tangent angled line from
#    lower box corner; project the existing lower box edge to close the
#    profile.
inner_clear       = 0.6   # mm; Offset Start clearance between mating flanges
# 10. Extrude with Start = Offset(0.6 mm), Distance = 5 mm, New Body.

# CAVITY: cut the nub shape out of the inner hinge.
# 11. Combine: Target = inner hinge body; Tool = outer hinge body (which
#     carries the nub); Operation = Cut; Keep Tools = True.

# RUNNING CLEARANCE: Offset Face on cavity walls.
# Offset Face is per-face, applied to ALL selected faces simultaneously.
# Selecting both opposing walls of a cylindrical cavity and offsetting
# negative 0.4 mm widens the cavity by 0.4 mm on each side = 0.8 mm
# diametric clearance.
cavity_offset    = -0.4   # mm; per-face. Doubles to 0.8 mm diametric.
starting_clear   = 0.8    # mm; diametric. Speaker: start at 0.8, work smaller.
# Range the speaker gives is 0.2-0.8 mm, hedged on slicer/printer.

# Mirror each hinge body across a midplane construction plane to make the
# matching hinge on the opposite side of the box pair.
# - Activate top-level component.
# - Construct > Midplane on the two outer faces of the box.
# - Create > Mirror (Solid tab, NOT Sketch tab) one body at a time so
#   each mirrored body ends up in the correct component.

# Optionally combine each hinge body with its parent box component body.
# Export as STL per component.
layer_h         = 0.1   # mm; speaker's recommended layer height for the print
```

Where the speaker's "parametric adaptability" claim is true vs not, per the Day 20 transcript review:
- Inner hinge sketch (steps 7-10): genuinely parametric. Uses only projected geometry and constraints, scales with the outer hinge.
- Outer hinge sketch (steps 1-2): explicit 4.5 mm flange line and 8 mm circle dimensions. Does NOT scale if box width/height parameters change. If your box dims will change, expose `flange_len` and `knuckle_dia` as user parameters and reference them from the sketch dims so the outer profile tracks.

Print-orientation: the box should lie with the lid face down (build plate down), exposing the hinge profile to print without supports. Layer height 0.1 mm per source.

Print test plan: start at `starting_clear = 0.8 mm`. If too loose (lid wobbles), reduce by 0.1 and reprint until the joint is tight but still pivots. If too tight on first print, increase the `nub_taper_deg` magnitude (toward -14) or reduce `nub_dia` by 0.1.

## 46. Sweep along path with horizontal lines as dimensional scaffolding

UNPROVEN by us. Source: Product Design Online "Day 3 / Paperclip" tutorial (2026-06-01 transcript).

Pattern: when a sweep path has multiple straight-vertical segments separated by horizontal offsets, sketch the horizontal segments as REGULAR lines first so you can dimension their widths quickly, then convert them to CONSTRUCTION lines so the Sweep ignores them. Replace each construction segment with a Tangent Arc that connects the two adjacent vertical lines smoothly. This avoids the "guide rail isn't tangent" headache and lets you dimension the path's width without separate point-to-point dim chains.

```python
# Sketch on top origin plane (paperclip example values):
# Vertical line from origin: 16.25 mm
# Horizontal line: 7.5 mm   <- will become construction
# Vertical line down:       26.25 mm
# Horizontal line: -6.5 mm  <- will become construction
# Vertical line down:       19.25 mm
# Horizontal line:  5.5 mm  <- will become construction
# Vertical line down:        9.25 mm

# After sketching, multi-select the 3 horizontal lines and toggle "Construction"
# in the Sketch Palette (or set isConstruction = True on each SketchLine via API).
# The line geometry survives for the Tangent Arc snap points; it just no longer
# participates in any feature that consumes the sketch's profiles or wires.

for h_line in horizontal_lines:
    h_line.isConstruction = True

# Now add Tangent Arcs across each construction-line endpoint pair. Fusion's
# Tangent Arc tool auto-applies tangent constraints at each junction; that's
# the geometry that makes the Sweep follow smoothly without a kink.
```

Why it matters for an MCP agent: building a sweep path from script-level coordinates without this pattern produces either (a) sharp corners that the Sweep refuses, or (b) a single curved spline that's hard to dimension. The construction-line scaffolding gives you both: each width is a single linear dim, and the corners are guaranteed tangent because they were placed by the Tangent Arc tool, not free-handed.

Convention: name the construction lines (e.g. `width_top`, `width_mid`, `width_bot`) so when you re-edit the sketch later the dimensions stay anchored to identifiable entities.

## 47. Loft with guide rails via Intersect + Projection Link

UNPROVEN by us. Source: a third-party glass-bottle Loft tutorial. The single most useful Loft technique in the corpus.

Pattern: when a Loft uses guide rails, the rails MUST touch every profile or Fusion raises "the guide rail isn't touching all sketch profiles." The reliable way to guarantee this is to sketch the rails on a plane that bisects the profiles (the XZ origin plane for centered profiles), then use the Intersect command (Sketch tab > Create > Project/Include > Intersect) with **Projection Link checked** to snap rail points onto the live profile edges. The intersected geometry appears in purple and updates parametrically if any source profile changes size.

```python
# After sketching 4 profile sketches (e.g. 2 filleted rectangles + 2 circles
# at offset planes), sketch the guide rails on the perpendicular bisector
# plane (XZ origin plane if profiles are centered on origin):

rail_sketch = root.sketches.add(root.xZConstructionPlane)
rail_sketch.name = "guide_rail_left"

# In the UI: hover each of the 4 profile sketches on the LEFT side; the red
# "intersect dot" appears; click to add. Repeat for all 4 profiles. Check
# Projection Link in the dialog. The script equivalent is to call
# sketch.intersect(entities) for each profile sketch.

# Build the rail itself from the now-projected points:
# - For straight segments (typically the upper portion near the stem):
#   draw a Line connecting the top two intersected points.
# - For curved segments (the bottle body curvature):
#   draw a Fit Point Spline through the bottom three intersected points.

# CRITICAL: snap the spline's top handle onto the line so the junction is G1.
# In the UI this is "click and drag the top spline handle until it snaps to
# the straight line." API equivalent is addCoincident between the spline's
# top control point's tangent direction and the line.

# Mirror the rail across the sketch's vertical axis (centered profiles let
# you use the axis directly with no extra construction geometry).

# Finally re-activate Loft; in the dialog, select the 4 profiles in
# bottom-to-top order (Loft IS ORDER-SENSITIVE), then click into the Rails
# field and pick the spline+line as one rail and the mirrored copy as the
# other.
```

Two failure modes the source video explicitly calls out:
1. **"Guide rail isn't touching all sketch profiles"** — caused by free-handed rail points that look on a profile edge but aren't. Fix: always use Intersect, never eyeball.
2. **Discontinuity at the spline-line junction** — Loft may treat them as separate rails or produce a kink. Fix: explicitly snap the spline's top handle to the line so the junction is G1 (tangent-continuous).

The geometric-continuity test was added as a follow-up Underspecified entry in the Day 4 dive: the source video doesn't say whether the snap achieves G1 (tangent) or only G0 (positional). In practice the snap appears to do G1 because Fusion shows the spline-line tangent constraint after snapping. If the Loft produces a visible kink anyway, manually add a tangent constraint between the spline's top control direction and the line.

## 48. Chamfer a circular edge via Revolve-Cut (workaround)

UNPROVEN by us. Source: a third-party hex-nut tutorial. Speaker says verbatim *"Chamfer does not currently work in a circular manner"* — this is a documented Fusion limitation as of 2023 video date, and the Revolve-Cut workaround is the accepted alternative.

The Chamfer feature in Fusion is designed for STRAIGHT-EDGE chamfers (rectangular box edges, polygon corners). When the target edge is circular (e.g., the OD of a cylinder, the chamfer ring on a hex nut where the top face transitions to the side faces), the Chamfer feature either refuses or produces wrong geometry. Substitute a Revolve-Cut driven by a small triangle profile:

```python
# 1. Sketch a triangle on a plane that contains the rotation axis (typically
#    XZ if the body's rotation axis is Z). Project the corner point of the
#    body you want to chamfer so the triangle's apex snaps to it precisely.
chamfer_height = 1.5   # mm; how tall the chamfer is along the axis
# Equal constraint on the two non-vertical legs -> isosceles right triangle,
# giving a 45-degree chamfer. Vertical leg = chamfer_height.

# 2. Revolve the triangle around the body's rotation axis (Z), 360 degrees.
#    Fusion auto-detects the existing body and switches Operation to Cut.
revolves = root.features.revolveFeatures
ri = revolves.createInput(triangle_profile, root.zConstructionAxis,
                          adsk.fusion.FeatureOperations.CutFeatureOperation)
ri.setAngleExtent(False, adsk.core.ValueInput.createByString("360 deg"))
revolves.add(ri)
```

Combine with Mirror-by-FACES (NOT Mirror-by-Features) when the chamfer needs to appear on both ends of the body:

```python
# Build a Midplane construction plane from the two outer faces of the body,
# then activate Mirror with Object Type = Faces:
mirror_input = root.features.mirrorFeatures.createInput(
    chamfer_face_collection,        # ObjectCollection of BRepFaces
    midplane_construction_plane)
root.features.mirrorFeatures.add(mirror_input)
```

Mirror-by-Faces lets you pick the specific chamfer faces from the body, not the original Revolve-Cut feature itself. This is correct when you want only the chamfer geometry mirrored (not the triangle sketch). Pattern N33 covers Mirror-by-Features for symmetric extrude duplication; this entry exists separately because mirroring a Revolve-Cut feature directly is awkward (the source feature already wraps 360 degrees; mirroring the feature produces overlapping geometry).

Open question whether Fusion has fixed the Chamfer-on-circular-edges limitation since the 2023 source video. Re-test with the Chamfer tool on a circular edge before committing to the workaround for new designs. If Chamfer now works, prefer it; this entry then becomes a fallback for legacy compatibility.

## 49. Modeled threads on Hole + Thread Offset for chamfer collision

UNPROVEN by us. Source: a third-party hex-nut tutorial.

Two distinct lessons in one Hole-feature workflow:

**Modeled vs cosmetic threads.** Fusion's Hole feature defaults to a "cosmetic" thread, which is a texture map shown in the viewport but absent from the 3D body and excluded from STL / STEP export. To get a thread that affects geometry (for 3D printing, FEA, or downstream CAM), you MUST check the **Modeled** checkbox. Per the source: *"You must check the 'Modeled' option if you would like this thread to affect the actual 3D body. Otherwise, Fusion 360 threads will default to being represented by a static image that will not affect the model upon exporting. This is to help with latency on large files that may contain hundreds of threads."*

```python
# Hole feature input with modeled thread.
hi = root.features.holeFeatures.createSimpleInput(
    adsk.core.ValueInput.createByString("12 mm"))   # nominal drill diameter
hi.setAllExtent(adsk.fusion.ExtentDirections.PositiveExtentDirection)
hi.threadInfo = adsk.fusion.HoleThreadInfo.create(
    adsk.fusion.ThreadLocations.SidesThreadLocation,
    "GB Metric profile",          # thread standard family
    "M12x1",                       # thread designation
    "12 mm",                       # nominal size
)
hi.isModeled = True                # critical: produce actual geometry
root.features.holeFeatures.add(hi)
```

**Thread Offset for chamfer collision.** When a hex nut (or similar threaded part) has chamfers on both faces AND a tapped hole running through, the thread cylinder geometrically intersects the chamfer cone on whichever side the chamfer is. The fix is to shorten the thread so it doesn't reach the chamfer:

```python
# After the initial Hole feature, edit it (or set on creation):
hi.threadOffset = adsk.core.ValueInput.createByString("8.5 mm")
```

The 8.5mm value in the source is derived from the specific hex-nut geometry (10mm extrude depth + 1.5mm chamfer height per side). For a script-driven part, compute the offset parametrically:

```python
thread_offset_expr = "extrude_depth - chamfer_height - thread_clearance"
# e.g., 10 - 1.5 - 0 = 8.5 mm in the source's geometry
```

Practical note: Fusion's parametric edit-back makes this a one-shot followup. Modify the Hole feature after observing the collision; the thread shortens, the Hole otherwise stays intact, no need to rebuild.

## 50. Fillet-before-Shell ordering rule

Codified from two third-party glass-bottle tutorials. Both call this out independently as a critical ordering rule.

Rule: when a body will be Shelled, apply any Modeling Fillets to the OUTSIDE of the body BEFORE running the Shell command. Shell traces the existing contour to compute the inner wall offset, so a fillet that exists at Shell-time produces a smooth uniform-thickness wall around the rounded edge. A fillet applied AFTER Shell does not propagate to the inner surface — the inner surface stays sharp where the outer is rounded, the wall thickness becomes non-uniform near the fillet, and in pathological cases Shell silently fails.

```python
# Correct order:
# 1. Build solid body (extrude / revolve / loft / sweep).
body = build_main_body()

# 2. Apply outer-edge fillets.
fillets = root.features.filletFeatures
edge_collection = adsk.core.ObjectCollection.create()
edge_collection.add(body_lower_edge)
fi = fillets.createInput()
fi.addConstantRadiusEdgeSet(edge_collection,
    adsk.core.ValueInput.createByString("5 mm"), True)
fillets.add(fi)

# 3. THEN Shell.
shell_input = root.features.shellFeatures.createInput(
    body_open_face_collection,        # the open face(s)
    False)                            # isTangentChain
shell_input.insideThickness = adsk.core.ValueInput.createByString("2 mm")
root.features.shellFeatures.add(shell_input)
```

Equivalent rule for sketch fillets in Loft / Sweep profiles: apply Sketch Fillets to the profile sketches BEFORE building the Loft/Sweep. The Loft consumes the sketch with whatever profile is closed at the time; if you fillet the sketch later, the Loft may or may not pick up the change depending on the timeline.

Verified-by-source quote (Day 2): *"It's important to note that we're adding the Fillet before we make the bottle hollow, as the Shell command will trace the inside of the object."*

Verified-by-source quote (Day 4): *"Similar to the soda bottle on day number two, we need to apply this fillet before we go to hollow out the body, as the shell command will follow this contour."*

Two independent corroborations from a careful source on the same point is enough to codify this without our own print verification. (The rule is also widely repeated in Fusion training material outside this corpus.)

Corollary: if you discover after Shell that you forgot a fillet, the cheapest fix is to delete the Shell from the timeline, add the fillet, and re-add the Shell. Edits compound; rolling back one feature is usually faster than fighting a half-correct geometry.

## 51. Import SVG artwork and place it centred on a face

Brand logos and any artwork too complex to draw from primitives. See gotchas: imported curves are FIXED (`sketch.move()` is a silent no-op), and holes arrive as separate profiles.

Two-step: measure the native size once with a throwaway import, then place for real.

```python
SVG = 'C:/abs/path/logo.svg'
TARGET_W = 44.0                  # mm, final width on the face
TARGET_CX, TARGET_CY = 0.0, 0.0  # mm, where to centre it

# --- step 1: measure native size at scale 1.0 (throwaway) ---
probe = root.sketches.add(root.xYConstructionPlane)
probe.importSVG(SVG, 0, 0, 1.0)
xs, ys = [], []
for c in probe.sketchCurves:
    b = c.boundingBox
    xs += [b.minPoint.x, b.maxPoint.x]
    ys += [b.minPoint.y, b.maxPoint.y]
native_w, native_h = (max(xs)-min(xs))*10, (max(ys)-min(ys))*10   # mm
probe.deleteMe()

# --- step 2: place at import time (anchor = top-left, extends +X / -Y) ---
s = TARGET_W / native_w
w, h = native_w * s, native_h * s
ax_cm = (TARGET_CX - w/2.0) / 10.0
ay_cm = (TARGET_CY + h/2.0) / 10.0

sk = root.sketches.add(plane)
sk.name = 'icon_logo'
assert sk.importSVG(SVG, ax_cm, ay_cm, s), "importSVG failed"

# --- step 3: verify it lands inside the host face BEFORE extruding ---
xs, ys = [], []
for c in sk.sketchCurves:
    b = c.boundingBox
    xs += [b.minPoint.x, b.maxPoint.x]
    ys += [b.minPoint.y, b.maxPoint.y]
print(f"bbox X {min(xs)*10:.2f}..{max(xs)*10:.2f}  Y {min(ys)*10:.2f}..{max(ys)*10:.2f}")
assert min(xs)*10 > FACE_X_MIN and max(xs)*10 < FACE_X_MAX, "artwork overruns face in X"
assert min(ys)*10 > FACE_Y_MIN and max(ys)*10 < FACE_Y_MAX, "artwork overruns face in Y"

# --- step 4: keep solids, drop holes ---
thresh = 100.0 * s * s           # mm^2; tune per asset, print the split to check
keep = adsk.core.ObjectCollection.create()
for i in range(sk.profiles.count):
    pr = sk.profiles.item(i)
    area = pr.areaProperties(
        adsk.fusion.CalculationAccuracy.LowCalculationAccuracy).area * 100.0
    if pr.profileLoops.count > 1 or area > thresh:
        keep.add(pr)
        print(f"  keep [{i}] loops={pr.profileLoops.count} area={area:.2f}")
    else:
        print(f"  HOLE [{i}] loops={pr.profileLoops.count} area={area:.2f}")

exts = root.features.extrudeFeatures
ei = exts.createInput(keep, adsk.fusion.FeatureOperations.JoinFeatureOperation)
ei.setDistanceExtent(False, adsk.core.ValueInput.createByString('icon_t'))
exts.add(ei).name = 'icon_logo_extrude'

assert root.bRepBodies.count == 1, f"floating bodies: {root.bRepBodies.count} (artwork off-face?)"
```

## 51b. Embossed sketch text sized to fit a face

Extrude the **SketchText object itself**, not `sketch.profiles` — Fusion preserves letter counters (a, o, e) automatically, so none of the SVG hole-filtering applies.

```python
sk = root.sketches.add(plane)
sk.name = 'agent_text'
ti = sk.sketchTexts.createInput2('automate it', cm(7.0))     # height in cm
ti.fontName = 'Arial'
ti.textStyle = adsk.fusion.TextStyles.TextStyleBold
ti.setAsMultiLine(
    P(cm(-29.5), cm(-11.0), 0), P(cm(29.5), cm(11.0), 0),    # the wrap box
    adsk.core.HorizontalAlignments.CenterHorizontalAlignment,
    adsk.core.VerticalAlignments.MiddleVerticalAlignment, 0)
st = sk.sketchTexts.add(ti)

ei = exts.createInput(st, adsk.fusion.FeatureOperations.JoinFeatureOperation)   # <- st, not a profile
ei.setDistanceExtent(False, adsk.core.ValueInput.createByString('icon_t'))
exts.add(ei).name = 'agent_text_extrude'
```

**Always probe the height; never assume it.** Font metrics are unknowable in advance, and `setAsMultiLine` silently **wraps** rather than erroring, which shows up as a bbox far taller than the requested height:

```python
for h_mm in (7.0, 7.5, 8.0):
    sk = root.sketches.add(plane); sk.name = '_fit'
    ...
    st = sk.sketchTexts.add(ti)
    bb = st.boundingBox
    w, ht = (bb.maxPoint.x-bb.minPoint.x)*10, (bb.maxPoint.y-bb.minPoint.y)*10
    print(f"h={h_mm} -> {w:.2f} x {ht:.2f}  {'WRAPPED' if ht > h_mm*1.5 else 'single line'}")
    sk.deleteMe()
```

Real data, "automate it" in Arial Bold on a 60mm face: 7.0mm -> 51.69mm wide (fits, 4.15mm margins); 7.5mm -> 55.39mm (2.31mm); 8.0mm -> 59.08mm (0.46mm, unusable). Widen the wrap box past the expected string width or the wrap masks the real fit.

## 52. Single-swap colour-change emboss (icon plane on top of a flat slab)

For an FDM piece where embossed artwork must print in a second colour with **no manual paint step** in the slicer. The trick is geometric, not a slicer setting: if nothing whatsoever exists above the slab's top face except the artwork, then every layer above that height is pure artwork, so one filament change at that Z colours all of it.

```python
# icon_plane tracks body_t automatically, so thickness variants need no rework
pi = root.constructionPlanes.createInput()
pi.setByOffset(root.xYConstructionPlane, adsk.core.ValueInput.createByString('body_t'))
icon_plane = root.constructionPlanes.add(pi)
icon_plane.name = 'icon_plane'

# every icon sketch goes on icon_plane and extrudes 'icon_t' Join
```

Rules that make it work:

- **Nothing else above `body_t`.** One stray feature poking above the slab breaks the guarantee.
- **Land `body_t` on a layer boundary.** 10mm and 15mm are both exact at 0.2mm layers (layer 50 / 75). A `body_t` of e.g. 10.1mm forces the swap mid-layer.
- **Make `icon_t` a whole number of layers.** 0.6mm = 3 layers at 0.2mm.
- Per-icon *different* colours still need manual painting; this pattern buys one swap for all artwork at once.

## 53. Smooth offset band along a bezier centreline (fitted spline, not polyline)

For ribbon/connector geometry following a curve. Sampling the centreline and offsetting into a many-segment polyline "works" but leaves visible facets on the extruded side walls (~1mm facets at 48 segments). Fitted splines through far fewer points give smooth walls, and the volume comes out unchanged, which is the proof the swap did not distort the geometry.

```python
import math

def bez(p0, p1, p2, p3, t):
    u = 1.0 - t
    return (u*u*u*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t*t*t*p3[0],
            u*u*u*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t*t*t*p3[1])

def bez_d(p0, p1, p2, p3, t):        # analytic tangent; do NOT finite-difference
    u = 1.0 - t
    return (3*u*u*(p1[0]-p0[0]) + 6*u*t*(p2[0]-p1[0]) + 3*t*t*(p3[0]-p2[0]),
            3*u*u*(p1[1]-p0[1]) + 6*u*t*(p2[1]-p1[1]) + 3*t*t*(p3[1]-p2[1]))

P = adsk.core.Point3D.create
W = 0.15        # HALF width, cm
N = 12          # 13 points is plenty for a spline; 48 was overkill as a polyline

left, right = [], []
for i in range(N + 1):
    t = i / float(N)
    px, py = bez(p0, p1, p2, p3, t)
    tx, ty = bez_d(p0, p1, p2, p3, t)
    m = math.hypot(tx, ty)
    nx, ny = ty/m, -tx/m                      # unit normal
    left.append(P(px + nx*W, py + ny*W, 0))
    right.append(P(px - nx*W, py - ny*W, 0))

lc = adsk.core.ObjectCollection.create()
for pt in left: lc.add(pt)
rc = adsk.core.ObjectCollection.create()
for pt in right: rc.add(pt)
sk.sketchCurves.sketchFittedSplines.add(lc)
sk.sketchCurves.sketchFittedSplines.add(rc)
sk.sketchCurves.sketchLines.addByTwoPoints(left[0], right[0])      # end caps
sk.sketchCurves.sketchLines.addByTwoPoints(left[N], right[N])
```

Bury each end ~2mm inside the bodies it connects, so the Join is solidly manifold rather than a coincident-face touch.

## 54. Detail-by-subtraction: draw detail as geometry, filter the profiles

Cheap way to get icon detail (robot eyes, an envelope flap line, a grille) without a second cut feature. Draw the detail shapes *inside* the outline in the same sketch; Fusion emits the outline-minus-details as one profile and each detail as its own. Extrude only what you want.

```python
def biggest(sk):
    best, ba = None, -1
    for i in range(sk.profiles.count):
        pr = sk.profiles.item(i)
        a = pr.areaProperties(adsk.fusion.CalculationAccuracy.LowCalculationAccuracy).area
        if a > ba:
            best, ba = pr, a
    c = adsk.core.ObjectCollection.create()
    c.add(best)
    return c, ba * 100.0     # mm^2
```

Variants:

- **Holes** (eyes, mouth): keep only the largest profile; the detail profiles are the holes.
- **Groove / engraved line** (envelope flap, seam): draw the detail as a thin closed *band*, then keep everything EXCEPT the band (sort by area, drop the smallest). A removed wedge cuts the outline open and reads wrong; a band leaves the outline intact and reads as an engraved line.
- Keep grooves at least ~1.0mm **perpendicular** width. A V-band of 1.5mm *vertical* thickness at 46 degrees is only 1.04mm perpendicular. Compute the real width, do not eyeball the sketch.
- To close a region using an existing edge, do **not** redraw that edge. Put your new curve endpoints exactly on its endpoints and reuse it. Duplicate coincident lines create slivers.

Always print every profile area before choosing; the split is asset-specific.

## 54b. Keyed tab + socket that survives a flat print

A locating key for a part that drops into a base. Beats a plain slot: a round or tangent edge in a straight slot is line contact and rocks; a rectangular tab cannot rotate.

Four constraints that all have to hold at once, and they fight each other:

1. **Weld.** The tab must root into real material, not a thin tangent. Bury it into the host and check the host is wider than the tab at the joint:

```python
dy = abs(tab_top_y - circle_cy)
half_chord = math.sqrt(R**2 - dy**2)
assert half_chord > tab_w/2, "tab is wider than its host at the joint"
```

2. **Visible face.** Inset the tab from the face that shows, so the host's outline stays clean.
3. **Printability.** Inset from ONE face only; keep it flush with the plate or it becomes an unsupported island (see gotchas). `tab_t = body_t - tab_inset`, extruded from Z=0.
4. **Seating.** Make the socket DEEPER than the tab is long, so the tab does not bottom out and the host's own edge takes the load:

```python
base_socket_d = tab_exp + 0.6        # 0.6mm of daylight under the tab tip
```

Socket plan size is `(tab_w + clear) x (tab_t + clear)`, and its centre shifts by `tab_inset/2` to keep the part centred in its mate (see gotchas).

```python
socket_cy = BASE_CY + tab_inset/2.0
part_back  = socket_cy + (tab_t + clear)/2.0 - clear/2.0
part_front = part_back - body_t
assert abs((part_front + part_back)/2.0 - BASE_CY) < 0.2
```

`clear` 0.3mm total (0.15/side) is a friction fit for FDM. Assert the mating volumes differ across thickness variants, or you will ship a socket that silently never tracked its parameter.

Note on poka-yoke: evenly spaced identical tabs will also seat rotated 180 degrees. If that matters, make one tab a different width; if the wrong orientation is obvious on sight, don't bother.

## 55. Trace a silhouette from a screenshot (pixel table to mm)

For sculptures or replicas of a screen UI. Pick ONE dimension as the driver, derive a px-to-mm scale, and express every coordinate through it. The screenshot's zoom level then cancels out entirely, so it does not matter what zoom the source image was captured at.

```python
S = 60.0 / 236.0          # DRIVER: known real size / its measured pixel width
CX, CY = 928.0, 506.0     # px of the feature you're treating as the origin

def X(pxx): return (pxx - CX) * S / 10.0   # cm, +X right
def Y(pxy): return (CY - pxy) * S / 10.0   # cm, +Y up (screen Y is inverted)
def L(pxl): return pxl * S / 10.0          # cm, a length
```

Verify by asserting the driver: the bounding box of the driver feature must come back at exactly the intended size (`X -30.00..30.00` for a 60mm driver). If it does, every other dimension is right by construction.

Honest limitation to disclose, not hide: this puts the layout in the *script*, not in sketch constraints. The extrudes stay parametric, but changing the driver parameter alone will NOT rescale the plan geometry; that needs a script re-run. Say so in the SKU README rather than implying the model is fully parametric.

## 56. Variant matrix from one design: name the axes into the filename

When a design grows mutually exclusive treatments (two face arts, two mount styles, two thicknesses), the export set multiplies. The failure mode is not the geometry, it is the **naming**.

The specific way it goes wrong: a design starts with one treatment, exports as `<SKU>-<mount>-t<n>`, then gains a second treatment. Re-exporting over the same filenames silently destroys the first treatment's files. The name had no room to say which treatment it held, so the second one just took its place. If the design also does not archive, those files are gone.

Rule: **the moment a design gains a second value on any axis, that axis belongs in the filename** — including for the files that already exist. Rename the originals rather than leaving them ambiguous.

```
<part>-<mount>-<face>-t<thickness>      # every axis explicit
bracket-stand-logo-t10
bracket-magnet-text-t10
```

Build the matrix with the expensive axis outermost, so the costly feature is built once per value rather than once per file:

```python
for face in ('logo', 'text'):        # outermost: rebuilding this is expensive
    set_face(root, plane, face)
    for mount in ('stand', 'magnet'):
        set_mount(root, mount)
        for t in THICKNESSES:
            bt.expression = f'{t} mm'
            assert settle(design, root, 2)
            assert_variant_invariants(sculpt(root), mount, t)   # per-variant, before export
            dump(em, sculpt(root), f'{SKU}-{mount}-{face}-t{t}')
```

Assert per-variant invariants **inside** the loop, not once at the end. Cheap ones that catch real mistakes: the Y-min that distinguishes the mounts, `Zmax == body_t + icon_t`, the X span. A variant that silently exported with the wrong mount's geometry is otherwise indistinguishable from a correct file until someone prints it.

Also disclose which axes are **not** visible in the bounding box. Two face treatments occupy the same face, so nothing in the geometry summary tells them apart. Record a discriminator in the SKU README (triangle count works: an imported-SVG logo carried 4,316 tris against a text treatment's 3,886) so a future reader can identify a stray file without opening CAD.

Finally: when an axis collapses (a thickness gets dropped), archive the retired files **with a README explaining why**, and check whether any of them were wrong. A dropped axis is the best moment to notice that its files never worked; see the volume-diff rule in `gotchas.md`.

## 57. Fit artwork to a print: measure the gaps, not the strokes

Before putting any logo, wordmark, or dense artwork on a part, work out the size it must be to survive the nozzle. The answer is usually driven by the **negative space between shapes**, not the shapes themselves, and it is usually much bigger than expected.

Two independent floors:

- **stroke**: a raised wall needs >= ~1 nozzle (0.4mm) to extrude at all
- **gap**: a valley between two raised walls needs ~2 nozzle widths (0.8mm) or the slicer merges them into a blob

Measure both from the source raster with a distance transform. The ridge (local maxima of the DT) along a shape's spine gives that shape's half-width; take a low percentile, not the global min, which is just antialiasing on every edge:

```python
def ridge(binary):
    dt = ndimage.distance_transform_edt(binary)
    mx = ndimage.maximum_filter(dt, size=3)
    r = (dt > 0) & (dt >= mx - 1e-9) & (dt > 1.0)
    return dt[r] * 2.0                      # full widths, px

strokes = ridge(ink)
gaps    = ridge(~ink & bbox_of(ink))        # restrict: outside the artwork is background
min_w_for_gaps = 0.8 * bbox_width_px / np.percentile(gaps, 5)
```

Report the **distribution**, not one number. "5th percentile" alone cannot tell a few pinch points from a systemically tight logo, and that difference decides whether you can ship it:

```
   width |  <0.4mm |  <0.6mm |  <0.8mm
    60mm |   12.6% |   37.3% |   55.7%     <- half the logo fuses. dead.
    90mm |    0.5% |   12.6% |   27.4%     <- borderline
   120mm |    0.5% |    1.5% |   12.6%     <- fine
```

### Trading stroke weight for gap width

If the strokes have headroom and the gaps do not (the common case for hand-lettered or display type), **erode the artwork**: eroding by k widens every gap by 2k while narrowing every stroke by 2k.

Erosion is only safe while **topology holds**. Check part and hole counts, not just widths, because the failure mode is letters snapping apart or counters closing:

```python
p0, h0 = ndimage.label(ink)[1], ndimage.label(~ink)[1] - 1
for k in range(0, 9):
    e = binary_erosion(ink, disk(k))
    p, h = ndimage.label(e)[1], ndimage.label(~e)[1] - 1
    ok = gap_p5(e) >= 0.8 and wall_p5(e) >= 0.5 and (p, h) == (p0, h0)
```

Real result: a wordmark needing **127mm** unmodified printed cleanly at **72.8mm** with 3px of erosion (0.17mm per edge, invisible), topology intact at 11 parts / 4 counters. At 7px the letters broke (11 -> 14 parts) while the widths still looked fine. **The width check passes long after the artwork has shattered; only the topology check catches it.**

Render an original / eroded / difference triptych and look at it. Numbers cannot tell you it still looks like the brand.

### Getting permission first

Eroding is **modifying someone's mark**. That is a design decision with a legal edge, not a technical one. Ask before doing it, and record who said yes. A licence to *use* a mark is not a licence to *redraw* it, and the person who owns it may care about 0.17mm more than you would guess.

## 58. Leaning cut groove (flute) via a perpendicular construction plane

A decorative flute that leans off vertical. Build it as a CUT, never as a joined proud rib: a joined
leaning cylinder overhangs the body top and bottom and needs trimming, whereas a cut is bounded by
the body for free.

Geometry: a cylinder of radius `rib_r` whose axis sits `rib_axis_off` OUTSIDE the face, so it bites
`rib_depth = rib_r - rib_axis_off` into the wall. Groove width at the surface is
`2 * sqrt(rib_r^2 - rib_axis_off^2)`.

```python
# rib_r 2.5, rib_depth 1.2 -> axis 1.3 outboard, groove 4.27 wide, 1.73 land at 6 pitch
params.add('rib_axis_off', VI('rib_r - rib_depth'), 'mm', 'COMPUTED')

# 1. plane offset outboard of the face (XZ shown; use yZ for an X-normal face)
pi = comp.constructionPlanes.createInput()
pi.setByOffset(comp.xZConstructionPlane, VI('face_y - rib_axis_off'))
plane = comp.constructionPlanes.add(pi)

# 2. the axis line. XZ mapping: sketch X = world X, sketch Y = -world Z.
#    Constrain the endpoint with TWO component distances, never an angular dim (see gotchas).
sk = comp.sketches.add(plane)
F = sk.sketchCurves.sketchLines.addByTwoPoints(P(x0, -z0, 0), P(x1, -z1, 0))
sk.geometricConstraints.addCoincident(F.startSketchPoint, sk.project(comp.zConstructionAxis).item(0))
sd = sk.sketchDimensions
sd.addDistanceDimension(sk.originPoint, F.startSketchPoint,
    DO.VerticalDimensionOrientation, t).parameter.expression = 'rib_z0'
sd.addDistanceDimension(F.startSketchPoint, F.endSketchPoint,
    DO.HorizontalDimensionOrientation, t).parameter.expression = 'rib_len * sin(rib_lean)'
sd.addDistanceDimension(F.startSketchPoint, F.endSketchPoint,
    DO.VerticalDimensionOrientation, t).parameter.expression = 'rib_len * cos(rib_lean)'
assert sk.isFullyConstrained
ws, we = F.worldGeometry.startPoint, F.worldGeometry.endPoint
assert we.z > ws.z, 'axis points downward'          # direction, not just constraint state

# 3. plane PERPENDICULAR to the axis at its start. Its origin lands exactly on the
#    line start and its normal follows the tangent, so a circle constrained to the
#    sketch origin is automatically centred on the axis.
pi2 = comp.constructionPlanes.createInput()
pi2.setByDistanceOnPath(F, adsk.core.ValueInput.createByReal(0.0))
npl = comp.constructionPlanes.add(pi2)

sk2 = comp.sketches.add(npl)
c = sk2.sketchCurves.sketchCircles.addByCenterRadius(P(0, 0, 0), 0.25)
sk2.geometricConstraints.addCoincident(c.centerSketchPoint, sk2.originPoint)
sk2.sketchDimensions.addDiameterDimension(c, t).parameter.expression = 'rib_r * 2'

# 4. one-sided cut along the axis; positive extent runs along the line direction
ci = ext.createInput(sk2.profiles.item(0), adsk.fusion.FeatureOperations.CutFeatureOperation)
ci.setDistanceExtent(False, VI('rib_len'))
ci.participantBodies = [body]
seed = ext.add(ci)
```

Then replicate with a **rectangular** pattern along the face, one set per planar face. Do NOT use
Pattern on Path with Path Direction: it discards the lean (see gotchas). Print angle 20 degrees from
vertical is 70 from horizontal, so flutes are self-supporting.

Verify the lean survived by querying the cut faces, not by looking at a screenshot:

```python
leans = [math.degrees(math.acos(abs(f.geometry.axis.z))) for f in body.faces
         if isinstance(f.geometry, adsk.core.Cylinder) and f.geometry.radius < 0.3]
print(min(leans), max(leans))      # must both equal rib_lean
```

## 59. Pattern on Path (when the seed really is perpendicular to the path)

Correct use: teeth on a belt, links on a chain, anything whose orientation SHOULD be derived from
the path. The path must be a proxy, and prefer a sketch curve over a body edge because any cut you
make along an edge fragments it.

```python
path = adsk.fusion.Path.create(
    line.createForAssemblyContext(occurrence),                 # proxy is mandatory
    adsk.fusion.ChainedCurveOptions.connectedChainedCurves)    # chains a closed loop

pp = comp.features.pathPatternFeatures
pin = pp.createInput(ents, path,
                     VI('floor(perimeter / pitch)'),           # quantity, parametric
                     VI('pitch'),
                     adsk.fusion.PatternDistanceType.SpacingPatternDistanceType)
pin.isOrientationAlongPath = True                              # UI "Path Direction"
pin.patternComputeOption = adsk.fusion.PatternComputeOptions.IdenticalPatternCompute
pp.add(pin).name = 'teeth'
```

`IdenticalPatternCompute` avoids the "too many pattern instances" warning that `Adjust` throws.

Drive quantity from an expression rather than the tutorial's measure-the-loop-and-paste-the-number
ritual: `'floor((2 * outer_w + 2 * depth) / pitch)'` keeps the pattern correct when the profile
changes. Instances that fall past the end of the path continue in a straight line from the endpoint
and simply cut nothing, so over-provisioning quantity is safe.

## 60. Restore-by-join: terminate a field of cuts on a clean boundary

See the gotchas entry for the full reasoning. The shape of the move:

```python
# 1. overrun: start each cut past the boundary so its angled end cap is buried
params.add('rib_z0', VI('plinth_h - rib_r'), 'mm', 'COMPUTED')

# 2. restore: join back the region that should have stayed solid, AFTER the cuts
ei = ext.createInput(outer_sketch.profiles.item(0),
                     adsk.fusion.FeatureOperations.JoinFeatureOperation)
ei.setDistanceExtent(False, VI('plinth_h'))
ei.participantBodies = [body]
ext.add(ei).name = 'plinth_band'
```

Reusing the body's own outer sketch profile keeps the restore exactly flush with the silhouette and
costs no new sketch.

## 61. Framed fluted panel (plinth, top ring, corner posts, mating pads)

A fluted field needs a frame, or it reads as damage: flutes sawtooth against the base, collide with
each other at corners, serrate the top rim, and stop parts seating flat against each other. Four
applications of section 60, all after the flute cuts:

| Boundary | Shape | Note |
|---|---|---|
| Bottom | outer profile, Z 0..`plinth_h` | also the natural home for tongue/groove keying |
| Top rim | **RING**: outer profile offset inward by ~2 mm, Z `h - top_band`..`h` | a solid block seals every cavity |
| Vertical corners | wall-thick square at one corner, patterned 2x2, full height | width capped by the nearest cavity; `wall` is always safe |
| Contact faces | pad on that face only, spanning the CONTACT height | modules differ in height, so only part of a face touches |

Ring profile selection:

```python
curves = adsk.core.ObjectCollection.create()
for l in outer_lines: curves.add(l)
sk.offset(curves, P(cx, cy, 0), 0.2)            # inward; creates a live offset constraint
profs = [(sk.profiles.item(i), sk.profiles.item(i).areaProperties().area)
         for i in range(sk.profiles.count)]
ring = min(profs, key=lambda t: t[1])[0]        # ring is the smaller of the two
```

Corner posts, seeded once and patterned to all four corners:

```python
ri = rp.createInput(ents, comp.xConstructionAxis, VI('2'), VI('outer_w - corner_band'), SPACING)
ri.setDirectionTwo(comp.yConstructionAxis, VI('2'), VI('depth - corner_band'))
```

Verify the frame by querying the flute Z range per body; it must equal
`plinth_h .. module_height - top_band` exactly.

**Accept one limit.** The flute adjacent to each corner post feathers to a point. A groove leaning
`a` degrees sweeps `h * tan(a)` horizontally over height `h`, so no vertical line ever sits between
flutes at every height. The sliver is thin enough that the slicer drops it.

## 62. Vertical dovetail interlock between stacked or abutting modules

The general problem: two parts meet on a flat vertical face and must not slide apart in use. Work
out which axes are ALREADY blocked before designing anything; usually only one is free, and that
determines the whole mechanism.

A plain rail in a blind groove blocks X (the groove is closed at both ends) and Z (the groove roof),
and leaves Y, the pull-apart direction, completely free. Resisting pull-apart needs an undercut, and
an undercut cannot be assembled by pushing along the axis it blocks, so it forces a sliding
assembly direction. A blind rail forbids sliding. The rail is therefore not fixable in place; the
assembly direction has to change.

**Run the dovetail vertically, never horizontally.** A dovetail is a prism. Extruded along Z, its
cross-section is constant in the horizontal plane, so every flank is a vertical wall and nothing
overhangs. The same dovetail run horizontally along a vertical face has a near-horizontal underside,
the worst possible FDM overhang. Printability picks the axis.

**Put the male on the TALLER part and the socket in the SHORTER one.** The socket has to run out
through the top of its part so the mating part can drop on. Cut it into the taller part and that
open slot is exposed above the joint. Cut it into the shorter part and the taller neighbour covers
it completely. This is what makes a dovetail viable between parts of unequal height, which is
usually why it gets wrongly rejected.

```python
# depth is bounded by the wall behind the socket -- check this FIRST
assert wall_solid - (dt_depth + dt_clear) > 1.2, 'socket leaves too little wall'

params.add('dt_depth',   VI('1.6 mm'), 'mm', 'engagement depth')
params.add('dt_w_root',  VI('12 mm'),  'mm', 'width at the mating face')
params.add('dt_angle',   VI('45 deg'), 'deg', 'flank angle from the pull axis')
params.add('dt_w_tip',   VI('dt_w_root + 2 * dt_depth * tan(dt_angle)'), 'mm', 'COMPUTED')
# socket: true parallel offset, so clearance is dt_clear NORMAL to every face
params.add('dt_sock_d',      VI('dt_depth + dt_clear'), 'mm', 'COMPUTED')
params.add('dt_sock_w_root', VI('dt_w_root + 2 * dt_clear / cos(dt_angle)'), 'mm', 'COMPUTED')
params.add('dt_sock_w_tip',  VI('dt_sock_w_root + 2 * dt_sock_d * tan(dt_angle)'), 'mm', 'COMPUTED')
# mouth overrun keeps the cut off the body boundary; extend along the same flank lines
params.add('dt_mouth_w', VI('dt_sock_w_root - 2 * dt_over * tan(dt_angle)'), 'mm', 'COMPUTED')
```

Sketch the trapezoid on the **XY plane** and extrude along Z. Narrow at the mating face, wide at the
tip. Jitter the two flat edges so Fusion does not auto-infer horizontal (see gotchas), constrain
them explicitly, then dimension the remaining 6 DOF.

```python
pts = [(cx - w_root/2, y_f), (cx + w_root/2, y_f + J),
       (cx + w_tip/2,  y_f - d), (cx - w_tip/2,  y_f - d + J)]
```

| Feature | Operation | Extent |
|---|---|---|
| male, on the taller part | Join | `setDistanceExtent(False, '<shorter_part_height>')` |
| socket, in the shorter part | Cut | `setDistanceExtent(False, '<its_height> + 5 mm')`, through the top |

Mirror the seed about the YZ plane for the second dovetail; two per joint blocks rotation about Z.

Lead-in chamfer on the male top, sized so the chamfered top is narrower than the socket mouth, makes
the drop-on self-aligning. Select its edges by world coordinates, not by face, because the male's
top face may merge with coplanar neighbours (see gotchas).

Verify: `body.volume` delta against `2 * ((w_root + w_tip) / 2) * depth * height` for the male and
the socket equivalent, then an interference check across every body. Zero pairs plus a bounding box
that reaches into the neighbour's territory proves capture.

**What this locks.** X and Y fully; down-Z is whatever the parts sit on; up-Z is the intended
removal direction. That is a complete lock for anything resting on a surface. Add a detent only if a
fit-check print feels loose, and only if some member can actually flex the detent height; a 1.6 mm
wall over a 16 mm span reads as a hard push, not a click.

## 63. Sheared prism via loft (a leaning body with a flat base)

Fusion refuses shear transforms (see gotchas), so build the shear geometrically. Both profiles are
identical; only the upper one's anchor carries the lateral offset. The result has horizontal top and
bottom faces, a full flat footprint, and no wedge.

```python
LEAN = math.radians(15.0)
lean_off = 103.0 * math.tan(LEAN)

ci = root.constructionPlanes.createInput()
ci.setByOffset(root.xYConstructionPlane, VI('shell_h'))
pl_top = root.constructionPlanes.add(ci)
pl_top.name = 'top_plane'

# both rectangles are outer_w x outer_d; the top one is anchored at lean_off + outer_d/2
sk_bot = rect_sketch('body_bot', root.xYConstructionPlane, 'outer_w + 0 mm', 'outer_d + 0 mm',
                     0.0, 0.0, 'outer_w / 2', 'outer_d / 2')
sk_top = rect_sketch('body_top', pl_top, 'outer_w + 0 mm', 'outer_d + 0 mm',
                     0.0, lean_off, 'outer_w / 2', 'lean_off + outer_d / 2')

lofts = root.features.loftFeatures
li = lofts.createInput(adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
li.loftSections.add(sk_bot.profiles.item(0))
li.loftSections.add(sk_top.profiles.item(0))
li.isSolid = True
body = lofts.add(li).bodies.item(0)

# Cavalieri: a shear preserves volume. Free check that the loft did what you meant.
assert abs(body.volume - 130.0 * 90.0 * 103.0 / 1000.0) < 0.01
```

Fillet the LEANING corner edges by matching direction against the lean vector, since they are no
longer parallel to Z:

```python
u = adsk.core.Vector3D.create(0.0, math.sin(LEAN), math.cos(LEAN))
edges = adsk.core.ObjectCollection.create()
for e in body.edges:
    g = e.geometry
    if not isinstance(g, adsk.core.Line3D):
        continue
    s, t = g.startPoint, g.endPoint
    d = adsk.core.Vector3D.create(t.x - s.x, t.y - s.y, t.z - s.z)
    if d.length < 1e-9:
        continue
    d.normalize()
    if abs(abs(d.dotProduct(u)) - 1.0) < 1e-6:
        edges.add(e)
assert edges.count == 4
```

Volume removed by four corner fillets: `4 * r^2 * (1 - pi/4) * (height / cos(lean))`.

Hollow it with a Shell feature removing the two HORIZONTAL faces. That offsets perpendicular to
every face, which is what a leaning wall needs, and derives the inner corner radii for free.
Expected wall volume by horizontal slices, noting the `1/cos` terms:

```python
c = math.cos(LEAN)
outer_a = W * D - 4 * (R * R / c) * (1 - math.pi / 4)
inner_a = (W - 2*t) * (D - 2*t/c) - 4 * ((R - t) ** 2 / c) * (1 - math.pi / 4)
assert abs(body.volume - (outer_a - inner_a) * H / 1000.0) < 0.05
```

## 64. Through-cut lattice: one seed cuts two opposite walls

A seed sketched on XZ at y=0 and cut with a symmetric through-extent removes material from the FRONT
and REAR walls in one feature. Same on YZ for left and right. Four sketches, four cuts and four
patterns produce a 170-opening lattice, and opposite faces are perfectly phase-aligned because they
are literally the same feature.

```python
ei = exts.createInput(sk.profiles.item(0), adsk.fusion.FeatureOperations.CutFeatureOperation)
ei.setSymmetricExtent(VI('outer_d * 3 + 40 mm'), True)    # over-provisioned: no direction to fumble
ei.participantBodies = [body]
cut = exts.add(ei)

per_wall = hex_area * wall            # vertical wall
per_wall = hex_area * wall / math.cos(LEAN)   # leaning wall: the Y prism traverses more material
assert abs(removed - 2 * per_wall) < 1.0, 'seed did not cross exactly two walls'
```

Preconditions to check from the field maths BEFORE building: the field must stay inside the flat
face region on BOTH walls, and the cut must not clip the adjacent walls.

Honeycomb field maths, for opening circumradius `r` and member `m`:

```
across_flats = sqrt(3) * r      col_pitch = sqrt(3) * r + m
across_points = 2 * r           row_pitch = 1.5 * r + (sqrt(3)/2) * m
N    = floor((flat_width - across_flats) / col_pitch) + 1
land = (flat_width - ((N - 1) * col_pitch + across_flats)) / 2
```

Express `N` in Fusion with `floor()`, which works in expressions, so the counts stay parametric.
Do NOT simplify to `floor(flat_width / col_pitch)`: it agrees at some widths and silently returns one
column too many at others, putting a clipped sliver against the corner.

## 65. Rectangular pattern direction: retry by volume, never by reasoning

Pattern direction is unpredictable and fails QUIETLY. Instances land outside the body, remove
nothing, and no error is raised. Build, compare removed volume against expectation, and negate on
mismatch. Loop all four sign combinations; it costs nothing when it is not needed.

```python
def build_pattern(pats, feat, body, ax1, q1, d1, ax2, q2, d2, expected):
    v1 = body.volume
    for s1 in ('', '-'):
        for s2 in ('', '-'):
            p = pats.createInput(adsk.core.ObjectCollection.create(), ax1, VI(q1),
                                 VI(f'{s1}{d1}'),
                                 adsk.fusion.PatternDistanceType.SpacingPatternDistanceType)
            p.inputEntities.add(feat)
            p.setDirectionTwo(ax2, VI(q2), VI(f'{s2}{d2}'))
            f = pats.add(p)
            if abs((v1 - body.volume) * 1000.0 - expected) < 1.0:
                return f
            f.deleteMe()
    raise AssertionError('pattern never matched expected removal')
```

To shear a field so it follows a leaning wall, pass a construction line along the lean as direction
two with step `row_pitch / cos(lean)`. That gives exactly `row_pitch` of vertical rise per row and
holds the horizontal corner land constant on every row. `ConstructionAxes.setByLine` is rejected in
the parametric environment; a sketch construction line works.

## 66. Verify a slip fit by measurement, not by interference

`interference_check` returns 0 pairs for a zero-clearance press fit as readily as for a correct one.
Measure the gap along each face normal, and assert BOTH the per-side gap and that the part is centred
in the opening, since a correct total gap can sit entirely on one side.

```python
def offsets(body, nx, ny, nz):
    out = []
    for f in body.faces:
        g = f.geometry
        if not isinstance(g, adsk.core.Plane):
            continue
        n = g.normal
        if abs(abs(n.x * nx + n.y * ny + n.z * nz) - 1.0) > 1e-5:
            continue
        o = g.origin
        out.append(round((o.x * nx + o.y * ny + o.z * nz) * 10, 4))
    return sorted(set(out))

sp = [v for v in offsets(shell, nx, ny, nz) if abs(abs(v) - expected_shell) < 0.05]
ip = [v for v in offsets(insert, nx, ny, nz) if abs(abs(v) - expected_insert) < 0.05]
assert len(sp) == 2 and len(ip) == 2, 'filter caught pattern facets; tighten the band'
s_lo, s_hi, i_lo, i_hi = min(sp), max(sp), min(ip), max(ip)
assert abs((i_lo - s_lo) - gap) < 2e-3 and abs((s_hi - i_hi) - gap) < 2e-3
assert abs(((i_hi + i_lo) / 2) - ((s_hi + s_lo) / 2)) < 1e-6, 'gap all on one side'
```

**Band the filter tightly.** A patterned or pocketed body has hundreds of planar faces sharing a
normal, and a naive min/max picks up the pattern facets.

For rounded corners, slide each cylinder axis to a common plane and assert the axes coincide, which
is what makes the clearance uniform round the corner rather than varying:

```python
t = -o.z / u.z                                    # o = cylinder origin, u = axis direction
key = ((o.x + t * u.x) * 10, (o.y + t * u.y) * 10)
```

## 67. Design variants as suppressible cut blocks in ONE document

When a product ships several versions of one feature (four shell patterns over an identical body),
do not duplicate the document. The shell solid, fillet, hollow and the entire second part are
identical across variants, so a copy per variant is four copies of the part that is not changing,
and every later fix has to be applied four times.

Build each variant as a named block of features and suppress all but one:

```python
GROUPS = {'hex':      ('hex_cut_', 'hex_pattern_'),
          'diamond':  ('dia_cut_', 'dia_pattern_'),
          'dogtooth': ('tth_cut_', 'tth_pattern_'),
          'flower':   ('flw_L_cut_',)}
ALL = tuple(p for g in GROUPS.values() for p in g)

def activate(which):
    for i in range(tl.count):
        n = tl.item(i).name
        if n.startswith(ALL):
            tl.item(i).isSuppressed = not n.startswith(GROUPS[which])
```

Rules that make this safe:

- **Prefix every feature in a block.** The prefix IS the grouping mechanism; a stray unprefixed
  feature will never be suppressed and will silently apply to every variant.
- **Shared entities must sit outside all blocks.** A construction sketch used as a pattern direction
  by several blocks (`lean_ref`) belongs to none of them and must never be suppressed.
- **Set `participantBodies` on every cut.** Variant blocks are appended to the END of the timeline,
  so unlike the original block they run AFTER other bodies exist, and a symmetric through-extent
  will happily slice them. Verify by asserting the other body's volume and face count are unchanged.
- **Assert the face count after activating**, before exporting. It is the cheapest proof that the
  right block is live.

## 68. Verify an opening count by face arithmetic, not by looking

A patterned shell has an exact face count, and it is the strongest cheap check available:

```
faces = base_faces + openings * edges_per_opening
```

`base_faces` is the un-patterned hollow body: for a filleted rectangular sleeve it is 4 outer planes
+ 4 outer cylinders + 4 inner planes + 4 inner cylinders + top ring + bottom ring = **18**. Confirm
it once by suppressing every cut block and reading `body.faces.count`.

Then each clean through-opening contributes one face per edge of its profile:

| pattern | openings | edges each | expected | got |
|---|---|---|---|---|
| pointy-top hex | 170 | 6 | 18 + 1020 = 1038 | 1038 |
| diamond | 254 | 4 | 18 + 1016 = 1034 | 1034 |
| 9-gon dogtooth | 64 | 9 | 18 + 576 = 594 | 594 |
| arc cells | 136 | 2 or 3 arcs | 18 + 656 = 674 | 674 |

This catches everything that matters: a pattern instance that landed off the body removes nothing
and the count drops; two openings that merged produce fewer faces than the sum; a clipped opening
merges with the outer surface and breaks the arithmetic entirely. A screenshot catches none of the
three.

If the count is wrong it is nearly always pattern direction. Negate the distance and rebuild rather
than reasoning about which way Fusion went (section 65).

## 69. Analytic cell decomposition, handed to Fusion as three-point arcs

For any pattern defined as the FACES of an arrangement of overlapping curves, Fusion cannot compute
the arrangement (gotchas.md, "Sketch profile computation does not scale"). Derive the cells offline
and draw them as finished closed loops.

The property that makes this exact for circle arrangements: each cell is the intersection of
inside-discs and outside-disc-complements, so insetting by half the member width keeps every
bounding curve a circular arc on the SAME centre.

```
cell       = { p : |p-c| <= R        for c in IN } and { p : |p-c| >= R        for c in OUT }
inset cell = { p : |p-c| <= R-mem/2  for c in IN } and { p : |p-c| >= R+mem/2  for c in OUT }
```

No offset curves, no approximation, no polyline fallback.

Procedure:

1. Sample the field to discover which containment signatures actually occur. Each distinct
   signature is a cell.
2. Per signature, intersect every pair of constraint circles at their INSET radii; keep the points
   satisfying all remaining constraints.
3. Sort the surviving points by angle about their centroid.
4. For each consecutive pair, choose the arc whose MIDPOINT also satisfies every constraint.
5. Emit `(centre, radius, a1, a2, ccw)` and draw with `addByThreePoints(start, mid, end)`.

**The trap: a two-arc cell must take its two arcs from DIFFERENT circles.** For a lens both bounding
circles pass the midpoint test, so a "smallest sweep wins" rule picks the same circle twice, traces
out and back, and collapses the cell to a zero-area sliver. Nothing errors. The symptom is that only
the higher-order cells survive and open area reads roughly a third of what it should. Track the
previous arc's circle and exclude it.

Fusion needs no coincident constraints if endpoints are computed from the same arc data: 208 arcs
describing 86 cells resolved to exactly 86 profiles.

```python
def arc_triple(A):
    d = ((A['a2']-A['a1']) % (2*math.pi)) if A['ccw'] else -((A['a1']-A['a2']) % (2*math.pi))
    return [(A['cx'] + A['r']*math.cos(a), A['cy'] + A['r']*math.sin(a))
            for a in (A['a1'], A['a1'] + d/2, A['a2'])]
```

Cross-validate the generator by rasterising ITS OUTPUT (not the original curves) and comparing open
area against an independent estimate. That is what exposed the lens bug.

The cost is parametricity: the sketch carries literal coordinates and will not rescale with the
drivers. Budget one block per size, named accordingly, and keep the generator script beside the CAD
source rather than in a scratch directory.

## 70. Jittered polygon seed: a constrained N-gon Fusion will actually accept

Combines the gotchas "numerically redundant dimension" and "inferred constraints survive
isComputeDeferred" into one helper. Use for any opening profile that is not a regular polygon, where
`addScribedPolygon` does not apply.

```python
def seed(name, plane, pts, u_exprs, v_exprs, tp):
    """pts: sketch-space vertices (cm). u_exprs/v_exprs: |distance from origin| per vertex."""
    sk = root.sketches.add(plane); sk.name = name
    sk.isComputeDeferred = True
    L = sk.sketchCurves.sketchLines
    jit = [(0.005*(k+1)*(1 if k % 2 else -1), 0.004*(k+1)*(-1 if k % 2 else 1))
           for k in range(len(pts))]
    jp = [P(x+jx, y+jy, 0) for (x, y), (jx, jy) in zip(pts, jit)]
    lines = [L.addByTwoPoints(jp[0], jp[1])]
    for k in range(1, len(jp)-1):
        lines.append(L.addByTwoPoints(lines[-1].endSketchPoint, jp[k+1]))
    lines.append(L.addByTwoPoints(lines[-1].endSketchPoint, lines[0].startSketchPoint))
    while sk.geometricConstraints.count:
        sk.geometricConstraints.item(0).deleteMe()
    sk.isComputeDeferred = False
    assert sk.geometricConstraints.count == 0
    sd = sk.sketchDimensions
    verts = [lines[0].startSketchPoint] + [l.endSketchPoint for l in lines[:-1]]
    for k, (pt, ue, ve) in enumerate(zip(verts, u_exprs, v_exprs)):
        sd.addDistanceDimension(sk.originPoint, pt, DO.HorizontalDimensionOrientation,
                                P(tp[0] + 0.3*k, tp[1], 0)).parameter.expression = bare(ue)
        sd.addDistanceDimension(sk.originPoint, pt, DO.VerticalDimensionOrientation,
                                P(tp[0], tp[1] - 0.3*k, 0)).parameter.expression = bare(ve)
    assert sk.isFullyConstrained, f'{name}: under-constrained'
    assert sk.profiles.count == 1, f'{name}: {sk.profiles.count} profiles'
    return sk
```

Every expression is an unsigned distance from the origin, so keep the seed away from the axes and
check the smallest is comfortably positive before building. `bare()` appends `+ 0 mm` to a lone
parameter name to dodge the G6 bare-name freeze.

## 71. Generated silhouette: draw offline, gate offline, hand Fusion finished loops

For decorative flat-plate art (mountain skylines, city outlines, lattice scenes) the drawing is not
parametric CAD work and should not be attempted as such. The pipeline that works:

1. **A generator module** holds every driver and emits the drawing as closed loops in mm, plus a
   `geometry.json` of derived numbers for cross-checking the CAD. Use a seeded LCG, not
   `random.seed`, so it reproduces across Python versions.
2. **A rasteriser** renders the front elevation at 0.1 mm and runs printability gates (section 72).
   It paints failures onto a preview PNG and prints per-region bounding boxes in mm.
3. **A scanline union area** over the same loops, so the CAD has something independent to be checked
   against. Sample rows at `z0 + (i + 0.5) * dz` and merge per-row intervals; stable from
   dz 0.01 down to 0.002.
4. **Fusion** reads the loops from JSON and chains `sketchLines.addByTwoPoints`, passing the previous
   `SketchPoint` as the new start so vertices stay coincident. 568 points build in seconds with
   `isComputeDeferred = True`.
5. **Classify profiles** (section 72) and extrude the survivors as one Join.
6. **Reconcile the volume** against step 3.

The sketch carries literal coordinates and no dimensions. That is inherent, not a defect: say so in
the SKU README, and note that changing any size driver means re-running the generator and rebuilding
that one feature. Everything *else* in the model stays fully parametric.

```python
loops = json.load(open(SRC))['loops']
sk = root.sketches.add(root.xYConstructionPlane)
sk.isComputeDeferred = True
lines = sk.sketchCurves.sketchLines
for lp in loops:
    seg = lines.addByTwoPoints(P(lp[0][0] / 10.0, lp[0][1] / 10.0, 0),
                               P(lp[1][0] / 10.0, lp[1][1] / 10.0, 0))
    first, prev = seg.startSketchPoint, seg.endSketchPoint
    for x, y in lp[2:]:
        prev = lines.addByTwoPoints(prev, P(x / 10.0, y / 10.0, 0)).endSketchPoint
    lines.addByTwoPoints(prev, first)
sk.isComputeDeferred = False
```

## 72. Classify arrangement profiles by a guaranteed interior point

Overlapping loops make the enclosed voids into profiles too, and a centroid is not reliably inside
its own profile (gotchas.md). Build the outer ring from the profile's own curves, then sample inward
off each edge midpoint.

```python
def chain(segs):
    """Order an unsorted bag of (p, q) segments into a closed ring."""
    ring, used = [segs[0][0], segs[0][1]], {0}
    while len(used) < len(segs):
        tail = ring[-1]
        for k, (a, b) in enumerate(segs):
            if k in used:
                continue
            if abs(a[0] - tail[0]) < 1e-6 and abs(a[1] - tail[1]) < 1e-6:
                ring.append(b); used.add(k); break
            if abs(b[0] - tail[0]) < 1e-6 and abs(b[1] - tail[1]) < 1e-6:
                ring.append(a); used.add(k); break
        else:
            break
    return ring[:-1]


def outer_ring(prof):
    for lp in prof.profileLoops:
        if not lp.isOuter:
            continue
        segs = []
        for pc in lp.profileCurves:
            g = pc.geometry                       # all SketchLine -> Line3D here
            segs.append(((g.startPoint.x * 10, g.startPoint.y * 10),
                         (g.endPoint.x * 10, g.endPoint.y * 10)))
        return chain(segs)


def votes(ring, loops, step=0.05):
    """Majority vote over interior samples. step must be under the smallest feature."""
    n = len(ring)
    a2 = sum(ring[i][0] * ring[(i + 1) % n][1] - ring[(i + 1) % n][0] * ring[i][1]
             for i in range(n))
    sgn = 1.0 if a2 > 0 else -1.0                 # CCW -> interior is left of travel
    yes = no = 0
    for i in range(n):
        ax, ay = ring[i]
        bx, by = ring[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        if L < 1e-6:
            continue
        px = (ax + bx) / 2 - sgn * dy / L * step
        py = (ay + by) / 2 + sgn * dx / L * step
        if not pip(px, py, ring):                 # sample escaped a thin profile
            continue
        if any(pip(px, py, lp) for lp in loops):
            yes += 1
        else:
            no += 1
    return yes, no
```

Profiles where both counts come back zero are thinner than `2 * step` and can be dropped; on a
250 mm part that was one profile well under a nozzle width. **The volume reconciliation is what
proves the classification** — the vote is a heuristic, the area is not.

## 73. Rebuild one mid-timeline feature in place, not appended

Deleting and re-adding a feature appends it to the end of the timeline, which reorders it relative to
everything downstream. For a Join that later features cut into, or a fillet whose chain overlaps
another fillet, that changes the result silently.

```python
tl = design.timeline
for i in range(root.features.count):
    if root.features.item(i).name == 'ex_skyline':
        root.features.item(i).deleteMe()
        break
sk = root.sketches.itemByName('sk_skyline')
if sk:
    sk.deleteMe()

idx = [i for i in range(tl.count) if tl.item(i).name == 'ex_plate'][0]
tl.markerPosition = idx + 1        # new features insert HERE
# ... build the sketch and feature ...
tl.moveToEnd()
```

Then diff the feature-name list: deleting a Join takes downstream fillets with it (gotchas.md), so
restore them at their original slots, also via `markerPosition`. Verify by volume, and print the last
few timeline names to confirm the order.

## 74. Self-supporting ramp as a loft between two XY-plane profiles

To grow a wedge or ramp off a prismatic feature without sketching on YZ (which inverts sketch X to
negative world Z), loft between two rectangles on offset XY planes:

```python
# plane A at the ramp start, plane B at its end
pi_ = planes.createInput(); pi_.setByOffset(root.xYConstructionPlane, VI('z_wedge_near'))
# ... section A: pier_w x hook_t
# ... section B: pier_w x (hook_t + hook_up)
li = lofts.createInput(adsk.fusion.FeatureOperations.JoinFeatureOperation)
li.loftSections.add(secA)
li.loftSections.add(secB)
li.participantBodies = [body]
```

The loft's swept face is planar at `atan( rise / run )` off the build direction, so the ramp angle is
**derived from the two dimensions and never typed**. Volume is the exact triangular prism
`width * rise * run / 2`, which asserts to four decimals.

Used for a printed hook: the arm extrudes flat, the loft adds the upturned tip at 39.8 degrees off
print Z, and nothing overhangs.

## 75. Nozzle-relative printability gates for flat-plate art

Three raster checks over the front elevation, at 0.1 mm/px. All three failed for the wrong reasons on
the first attempt; these are the corrected forms.

| check | method | threshold |
|---|---|---|
| connectivity | flood fill from a known-solid seed; count unreached material px | 0 |
| min feature | morphological opening at `MIN_FEATURE`, then per-blob area | 0.9 mm, no region > 2.0 mm^2 |
| min gap | same on the inverted image | 0.9 mm, no region > 1.5 mm^2 |

**Fail on individual REGIONS, not on total percentage of area lost.** A square-kernel opening cannot
distinguish *narrow* from *short*, so a percentage gate condemns every blunt summit and every tree
apex. Worse, the wedge of sky between any two overlapping shapes always tapers to a point, so it
always trips.

**Set the failing threshold at nozzle scale, not structural comfort.** 1.6 mm (4 perimeters) reads as
a sensible minimum and it vetoes intentional sharp points, which on a 5 mm plate print fine and just
round by about a nozzle. 0.9 mm (2 line widths) is where the printer genuinely cannot lay material.
Keep 1.6 mm as an advisory report: it says how delicate the drawing is without being a gate.

**Paint the failures onto the preview and print per-region bounding boxes in mm.** "0.9% of sky lost"
does not tell you what to fix; "1.78 mm^2 at x -68.2..-66.7, z 11.1..13.5" does.

The dominant defect these catch is not thin limbs, it is the **near-miss**: two boundaries passing
0.12 to 0.90 mm apart, or crossing at a shallow tangential angle. Five of them on one part. Shapes
must either clearly overlap or clearly separate; the near-miss is the only bad case, and it is
invisible at any zoom level a human would use.
