# Fusion MCP Gotchas

Failure modes from production sessions plus stress-test findings. Each entry: what happens, why, the fix.

## Lock-badge display lag on standalone script-built sketches (G9 corrected 2026-05-31)

A sketch that is built by a script AND is not immediately consumed by a downstream feature in the same script can be fully constrained AND have a working parametric link to user parameters, while its browser-tree icon shows NO lock badge until you enter edit mode once. After exiting edit mode the badge stays. `design.computeAll()` does NOT force the badge to update.

Sketches that ARE immediately consumed by an extrude / cut / revolve / etc. in the same script render their lock badge correctly right away. The feature creation appears to force the UI refresh. Verified in the claude-test mounting plate build, 2026-05-31: `plate_outline` (consumed by extrude) and `hole_outline` (consumed by cut) both showed lock badges immediately; the earlier standalone `claude_test_g9_*` lab sketches did not.

This is purely cosmetic. The constraint state was correct the whole time. The API flag (`Sketch.isFullyConstrained`) is honest. The geometry follows parameter changes correctly.

**What this gotcha replaces.** An earlier version of this entry claimed parameter-name expressions in sketch dims silently fail to constrain the geometry. That claim was wrong and was the result of taking the absent lock badge as evidence of constraint failure without testing parametric propagation. Parameter-name expressions in sketch dimensions do constrain geometry correctly; verify with a parametric round-trip rather than the browser-tree badge.

**How to verify a sketch is really constrained without entering edit mode:**

1. Check `Sketch.isFullyConstrained` — should be True.
2. If the sketch dim uses a parameter expression: change the parameter value programmatically, call `design.computeAll()`, then read the dim's `parameter.value`. If it tracks the parameter change, the parametric link is live. If it stays frozen, something is genuinely broken.
3. Browser-tree badge absence alone is not evidence of failure.

**Open question.** Whether `Sketch.activate()` (or equivalent) forces the badge to render without requiring the user to click in. Untested; would let a canonical sketch helper leave visibly-locked sketches behind.

**Rule.** Trust `isFullyConstrained` plus a parametric round-trip. Don't trust the badge for state, only for "user-visible-confirmation."

## Lock-badge advice from older sessions

A previous entry in this file said the lock badge is ground truth and `isFullyConstrained` can lie. We have NOT reproduced a case where `isFullyConstrained` returns True for an actually-broken sketch in current Fusion (May 2026 build). The cases the previous advice was rooted in may have been the same display-lag misobservation that the corrected G9 above documents. If you do hit a case where the API flag and the live parametric round-trip disagree, log it as a new gotcha with a reproducer.

In-canvas line colors are still a useful tell when you ARE in edit mode: black = driving + fully constrained, blue = driving + under-constrained, red = over-constrained / conflict. The small red "pencil tip" in the default sketch icon is NOT a constraint indicator.

## Sketch plane orientation surprises

**XY plane (safe default).** Sketch X maps to world X, sketch Y maps to world Y. Extrude in `+Z` direction goes up. No surprises.

**XZ plane.** Sketch X maps to world X. Sketch Y maps to NEGATIVE world Z. For Z-up geometry, negate all Y values in your vertex list. A typical symptom: a side-profile bracket drawn Y-flipped on first attempt, only caught by the bounding box because the iso-top-right screenshot still looked plausible.

**YZ plane (`yZConstructionPlane`).** Sketch X maps to NEGATIVE world Z (inverted). Sketch Y maps to POSITIVE world Y. Normal/extrude direction is world X. So "up" in the sketch is sketch X with an inverted sign relative to world Z, and the sketch's vertical axis is sketch X, not Y. To place a point at world Z=80, use sketch X = -80; for world Y=20, use sketch Y = +20.

Verified universal in current Fusion (build `4bca736941837d3e42bba21bb36b9891e34b2fce`, May 2026) across two independent documents with a `worldGeometry` repro: a sketch point at (0.5, 1.0) cm reads world (0, 10mm, -5mm). Re-confirm if plane behavior changes in a future build. (The original guess for this entry was wrong, caught by the Dell-bracket session.)

**Habit for any non-XY plane.** Before committing to a coordinate scheme, drop one test `sketchPoint` and read its `worldGeometry` to confirm the mapping. Five lines, saves a full re-orientation debug cycle. See patterns.md N8 for a constrained yZ-plane worked example.

**Rule.** Default to XY for top-down designs (trays, panels, anything that lays flat). XZ for side-profile parts (brackets, arms), remembering to negate Y. Avoid YZ unless extrusion along world X is specifically wanted.

## Self-intersecting polygon returns `profiles.count == 2`

A polygon where two edges cross internally (e.g. an 8-vertex Z-profile where edges V8 to V1 cross V5 to V6, producing a figure-8) is treated by Fusion as TWO closed profiles, not an error. The extrude succeeds and produces wrong geometry.

**Rule.** Always `assert sk.profiles.count == <expected>` immediately after `sk.isComputeDeferred = False`. Print the count if uncertain. Bail before extruding.

Profile count of 0 means the polygon did not close (vertex typo or float mismatch).

## Undo wipes whole-script transactions silently

`update(undo)` reverses the last `execute` as ONE atomic transaction. If that script added params AND created geometry, undo wipes both. Common symptom: "wait, why are these params missing?" several scripts later.

**Same rollback on exception-driven failure.** It is not only user undo. If a script throws partway (say, on `params.add` call 6 of 25), the 5 adds that already succeeded are silently wiped too. The tool error shows the traceback for the failing call but does NOT report which prior changes rolled back. Re-running an idempotent script after the fix then picks up from the last committed state, not the failed transaction's intermediate state.

**Rule.** Make every script idempotent (params, bodies, sketches all checked-and-added). When rollback is plausible, split into two `execute` calls: params first, geometry second. Prefer the delete-loop cleanup over undo when resetting geometry.

## `apiDocumentation` with null apiCategory returns empty silently

Omitting `apiCategory` returns `{"message": "API documentation query completed", "success": true}` with NO data. Looks like success.

**Rule.** Always set `apiCategory` to `"member"`, `"class"`, `"description"`, or `"all"`.

## Internal units are cm, not mm

`userParameters.itemByName(name).value` returns CM. `Point3D.create(x, y, z)` takes CM. A 30mm parameter has `.value == 3.0`.

`ValueInput.createByString('30 mm')` accepts unit suffixes and Fusion converts. Use this for human-readable expressions.

**Trap.** Treating `.value` as mm and multiplying sketch coords by 10 doubles every dimension.

**Rule.** Only multiply by 10 when PRINTING dimensions for human display. Math inside scripts stays in cm.

## Screenshot `direction: "current"` auto-fits in most cases, but not all

`direction: "current"` auto-fits the camera to show the body in the common case. It does NOT preserve the current viewport camera; it re-fits.

Two known failure modes:

- Untitled docs: auto-fit is unreliable, often returns an empty frame.
- Immediately after script-driven feature additions: the camera may not have settled, fit can miss.

**Rule.** Always run the explicit fit-view block (patterns.md section 20) before screenshotting. Treat `direction: "current"` auto-fit as a happy-path bonus, not a guarantee.

## Camera reset has no MCP primitive (CLOSED 2026-05-22)

Resolved via the Python API from within an `execute` script. The MCP itself doesn't expose a camera primitive directly, but Fusion's `activeViewport.fit()` does what's needed:

```python
vp = app.activeViewport
vp.fit()
cam = vp.camera
cam.viewOrientation = adsk.core.ViewOrientations.IsoTopRightViewOrientation
cam.isFitView = True
vp.camera = cam
vp.refresh()
```

See patterns.md section 20. Verified across multiple successive design iterations; produces consistent framing every time.

Previous workarounds (asking the user to press Home, or hoping `direction: "current"` happened to do the right thing) are no longer needed.

## Named-direction screenshots still need an explicit fit-view call

Closing the camera-reset gap (above) does NOT change the fact that named directions like `iso-top-right` don't auto-fit on their own. If you call `read` screenshot with a named direction WITHOUT first running the `vp.fit()` pattern from patterns.md section 20, the result is whatever zoom the viewport happened to be at, often a tight crop or empty frame.

**Rule.** For deterministic screenshots, ALWAYS run the patterns.md section 20 fit-view block first, then take the screenshot. Even for `direction: "current"`. Controlling the camera explicitly is more reliable than depending on screenshot-side auto-fit behavior.

## `setOneSideExtent` with fixed distance stops at obstructions

A counterbore cut using `setDistanceExtent(floor_thickness)` to cut up from a gusset bottom can stop short when the gusset itself sits below the sketch plane. The fixed distance only clears the upper feature, leaving the cut blocked.

**Rule.** When geometry below the sketch plane is variable or unknown depth, use `setAllExtent(direction)` for cut and intersect operations. Cuts through everything in that direction.

## Do not catch exceptions in `run()`

```python
# BAD
def run(_context: str):
    try:
        # ... work ...
    except Exception as e:
        print(f"failed: {e}")  # loses the traceback
```

The MCP returns Python exceptions with full traceback as the tool error. Catching them turns a 30-second fix into a 10-minute debug because the line number and stack frame are gone.

**Rule.** Let exceptions propagate. Trust the tool error path.

## Counterbore vs countersink direction

For parts where screws drive upward into the part (e.g. mounting brackets installed from below), the counterbore must be cut UP from the screw-tab bottom, not DOWN from the top. Easy to get wrong on the first attempt by defaulting to "screw enters from the top".

**Rule.** Trace the actual screw direction in the install before placing the counterbore. Place the counterbore sketch on a plane positioned at the bottom-facing side, then `setAllExtent(NegativeExtentDirection)` to cut up.

## Save on Untitled documents fails via MCP

Calling `execute document save` on a never-saved doc returns `{"error": "Document 'Untitled' is new and must be saved by the user first.", "success": false}`. No dialog, no UI prompt. Clean refusal.

**Rule.** Initial SaveAs must happen in the Fusion UI. After that, MCP `save` works for revisions. Surface this to the user when they ask Claude to save a brand-new design.

## Close on dirty documents requires confirmation flag

`execute document close` on a dirty doc returns: `"has unsaved changes. Confirm with the user before closing. Specify userConfirmedSaveAndClose or userConfirmedCloseWithoutSave in the request."`

Also: `userConfirmedSaveAndClose: true` on an Untitled doc still fails with the same "must be saved by the user first" error, because the save step inside save-and-close hits the same wall.

**Rule.** Never auto-pick which confirmation flag to send. Surface the choice to the user. The `saved: false` field in the close response is the audit trail for "did the agent discard changes?"

## Export path requirements

- Relative paths fail with `RuntimeError: 3 : The selected folder does not exist.`
- Protected paths (e.g. `C:/Windows/System32/`) fail with `RuntimeError: 3 : The selected folder is not accessible.`
- Missing parent folder likely produces the same "does not exist" error.
- Overwrite is SILENT. Existing file clobbered without prompt.

**Rule.** Always absolute paths. Always `os.makedirs(dirname, exist_ok=True)` before export. If preserving prior versions matters, add a suffix to the path.

## `createC3MFExportOptions` capital C

The 3MF export function is `em.createC3MFExportOptions`, not `em.create3MFExportOptions`. Common signature-guess miss. The C prefix is consistent with how Fusion versions its color-capable formats.

## ExportManager methods are `create*ExportOptions`, never `create*ExportInput` (2026-07-16)

Every other feature in the API uses the `createInput` naming convention, so `em.createSTLExportInput(...)` is the natural guess and it is wrong:

```
AttributeError: 'ExportManager' object has no attribute 'createSTLExportInput'.
Did you mean: 'createSTLExportOptions'?
```

The whole family is `Options`: `createSTLExportOptions`, `createC3MFExportOptions`, `createFusionArchiveExportOptions`, `createSTEPExportOptions`, `createOBJExportOptions`, `createIGESExportOptions`, `createSATExportOptions`, `createSMTExportOptions`, `createUSDExportOptions`, `createDXFFlatPatternExportOptions`, `createDXFSketchExportOptions`.

Two further traps:

- **The filename is a constructor arg, not a property.** `em.createSTLExportOptions(geometry, filename)`. There is no `.filename =` step for STL/3MF (unlike some older snippets).
- **Argument order flips for the Fusion archive.** It is `createFusionArchiveExportOptions(filename, component)` — filename FIRST — while STL/3MF are `(geometry, filename)`. Easy silent mix-up.

**Rule.** When unsure of an ExportManager signature, print the surface first; it is one cheap call and beats a failed round-trip:

```python
print([m for m in dir(design.exportManager) if 'Options' in m])
```

## Screenshot base64 can blow the tool-result token limit (2026-07-16)

`mcp__fusion__screenshot` returns base64 inline. At 1200px wide with `transparent=false` a single screenshot ran ~148,700 characters and was rejected/spilled to a file, costing a round-trip for nothing.

Also: `transparent=true` (the default) on a light-coloured body over a light background renders an image that reads as blank/washed out.

**Rule.** For anything above roughly 800px, or any repeated visual-check loop, skip the screenshot tool and write the file yourself, then read it back:

```python
vp = app.activeViewport
vp.fit(); vp.refresh(); adsk.doEvents()
vp.saveAsImageFile('C:/abs/path/shot.png', 1400, 780)
```

Then `Read` the PNG. Cheaper, higher resolution, no transparency surprise, and the file can be dropped straight into `catalog/<SKU>/docs/`.

## `viewExtents` is in cm (internal units), like everything else (2026-07-16)

Setting `cam.viewExtents = 22.0` intending "22mm across" gives a 220mm-wide view, i.e. fully zoomed out. Same cm rule as all other geometry. For a ~32mm-tall view use `3.2`. Also set `cam.isFitView = False` before hand-placing `eye`/`target`, or the fit overrides your framing.

## Imported SVG curves are FIXED — `sketch.move()` silently does nothing (2026-07-16)

`sketch.importSVG(filename, x, y, scale)` brings geometry in as **fixed** sketch curves. Any later attempt to reposition them is a silent no-op:

```python
sk.importSVG(SVG, 0, 0, s)
# ... compute dx, dy to centre it ...
sk.move(coll, matrix)     # returns without error, moves NOTHING
```

No exception, no `False` return. The bounding box afterwards is byte-identical to before, which is the only tell.

**Rule.** Place at import time using the position args. The anchor is the SVG's **top-left**, and geometry extends **+X / -Y** from it. To centre a logo of final size `w` x `h` on a target point:

```python
s = target_w / native_w_at_scale_1
ax_cm = (target_cx - w/2) / 10.0
ay_cm = (target_cy + h/2) / 10.0
sk.importSVG(SVG, ax_cm, ay_cm, s)
```

Measure `native_w_at_scale_1` with a throwaway import at `scale=1.0` first; scaling is linear and aspect is preserved to ~0.1%.

## SVG holes come back as SEPARATE profiles — extruding all of them fills the logo in (2026-07-16)

After `importSVG`, counters and ring interiors are their own profiles. Extruding every profile turns letter counters solid and fills ring shapes: an "8" becomes a blob, an outlined circle becomes a disc.

Real example (n8n logo, 10 profiles): 1 five-loop graph mark, 1 three-loop "8", 2 single-loop "n" letters, and **6 hole profiles** (four node counters at 4.72 mm² each, two "8" counters at 2.32 and 3.15 mm²).

Fusion represents a region-with-holes as a profile whose `profileLoops.count > 1` (first loop `isOuter=True`, the rest `False`), and *also* emits each hole as its own single-loop profile.

**Rule.** Filter before extruding:

```python
thresh = 100.0 * s * s          # mm^2, scaled with the import; tune per asset
keep = adsk.core.ObjectCollection.create()
for i in range(sk.profiles.count):
    pr = sk.profiles.item(i)
    area = pr.areaProperties(
        adsk.fusion.CalculationAccuracy.LowCalculationAccuracy).area * 100.0
    if pr.profileLoops.count > 1 or area > thresh:
        keep.add(pr)
```

Keep multi-loop profiles unconditionally (they already carry their holes), plus single-loop profiles above an area threshold (the solid letters). Print the kept/dropped split and eyeball it once per new asset — the threshold is asset-specific, not universal.

## `importSVG` anchors to the viewBox origin, not the content bounds (2026-07-16)

Placement maths derived from the content bounding box will be off by however much padding sits between the viewBox origin and the artwork. Real case: horizontal placement was exact, vertical was **5.0mm out**, because the SVG's content did not start at the viewBox's top edge.

**Rule.** Never hand-derive the anchor. Two-pass it:

```python
# pass 1: probe at (0,0), measure what you actually get
pr = root.sketches.add(plane); pr.name = '_probe'
pr.importSVG(SVG, 0, 0, s)
u0, u1, v0, v1 = sk_bbox(pr)          # min/max of every sketchCurve bbox
pr.deleteMe()

# pass 2: shift by the measured delta (import x/y translate sketch coords 1:1)
du = target_u_min - u0
dv = target_v_min - v0
sk = root.sketches.add(plane)
sk.importSVG(SVG, du, dv, s)
```

The `(x, y)` args translate the import in sketch space exactly, so the delta from a probe is always correct regardless of internal padding.

## Sketch curve `boundingBox` is in SKETCH space, not world (2026-07-16)

`sketchCurve.boundingBox` returns coordinates in the sketch's own U/V frame with Z always 0. On an XY sketch at the origin the two frames coincide, so this goes unnoticed for a long time — then you put a sketch on an offset or rotated plane and every bounds assert is silently meaningless (a front-face sketch reported `Z 0.00..0.00` for geometry genuinely spanning Z 4..20).

**Rule.** Convert before asserting against world bounds:

```python
wp = sk.sketchToModelSpace(adsk.core.Point3D.create(u, v, 0))
```

To learn a plane's mapping, transform three points and diff them:

```python
a  = sk.sketchToModelSpace(P(0,0,0))
bU = sk.sketchToModelSpace(P(1,0,0))   # dU = bU - a -> world dir of sketch +U
bV = sk.sketchToModelSpace(P(0,1,0))   # dV = bV - a -> world dir of sketch +V
```

For an XZ-offset plane this returns `dU=(1,0,0)`, `dV=(0,0,-1)` — confirming sketch +V maps to world **-Z**.

## `ConstructionPlaneInput.setByPlane` throws in parametric mode (2026-07-16)

```
RuntimeError: 3 : Environment is not supported
```

`setByPlane(Plane3D)` — the obvious way to get a plane with explicit UV directions — is unavailable in a normal parametric Design. Use `setByOffset` from an origin plane and live with that plane's UV convention, or use `setByThreePoints`.

Consequence worth planning around: you cannot dial in the plane orientation to suit your artwork. Combined with imported SVG being fixed (unmovable, unmirrorable), an SVG on an XZ-derived plane WILL import upside down. The fix is to pre-flip the source file:

```xml
<svg width="576" height="160" viewBox="0 0 576 160" ...>
<g transform="translate(0,160) scale(1,-1)">  <!-- original content --> </g>
</svg>
```

The plane's flip then cancels the file's flip. Note the build now depends on that generated file, so keep it next to the design and document it.

## `participantBodies` wants a plain list, not an ObjectCollection (2026-07-16)

Every other collection-shaped API arg takes an `ObjectCollection`, so this is a natural mistake:

```python
ei.participantBodies = coll        # TypeError: argument 2 of type 'std::vector<...BRepBody>'
ei.participantBodies = [stand]     # correct
```

## An inset feature on a flat-printed part becomes an unsupported island (2026-07-16)

`OffsetStartDefinition` is the obvious tool for "set this feature back from the face". On a part that prints flat, it can silently destroy a support-free print.

Real case: a locating tab under a sculpture needed to be clear of the visible front face so the face stayed round. Centring it in the thickness (2mm clear of *both* faces) is the symmetric, better-looking answer — and it starts the tab at Z=2 with **nothing beneath it**. The part of the tab overhanging the body outline becomes a floating island 2mm above the plate. Fusion builds it happily; the slicer then demands support on a part whose whole selling point was no supports.

**Rule.** Before insetting a feature with `OffsetStartDefinition` on a flat-printed part, ask what is under it at the start Z. If the feature extends beyond the silhouette of whatever sits below, inset from ONE face only and leave it flush with the plate:

```python
# floating: needs support where the tab overhangs the body
ei.startExtent = adsk.fusion.OffsetStartDefinition.create(VI('tab_inset'))
ei.setDistanceExtent(False, VI('body_t - 2 * tab_inset'))

# grounded: starts at Z=0, still clear of the visible face
ei.setDistanceExtent(False, VI('body_t - tab_inset'))
```

Verify it really starts on the plate:

```python
assert abs(min(tab_face_z)) < 0.01, "feature lifted off the plate - would need support"
```

Aesthetic symmetry is worth less than a support-free print. Ask which face actually matters.

## Offsetting a feature moves the part in its mate (2026-07-16)

Follow-on from the above, and the kind of thing that only shows up on the printer. Once a tab is inset from one face, it is **no longer centred in the part's thickness**. A socket cut at the mating part's dead centre then parks the part `inset/2` proud of centre — geometrically fine, visibly wrong, and invisible in CAD unless you compute it.

**Rule.** When a locating feature is asymmetric in thickness, shift the socket by half the asymmetry and assert where the part lands:

```python
socket_cy = BASE_CY + tab_inset/2.0          # tab flush at back, inset at front
part_back  = socket_cy + (tab_t + clear)/2.0 - clear/2.0
part_front = part_back - body_t
assert abs((part_front + part_back)/2.0 - BASE_CY) < 0.2, "part sits off-centre in its mate"
```

## Isolate a sub-feature's extent with face bounding boxes (2026-07-16)

After a Join, the feature you added is no longer a separate body, so you cannot measure it directly. Filter the merged body's faces by a coordinate you know the feature occupies alone:

```python
tab_z = []
for f in body.faces:
    fb = f.boundingBox
    if fb.minPoint.y*10 < -69.5:          # only the tab lives below the circles
        tab_z += [fb.minPoint.z*10, fb.maxPoint.z*10]
print(f"tab Z {min(tab_z):.2f}..{max(tab_z):.2f}")
```

This is how you prove an inset actually happened, and that the feature still touches the plate. Body-level bounding boxes cannot tell you either.

## Generated build inputs belong with the design, not in a temp dir (2026-07-16)

If a build consumes a *derived* asset (a pre-flipped SVG, a converted mesh, a generated profile), that file is a build dependency, not a scratch artifact. Left in a temp directory it works all session and breaks silently on the next rebuild after cleanup.

**Rule.** Put generated inputs next to the design (`design/` alongside the CAD source), commit the generator script beside them with a header explaining *why* the derived file exists, and say in the README that the build consumes the derived file rather than the source.

## An emboss on a vertical face needs an explicit sign check (2026-07-16)

Extruding artwork on a face whose plane normal points *into* the solid engraves it instead of embossing it, with no error. Whether you need `icon_t` or `-icon_t` depends on the plane's normal, which for `setByOffset` planes is inherited, not chosen.

**Rule.** Assert the resulting bounds moved the way you intended:

```python
assert abs(body.boundingBox.minPoint.y*10 - (front_y - icon_t)) < 0.01, \
    "embossed INWARD - flip the extrude sign"
```

## Body count is the cheapest correctness check after a Join (2026-07-16)

A Join extrude whose profiles do not actually touch the target silently produces **extra free-floating bodies** instead of failing. This is how an SVG placed slightly off its host face announces itself: the overhanging letters simply become their own bodies.

**Rule.** After any Join that should merge, `assert root.bRepBodies.count == 1` (or whatever the expected count is). It catches mis-placement that a screenshot from the wrong angle will happily hide. Pair it with an explicit bounds assert when placing onto a known face:

```python
assert min(xs)*10 > face_x_min and max(xs)*10 < face_x_max, "artwork overruns host face"
```

## `isRollingBall = True` matters for fillets

Default `FilletFeatureInput` geometry is NOT the spherical-corner blend most CAD users expect. Set `isRollingBall = True` for the standard blend.

## `isComputeDeferred` matters for >10 vertex sketches

`sk.isComputeDeferred = True` before bulk `addByTwoPoints` calls, `= False` after. Without it, every line add re-solves the sketch. Below 10 vertices the difference is negligible; at 50+ Fusion freezes.

## HoleFeatureInput is worth using over sketch+cut

It is tempting to bypass `HoleFeatureInput` because the signature looks awkward, but it works on first attempt with `createCounterboreInput(holeDia, cboreDia, cboreDepth)` and `setPositionByPoint(face, point3d)`.

**Rule.** Use `HoleFeatures` for standard holes (simple, counterbore, countersink). Parametric, named, editable in timeline, cleaner than two extruded cuts. Reserve sketch+extrude-cut for non-standard hole geometry.

## Project ID format mismatch

`document/open` returns `parentProjectId` in base64 form (e.g. `a.YnVzaW5lc3M6Z21haWw...`). `document/recent`, `document/search`, and `projects` return the same project as a decimal ID (e.g. `202602051047590776`). Same project, two formats. Use whatever the consuming call accepts; not yet confirmed if `document/open` for fileId accepts either form.

## Flange overhangs need slicer tree supports

CAD-side note: 10mm+ horizontal flange overhangs require tree supports in the slicer. No CAD-side fix short of redesigning as a chamfered skirt. Worth flagging when proposing flanged designs.

## `defaultLengthUnits` is read-only via script

Display units (mm vs cm) must be set via the Fusion UI or document template, not via script. Internal geometry is always cm regardless of display units; this is cosmetic only.

## `setDistanceExtent` direction is implicit on HoleFeature

For `HoleFeatureInput.setDistanceExtent`, the through-direction comes from the face normal passed to `setPositionByPoint`. No explicit `ExtentDirections` argument needed. Different from `ExtrudeFeatureInput`, which requires explicit direction.

## Redo stack is consumed by new features

After `undo`, any new feature added via `execute` consumes the redo stack. Subsequent `redo` returns `{"error": "Nothing to redo", "canUndo": true, "canRedo": false, "success": false}`. Fails gracefully.

**Rule.** The skill can rely on `canUndo` and `canRedo` flags in the returned JSON for branching logic. Document that any new feature kills the redo stack.

## Untitled docs have no fileId

`document/open` (read) lists Untitled docs without an `id` field. Cannot pass them to `document/open` (execute) since fileId is required. Untitled doc workflows must start from creating fresh in the Fusion UI or saving the doc first.

## Document search treats `-` and `_` as equivalent

Query `My-Part` matches docs named `My_Part...`. Useful for fuzzy matching across naming conventions.

## `participantBodies` is required for cuts that target a specific body

When multiple bodies exist in a component and a cut should only affect one:

```python
cut_in.participantBodies = [body]
```

Without this, Fusion may pick the wrong body or apply the cut to all candidate bodies. Always set when more than one body is present. Also required for the Join extrude pattern (`patterns.md` section 23) so the lip flange joins onto the body rather than creating a new disconnected solid.

## CAD volume is NOT a filament-weight estimate

`body.volume` (returns cm^3) is the geometric solid volume. Real print weight is dramatically lower because slicers use sparse infill, fixed wall counts, and don't fill cavities the way a solid would.

Symptom: a 306 cm^3 tray modeled in Fusion estimates "~310g of ABS at solid density" but actually prints at ~90g (30% infill, 3 perimeters, 5 top/bottom layers). Pricing off the solid number kills margin; pricing off a guess is just as bad.

**Rule.** Treat any pre-slice filament weight as provisional. Slice the actual STL in Bambu Studio (or whichever slicer) and read grams + print time from there. Lock COGS only after the first verified print confirms the slicer numbers.

## `document/open` (execute) requires fileId in urn form

The `fileId` parameter for `execute document open` is the `urn:adsk.wipprod:dm.lineage:...` form returned in the `id` field of `document/search` or `document/recent` results.

**Workflow.** `read document search` (or `recent`) -> copy the `id` field -> pass as `fileId` to `execute document open`. Project ID is NOT a substitute and isn't required for the open call.

## Tapered cut needs the third arg form of `setOneSideExtent`

`setOneSideExtent(extentDef, direction)` is the standard signature. To add taper (countersink-style cone), pass a third `ValueInput` for the taper angle:

```python
ext_def = adsk.fusion.DistanceExtentDefinition.create(
    adsk.core.ValueInput.createByString('cs_depth'))
taper_vi = adsk.core.ValueInput.createByString('-cs_angle / 2')  # negative = inward
cut_in.setOneSideExtent(ext_def,
    adsk.fusion.ExtentDirections.NegativeExtentDirection,
    taper_vi)
```

Easy to miss the third positional arg. For standard countersinks, prefer `HoleFeatures.createCountersinkInput` (`patterns.md` section 25); it's parametric and editable in the timeline.

## STL refinement is a no-op for flat geometry, real for curves

`MeshRefinementLow`, `MeshRefinementMedium`, `MeshRefinementHigh` produce identical files for any flat-faceted geometry. The difference only shows up on curved surfaces (fillets, revolves, lofts), where High gives smoother facets at the cost of file size.

**Rule.** Default to `MeshRefinementHigh` for production exports. Cost on flat-dominated geometry is zero (identical output); benefit on curve-heavy parts is significant.

## Export artifact cleanup is your responsibility

The MCP writes export files wherever you point them, never warns on overwrite, and never cleans up. Test runs that wrote to `C:/temp/test_body.stl` etc. accumulate over sessions.

**Rule.** Use a scoped sub-folder for throwaway exports (e.g. `C:/temp/fusion-tests/`) that you can delete in bulk. Production exports should always go to a project-pathed destination, never `C:/temp`.

## Math-function names are reserved as user-parameter names

`floor` is not a valid user-parameter name; Fusion's expression language reserves it for the math function `floor(x)`. `params.add('floor', ...)` raises `RuntimeError: 3 : param name is not valid` with no indication of which name failed.

Likely also reserved (not exhaustively tested): `ceil`, `abs`, `sqrt`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `log`, `ln`, `exp`, `min`, `max`, `pi`, `e`. Plain English words like `wall` are fine, so the rule is specifically Fusion expression-language identifiers, not arbitrary words.

**Rule.** Suffix any potentially-colliding name: `floor_thk`, `min_clearance`. Adopt a `<noun>_<adjective>` convention for thickness, depth, and length params (`wall_thk`, `body_height`).

## Stdout buffering can hide which loop iteration failed

When a script crashes mid-loop, prints from before the crash may not flush in time. Symptom: the log shows iterations 1-5 succeeding, iteration 6 has no log line, yet the traceback fires from inside iteration 6.

**Rule.** Use `print(name, flush=True)` for diagnostic prints when narrowing a failing iteration, or print AFTER each successful op so the last printed name is the last success and the failure is whatever came next in the input list.

## RectangularPattern with `isSymmetricInDirectionOne=True` makes wrong or disconnected bodies

Patterning a `JoinFeatureOperation` extrude (single knuckle at X=0) with `quantityOne=3`, `distanceOne='40 mm'`, `ExtentPatternDistanceType`, and `isSymmetricInDirectionOne=True` does NOT produce 3 instances at X=-20, 0, +20. It produces 6 new disconnected bRepBodies at X plus or minus 40 (body count went 2 to 8), and the Join did not merge. The result matches no standard interpretation of the inputs.

**Workaround.** Use `MirrorFeatures` (patterns.md N10, verified V7) for symmetric replication, or place instances manually on offset construction planes. Root cause unresolved but reproducible. Until investigated, prefer Mirror.

## SketchPoint is not hashable

`adsk.fusion.SketchPoint` cannot go in a `set()`. To find a corner, collect into a LIST and use `min(pts, key=lambda sp: (sp.geometry.x, sp.geometry.y))`. Applies to most Fusion API objects; prefer lists plus key functions over sets.

## Driving a joint does not persist through a recompute

Setting `jointMotion.rotationValue` / `slideValue` repositions the model, but adding a feature or any recompute (including setting `transform2` or `isGrounded`) resets driven joints to their rest position. Observed repeatedly: a lid driven to 180 degrees snapped back to 0 after new features were added and on every reorientation. Mitigations: set `restValue` on the joint limits (patterns.md N15); always re-drive joints as the final step before screenshot or export. Treat joint drive state as transient.

## Preview API badges are release gates

Symptom: a method exists in the scraped API corpus and works in a local experiment, but Autodesk later changes or removes it and the public plugin/server breaks.

Root cause: some Fusion API pages are explicitly tagged Preview and say not to deliver distributed programs that use preview capabilities.

Current corpus review, 2026-05-31:
- Stable May 2026 pages: `Component.findMeshUsingRay`, `MeshBody.calculateCollisionsWithRay`, `ConstructionPlaneInput.setByAngleOnCurvedFace`.
- Preview families: `UserCoordinateSystem*`, `ElectronManager` / Electronics objects, `AssemblyConstraint*`, `VolumetricModel*`.

**Rule.** Use Preview APIs only after explicit user opt-in. Do not put Preview APIs in default public workflows or stable MCP tools.

## Print-in-place at tight clearances can fuse on FDM (CAD-side print note)

PRINTER-VERIFIED on a captured slider+hinge test part: a print-in-place slider plus hinge at 0.2mm rotational / 0.3mm Z / 1mm Y clearances FUSED on the first Bambu print (moving parts welded to the housing). For this class of part, prefer SEPARATE parts laid out on one plate with assembly clearances (looser, tunable, sandable) over a captured print-in-place mechanism, and use a separate printed or filament/rod pin through the hinge knuckles rather than a print-in-place knuckle. See patterns.md N11, N17, N44, and N45 for the parametric clearance technique, the separate-parts recommendation, and full hinge recipes.

IF you do commit to a print-in-place hinge, keep its axis HORIZONTAL / parallel to the build plate so the knuckle-separation gaps print as vertical seams (reliably free). Laying the part so the hinge axis is VERTICAL turns those gaps into horizontal layer planes that fuse easily, giving a stiff or welded pivot. Same family as the "flange overhangs need slicer tree supports" note above.

### PRINTER-VERIFIED: keyed tab into a socket, PLA

Our own two-print result, so this one is not a tutorial recipe.

| Fit | Tab | Socket | Total clearance | Result |
|---|---|---|---|---|
| tab in socket, display stand | 8 x 6 mm rectangular | 8.3 x 6.3 | **0.3 mm** | seats, but "very tight" |
| same | 8 x 6 mm | 8.4 x 6.4 | **0.4 mm** | "works great, fitment is much better" |

PLA on a Bambu P1S, printed flat, socket opening upward. 0.4mm total (0.2/side) is a friction fit that still holds a display piece upright without wobble. That matches the usual FDM bands: **0.2-0.4mm total for a snug/friction fit, ~0.5mm+ before it slides freely.** Start at 0.4 rather than 0.3 for this class of fit.

Clearance is **absolute, not proportional**: it does not scale with the part. But engagement *length* does, and a longer tab has more surface to bind, so the same 0.4mm is effectively tighter on a 14mm tab than on an 8mm one. When scaling a design up, hold clearance and expect it to feel tighter, not looser.

### A fit validated on your own printer is not validated

This is the trap behind every clearance number above, and it is a judgement error rather than a CAD one.

If the model is going to a marketplace (MakerWorld, Printables, Thingiverse), strangers print it on machines you do not control. FDM tolerance varies by roughly **±0.1-0.2mm** between printers, nozzles, filaments, and slicer profiles; elephant foot alone eats that much. So:

- **"Very tight but it fits" on the designer's own printer is "does not go together" on a printer running slightly wide.** That is a support thread, not a print.
- The designer's printer is the *best* case, not the average case. It is the machine the part was iterated on.

Loosen toward the middle of the functional band before publishing, not to the edge that happens to work for you. The cost is asymmetric: a fit 0.1mm looser than ideal is slightly less crisp, while a fit 0.1mm tighter than someone's tolerance is unusable.

Counter-check before loosening: confirm the loose end still works. Going from a tight-but-functional fit to a wobbly one is a real regression, and on a display piece it is worse than the tight fit you started with. Reprint and confirm rather than assuming more clearance is free.

### Clearance recipes from accepted tutorial sources (NOT printer-verified by us)

Recipes recorded so a future first print has a baseline. None of the values below are validated by our own prints; expect to tune for your printer + slicer + material. See patterns.md N44 / N45 for full geometry recipes.

| Source | Mechanism | Per-face clearance | Diametric clearance | Other |
|---|---|---|---|---|
| What-Make-Art print-in-place | Captive cone + cylinder, one body | -0.3 mm flat faces, -0.2 mm cone face | n/a (mating faces are flat + cone, not cylindrical) | Cone -35deg taper, 55deg overhang on lead-in walls, 0.8 mm fillet on non-bed edges, 0.8 mm chamfer on bed face |
| PDO Day 20 snap-hinge | Two separate flanges with nub-in-cavity | n/a (cavity uses Offset Face) | 0.8 mm starting, range 0.2-0.8 mm | Nub taper -10 to -14 deg, 1 mm fillet on nub edge, 0.6 mm Offset Start clearance between mating flanges, 0.1 mm layer height |

Apply Offset Face to all opposing cavity walls SIMULTANEOUSLY with one negative value: the offset applies per-face, so -0.4 mm on opposite cavity walls produces 0.8 mm diametric clearance (PDO Day 20 technique). The number you type into Offset Face is HALF the resulting diametric gap.

Two distinct philosophies are visible in these sources:
- What-Make-Art treats the cone face as the running surface (tight clearance there for less play) and the flat side faces as the support surfaces (looser clearance for free movement).
- PDO uses no cone; the cylindrical nub rides in a cylindrical cavity with the cavity over-cut by Offset Face for free running, and a sketch-level taper on the nub (-10 to -14deg) to ease engagement.

Neither source distinguishes by material. PLA, PETG, and ABS will produce different functional clearances at identical CAD dimensions because of layer-line surface roughness and shrinkage. Treat the tabulated values as PLA-on-FDM starting points.

## G10 Stale feature reference after sketch geometry rewrite (2026-05-31)

A script that deletes all curves + dimensions in a sketch and replaces them with new geometry leaves any downstream feature (extrude, cut, fillet, etc.) pointing at a stale profile reference. Symptoms:

- `feature.healthState == 1` with `errorOrWarningMessage` containing "The profile reference is lost and this feature is using cached geometry."
- API queries on the body's edges show the NEW geometry (Fusion's cached output from the last successful compute).
- The Fusion UI continues to display the OLD geometry — the cached BREP rendered as-is.
- `design.computeAll()` does not fix this.

User-visible result: "I don't see any changes" despite the script reporting success and the BREP showing the new geometry.

**Fix.** Don't try to re-bind the feature in place. Delete it and re-create it with a fresh profile reference:

```python
old = body_comp.features.itemByName("dispense_hole_cut")
if old and old.healthState != 0:
    old.deleteMe()
sk = body_comp.sketches.itemByName("dispense_hole")
prof = sk.profiles.item(0)
ext = body_comp.features.extrudeFeatures
einput = ext.createInput(prof, adsk.fusion.FeatureOperations.CutFeatureOperation)
einput.startExtent = adsk.fusion.OffsetStartDefinition.create(
    adsk.core.ValueInput.createByString("slot_chamber_d + slot_narrow_d"))
einput.setDistanceExtent(False, adsk.core.ValueInput.createByString(
    "floor_thk - slot_chamber_d - slot_narrow_d"))
einput.participantBodies = [body_comp.bRepBodies.itemByName("body_main")]
new_feat = ext.add(einput)
new_feat.name = "dispense_hole_cut"
```

**Detection.** After any tool that mutates sketch geometry, audit every downstream feature's health:

```python
for ft in comp.features:
    if ft.healthState != 0:
        print(f"BROKEN {ft.name}: {ft.errorOrWarningMessage[:120]}")
```

Run this audit after every mutating call, not just at the end of a build. A feature that breaks mid-timeline stays broken and silently corrupts everything downstream of it. The `audit_feature_health` tool does exactly this sweep.

## G11 Fillets break when upstream geometry edits move their edges (2026-05-31)

Constant-radius fillets store topological references to the edges they target. Small tweaks survive, but bumping a sketch dimension that moves an edge significantly (10mm+ along its length, or changes its orientation) often pushes the fillet to `healthState == 2` or `3`:

```
The fillet/chamfer could not be created at the requested size.
This might be occurring at the ends of the selected edges.
```

1mm and 2mm fillets fail most often because they can't shrink to fit the new corner geometry. Larger named fillets on stable edges (body outer-corner rounding, cavity interior corners) typically survive.

**Reproduced in a real design session (2026-05-31).** Two sketch-dim edits broke three fillets across the same body:

| Edit (clip_profile sketch) | Broken fillet | Reason |
|---|---|---|
| `d278: 65→80mm` (clip top extended +15mm) | `Fillet3` (state=2) | Targeted clip-top corner edge that no longer existed in same form |
| `d288: 28→43mm` (platform underside Z=60→75) | `Fillet4` (state=3) | Targeted edge whose Z range shifted |

**Fix.** SUPPRESS, don't delete. Lets the user re-enable or repair interactively, and signals the feature was lost but not abandoned.

```python
ft = body_comp.features.itemByName("Fillet3")
if ft and ft.healthState != 0:
    ft.isSuppressed = True
    design.computeAll()
```

**Don't try to auto-repair fillet edge references from a script.** Edge identity after BREP regeneration is unstable; re-selecting "the same" edge requires a geometric query (find an edge whose endpoints match the previous ones at a tolerance), which is error-prone and design-specific. Cheaper to surface the breakage to the user and ask them whether the missing fillet matters.

**Detection.** Same health-audit sweep as G10. Always run it after any edit that touches body sketches or extrude depths.

## G12 Re-binding the timeline marker forces full re-render (2026-05-31)

When the Fusion UI is showing a stale cached state (often after G10/G11 fixes), a hard repaint can be forced by rolling the timeline marker to position 0 and back to the end:

```python
tl = design.timeline
end = tl.count
tl.markerPosition = 0
tl.markerPosition = end
app.activeViewport.refresh()
```

`computeAll()` re-evaluates features in place but does not always trigger a full UI re-rasterize. The marker round-trip does. Use sparingly — it's a noticeable user-visible flash and re-evaluates the entire feature tree. Save and reopen is the bigger hammer if even this doesn't work.

## SketchText cannot be mirrored, and rotating it 180 degrees mirrors it instead

Same family as the fixed-imported-SVG problem, and it bites in the same place: a sketch plane whose +V maps to world -Z (any plane derived from XZ). Text drawn upright in sketch UV comes out upside down in the world.

For imported SVG the fix is a pre-flipped file (`<g transform="translate(0,H) scale(1,-1)">`). **That fix does not transfer to text.** `SketchText` is not a file you can pre-process, and it cannot be mirrored after creation any more than fixed SVG curves can.

The trap is the obvious workaround. Rotating the text 180 degrees (the last arg of `setAsMultiLine`) looks like it should cancel the flip. It does not:

- a 180 degree rotation flips **both** U and V
- the plane flips **only** V
- net effect: U is flipped alone, so the text is upright but **mirrored**

Mirrored bold text at a glance in a small render reads as correct. This will ship if you do not look at a real screenshot of that face.

The fix that works: **do not sketch on the flipped plane at all.** Build the text on the XY plane where the orientation is unambiguous, extrude as a NewBody, then move the body into place with a rotation.

```python
ei = exts.createInput(st, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
ei.setDistanceExtent(False, adsk.core.ValueInput.createByString('0.7 mm'))
ex = exts.add(ei)
tools = adsk.core.ObjectCollection.create()
for i in range(ex.bodies.count):
    tools.add(ex.bodies.item(i))          # one body per letter

# +90deg about X: (x,y,z) -> (x,-z,y).
# sketch +Y -> world +Z (upright); extrude +Z -> world -Y (out the front face).
m = adsk.core.Matrix3D.create()
m.setToRotation(math.pi/2.0, adsk.core.Vector3D.create(1, 0, 0),
                adsk.core.Point3D.create(0, 0, 0))
m.translation = adsk.core.Vector3D.create(cx_cm, face_y_cm, cz_cm)  # applied AFTER the rotation
mi = root.features.moveFeatures.createInput2(tools)
mi.defineAsFreeMove(m)
root.features.moveFeatures.add(mi)

ci = root.features.combineFeatures.createInput(target_body, tools)
ci.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
root.features.combineFeatures.add(ci)
```

Two details that matter:

- **Extrude 0.1mm deeper than the emboss you want and bury that 0.1 in the target.** Landing the tool body exactly coplanar with the target face asks Combine to join on coincident faces; overlap is more robust. Extrude 0.7 for a 0.6mm proud emboss, translate so the back sits 0.1mm inside.
- **Assert the proud height** (`body.boundingBox.minPoint.y == face_y - 0.6`). It catches a sign error on the translation, which otherwise buries the text invisibly inside the part.

Multi-line text produces **one body per letter**. Collect them all into the ObjectCollection or you will move some letters and leave the rest behind.

## `adsk.doEvents()` returns before a parameter change finishes recomputing

Setting `param.expression` then immediately reading `root.bRepBodies.count` (or a volume, or a bounding box) can return **mid-recompute state**. Observed: an assertion read `bodies=13` (11 letters + sculpture + base) right after a `body_t` change, on a design whose join was perfectly healthy. Re-querying the same doc a moment later returned `bodies=2`. Nothing was wrong with the model; the read was just early.

This wastes real time, because the failure looks exactly like a genuine broken join and sends you diagnosing the wrong thing.

`adsk.doEvents()` alone is not a barrier. Force the compute and settle:

```python
def settle(design, root, expected_bodies):
    for _ in range(8):
        design.computeAll()
        adsk.doEvents()
        if root.bRepBodies.count == expected_bodies:
            return True
    return False

bt.expression = '10 mm'
assert settle(design, root, 2), f"did not settle: bodies={root.bRepBodies.count}"
```

Only assert on geometry **after** it settles. If it never settles, the failure is real.

## Suppress hard-won features, do not delete them

When a design carries mutually exclusive variants (two logos on one face, two mount styles), the instinct is delete-and-rebuild per variant. Use `feature.isSuppressed = True` instead when the feature's *placement maths* was expensive to derive: two-pass SVG anchor probes, plane-flip cancellation, a rotation matrix onto a non-trivial face.

```python
feats = {f.name: f for f in root.features}
feats['base_logo_extrude'].isSuppressed = (variant != 'logo')
feats['base_text_join'].isSuppressed  = (variant != 'text')
```

Delete-and-rebuild means re-deriving that maths on every switch, and every re-derivation is a fresh chance to get it wrong. Suppression is reversible, survives the save, and keeps the timeline as documentation of both variants. Reserve deletion for geometry that is genuinely cheap to reconstruct from a few numbers.

Caveat: suppression is per-feature, so suppress the **whole chain** for a variant (sketch extrude + move + combine), not just its last feature.

## A parameter change that does not move the volume means the geometry did not move

This is the detection rule for script-driven (as opposed to constraint-driven) geometry, and it is worth stating as a standalone check because the bug is silent in every other channel.

When plan geometry is computed numerically in a build script, changing a user parameter updates the parameter and **nothing else**. The parameter table cheerfully reports the new value. Screenshots look plausible. Exports succeed. The only tell is that the volume does not move.

Seen twice on the same design:

1. `base_slot_w` reported 15.40mm while the slot stayed 10.4mm.
2. A base exported with a volume **identical** at two different thicknesses (64,763.3 both), because the tab sockets never widened. That reached an exported STL.

So, after any parameter change that should alter geometry:

```python
before = body.volume * 1000
p.expression = '15 mm'
settle(design, root, 2)
after = body.volume * 1000
assert abs(after - before) > 1.0, f"volume unchanged ({after:.1f}) -> geometry is not parametric here"
```

Two identical volumes across two parameter values is never a coincidence worth accepting. Rebuild the sketch at the new value.

## `importSVG` scale depends on the SVG's units, and unitless means px at 96 DPI

`importSVG(file, x, y, scale)` has no fixed unit contract. What `scale` means depends on how the SVG declares its own size:

- SVG whose `width`/`height` map to mm: `scale = target_mm / native_units` lands exactly.
- SVG with **unitless** `width="1275"`: Fusion reads those as **CSS pixels at 96 DPI**, so the same formula comes out **25.4/96 = 0.2646x too small**.

Observed on one machine, same session, two files: an artwork whose units were mm imported at exactly the requested 44.00mm, while a generated `width="1275"` file asked for 72.8mm and delivered **19.17mm**. The ratio is 3.7795 = 96/25.4, which is the tell. If your import comes back 3.78x small (or 3.78x large), this is why.

Do not hand-derive the scale. **Probe it:**

```python
s = (target_mm / art_units) * (96.0 / 25.4)   # only if the file is unitless
pr = root.sketches.add(plane)
pr.importSVG(SVG, 0, 0, s)
w = (bbox_of(pr)[1] - bbox_of(pr)[0]) * 10
pr.deleteMe()
assert abs(w - target_mm) < 0.5, f"scale wrong: got {w:.2f}"
```

Better: always probe-import, measure, and correct by the measured ratio (`s2 = s * target / measured`). That is unit-agnostic and survives whatever the next file declares. You need a probe pass anyway, because `importSVG` also anchors to the viewBox origin rather than the content bounds.

## Do not filter SVG counters by area; pair them to their parent by containment

The tempting filter for "which imported profiles are letter counters" is a size threshold: keep profiles with `profileLoops.count > 1` or `area > threshold`, drop the rest. It works only when every counter happens to be smaller than every real shape. **That is a property of one particular logo, not a rule.**

Counter-example from a real hand-lettered wordmark: a counter of **32.44 mm²** whose parent ring was **59.65 mm²**, on the same artwork as legitimate ink parts of **13.83** and **21.63 mm²**. Any threshold that dropped the counter also dropped real letters, and any threshold that kept the letters also filled the counter.

Pair each counter to the profile that owns it:

```python
info = []
for i in range(sk.profiles.count):
    p = sk.profiles.item(i); bb = p.boundingBox
    info.append(dict(i=i, p=p, loops=p.profileLoops.count,
                     x0=bb.minPoint.x*10, x1=bb.maxPoint.x*10,
                     y0=bb.minPoint.y*10, y1=bb.maxPoint.y*10))

def inside(a, b, m=0.01):
    return (a['x0'] > b['x0']+m and a['x1'] < b['x1']-m and
            a['y0'] > b['y0']+m and a['y1'] < b['y1']-m)

counters = set()
for par in [d for d in info if d['loops'] > 1]:
    cand = [d for d in info if d['loops'] == 1 and inside(d, par)]
    assert len(cand) == 1, f"ambiguous: {len(cand)} candidates"
    counters.add(cand[0]['i'])
```

**Verify by volume, not by eye.** Extrude the kept profiles and check the volume delta equals `kept_area * icon_t` exactly. If a counter got filled, the delta comes out high by that counter's area. On one build the emboss added 1,073.1 mm³ against a kept area of 1,073.13 mm² at 1.0mm: proof to the decimal that no counter was filled.

### The bbox version false-positives as soon as shapes overlap

Bounding-box containment is a proxy for real containment and it breaks when two drawn shapes overlap: the overlap sliver's bbox can sit entirely inside a neighbour's bbox and read as a hole.

Hit on a clapperboard glyph where a tilted stick overlapped a slate: the test found **4 holes when 3 were drawn**. Nothing was wrong with the geometry; the test was wrong.

When you drew the detail yourself, **match centroids to the coordinates you drew** instead. It is exact and cannot be fooled by overlap:

```python
want = [(cx + slot(lx)[0], cy + slot(lx)[1]) for lx in SLOT_XS]
holes = {i for i in range(sk.profiles.count)
         if min(math.hypot(cen(i).x*10-wx, cen(i).y*10-wy) for wx, wy in want) < 0.4}
assert len(holes) == len(want)
```

Print the distances. A clean match shows an obvious gap (observed: slots at 0.000-0.071mm, nearest non-slot at 0.726mm). If that gap is not obvious, the match is not safe.

## A cut from the wrong face has the SAME volume as a cut from the right one

The volume-diff rule catches geometry that did not move. It cannot catch geometry that moved to the wrong place, and pocket direction is the case that bites.

Extruding a pocket sketch from the XY plane at Z=0 with a positive distance cuts **upward from the bottom face**. If you wanted the pocket to open at the top, you get a void buried against the build plate, a solid top face, and **exactly the same volume**, because the same amount of material is removed either way.

Symptoms: the render looks solid from above, the part prints with holes face-down on the plate, and nothing mates. Volume, mass, and bounding box all agree with the correct part.

Cut downward from a plane at the top instead:

```python
pi = root.constructionPlanes.createInput()
pi.setByOffset(root.xYConstructionPlane, adsk.core.ValueInput.createByString('base_h'))
top = root.constructionPlanes.add(pi); top.name = 'base_top_plane'
sk = root.sketches.add(top)
...
ei.setDistanceExtent(False, adsk.core.ValueInput.createByString('-socket_d'))   # negative
```

Assert on the **face position**, which is the only signal that differs:

```python
floors = [round(f.boundingBox.minPoint.z*10, 2) for f in faces_matching(body, sock_y)]
assert abs(floors[0] - (BASE_H - SOCKET_D)) < 0.05, f"socket opens the wrong way: {floors}"
```

Generalises: for any feature where a sign error still removes the same material (pockets, counterbores, recesses), verify **where a face landed**, never the volume.

## An exception rolls back the entire `execute`, including geometry that succeeded

The tool runs each `execute` as one transaction. A traceback anywhere discards **everything the script built**, not just the failing step.

Cost a full rebuild once: a script created 6 bodies correctly, then threw `AttributeError` in the *reporting* code at the very end (`BoundingBox3D.combine` returns a bool and mutates in place, so `tot = tot.combine(bb) or tot` blows up). The geometry was perfect. The next call reported `bodies=0`.

So:

- Keep verification/printing trivially safe, or put it in a **separate** `execute` after the build lands.
- Make build scripts **idempotent** (delete-by-name at the top) so a rerun after a rollback is free.
- This is not a reason to `try/except` around `run()`. Swallowing the traceback loses the diagnosis and still rolls back. Fix the reporting bug.


## Restarting Fusion invalidates the MCP session; the client 404s until it reconnects

Symptom: every MCP call fails with `Client error '404 Not Found' for url 'http://127.0.0.1:27182/mcp'`, while Fusion is plainly running and healthy.

This looks exactly like "the MCP server is off", and the instinct is to go toggle **Preferences > General > API > Fusion MCP Server**. That is the wrong fix and it makes things worse: each restart mints a new server that invalidates the session again.

What is actually happening: MCP's streamable-HTTP transport is **session-based**. The client holds an `Mcp-Session-Id` from its first handshake. Restart Fusion and the new server has never heard of that id, so it answers `404` to every POST. The transport is behaving correctly; the client is talking to a server that does not know it.

Distinguish the two cases from outside the client, because they look identical from inside it:

```
GET http://127.0.0.1:27182/mcp
  -> 404   the route does not exist. The MCP server really is off. Enable it in Preferences.
  -> 405   Method Not Allowed. The route EXISTS and only accepts POST. The server is UP;
           your session is stale.
```

Confirm with a fresh handshake, which is unaffected by the dead session:

```powershell
$body = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}'
Invoke-WebRequest -Uri "http://127.0.0.1:27182/mcp" -Method POST -Body $body `
  -ContentType "application/json" -Headers @{ "Accept" = "application/json, text/event-stream" }
```

A `200` plus an `Mcp-Session-Id` header proves the server is fine and the problem is entirely on the client side.

**The fix is to reconnect the client**, not to restart Fusion: in Claude Code, `/mcp` and reconnect the `fusion` server (or restart Claude Code). Only the user can do this; there is no tool call that re-handshakes your own transport.

Also check `Get-NetTCPConnection -LocalPort 27182` and confirm the owning PID is `Fusion360`. If something else holds the port, that is a genuinely different problem.

## Joint limits do not live on the JointMotion (2026-07-18)

`jointMotion.minimumValue` / `minimumValueEnabled` do not exist. Setting them appears to work in a script (Python happily assigns new attributes to some wrapped objects) and then has no effect.

Limits live on a `JointLimits` object hanging off the motion, and which one depends on the motion type:

| Motion | Limits property |
|---|---|
| `RevoluteJointMotion` | `rotationLimits` |
| `SliderJointMotion` | `slideLimits` |
| `CylindricalJointMotion` | both; pick `rotationLimits` unless you specifically want travel |
| `RigidJointMotion` | neither |

Each `JointLimits` exposes `isMinimumValueEnabled` / `minimumValue`, `isMaximumValueEnabled` / `maximumValue`, `isRestValueEnabled` / `restValue`. Note the `is` prefix, which is the part most people get wrong after reading older samples.

**Values are internal units**: radians for rotation, cm for slide. And you cannot get there via `ValueInput`:

```python
adsk.core.ValueInput.createByString("45 deg").realValue
# RuntimeError: Value does not contain a real
```

`realValue` is only meaningful on a `ValueInput` built with `createByReal`. A string-created one carries no evaluated number until a feature consumes it. Evaluate the expression yourself instead:

```python
um = design.unitsManager
lim = jm.rotationLimits                       # or jm.slideLimits
lim.isMaximumValueEnabled = True
lim.maximumValue = um.evaluateExpression("45 deg", "deg")   # returns radians
```

Pass `"deg"` for rotary and `"mm"` for linear as the expected measure; `evaluateExpression` returns the value in Fusion's internal unit for that measure, which is exactly what the limit wants. Read the value back afterwards to confirm it stored, because a limit that conflicts with the joint's current position can be quietly clamped.

## Fusion silently ignores a joint drive beyond its limits (2026-07-18)

Driving a joint past an enabled limit raises nothing, returns nothing, and leaves the joint where it was:

```python
lim.maximumValue = um.evaluateExpression("45 deg", "deg")
jm.rotationValue = um.evaluateExpression("90 deg", "deg")   # no exception
# jm.rotationValue is still whatever it was; the component did not move
```

There is no error and no warning. A script that assumes assignment means motion will report success on a model that never moved.

**Always read the value back** and compare against the request, and treat "assigned but unchanged" as a distinct outcome from "assigned and applied". Verify with geometry rather than the attribute alone when it matters: a 30 degree drive that lands moves the component's bounding box, and a 90 degree drive against a 45 degree limit leaves it identical.

## Ball joints only accept pitch=Z, yaw=X (2026-07-18)

`setAsBallJointMotion(pitchDirection, yawDirection)` looks like it takes any two principal axes. It does not. All nine principal-axis combinations were tested live on 2704.1.23 and exactly one is accepted:

```python
joint_input.setAsBallJointMotion(
    adsk.fusion.JointDirections.ZAxisJointDirection,   # pitch
    adsk.fusion.JointDirections.XAxisJointDirection,   # yaw
)
```

Every other pairing raises `Invalid parameter pitchDirection` or `Invalid parameter yawDirection`, including the intuitive `(X, Y)`. Hardcode the accepted pair; do not expose pitch and yaw as caller-controlled arguments, because eight of nine values are dead.

## Creating components from bodies: the API, and the rename it does (2026-07-18)

`Features.createComponentFromBodyFeatures` does not exist. Neither does a `CreateComponentFromBodyFeatureInput`. Samples referencing them are stale.

The working API is a method on the body:

```python
new_body = body.createComponent()          # world position preserved
new_body.parentComponent.name = "hinge_arm"
```

**The trap is what it does to the body name.** `createComponent()` moves the body into the new component and renames it to that component's default (`"Body1"`), discarding whatever you called it. Any later lookup by the original name silently fails, and in a multi-body script that shows up much later as a confusing `body_not_found`.

Restore it immediately:

```python
new_body = body.createComponent()
new_body.parentComponent.name = comp_name
new_body.name = original_name              # createComponent() clobbered this
```

## Moving an occurrence: rollTo and snapshots both revert the move (2026-07-18)

A move that assigns `occ.transform2` and then commits can end up as a perfect silent no-op: no exception, the API reports success, and the component has not moved. Two independent causes, and they stack.

**Rolling the timeline reverts the pending transform.** Calling `occ.timelineObject.rollTo(False)` before committing discards the assignment you just made. On a jointed component it is worse: the subsequent `design.snapshots.add()` raises `Has no pending snapshot`, because the roll consumed it. Do not roll.

**Ground-to-parent snaps the occurrence back.** Occurrences created by `createComponent()` default to `isGroundToParent = True`. `snapshots.add()` returns a ground-to-parent occurrence to its grounded position, silently undoing the move. Break the ground first:

```python
if getattr(occ, 'isGroundToParent', False):
    occ.isGroundToParent = False

before = occ.transform2.translation
m = occ.transform2
m.transformBy(matrix)
occ.transform2 = m
design.snapshots.add()
after = occ.transform2.translation          # verify, do not assume
```

**Always read the position back.** Beyond these two causes, a joint solver can legitimately override the requested move, so the only honest report is a before/after comparison rather than "the assignment did not raise".

## RigidGroups and ContactSets have no createInput (2026-07-18)

Both break the `createInput()` then `add(input)` pattern that most of the feature API follows.

```python
# Rigid group: add() takes the collection directly.
root.rigidGroups.add(occurrences, True)      # (occurrences, includeChildren)

# Contact sets live on the DESIGN, not the component.
design.contactSets.add(bodies)               # Component.contactSets does not exist
```

`RigidGroups.add` raises when an existing joint would make the group over-constrained, so wrap it rather than assuming a valid occurrence list succeeds.

**Contact sets additionally require assembly-context bodies.** The API wants bodies "in the context of the root component". A plain recursive walk over `component.bRepBodies` returns *native* bodies, which are rejected. For anything inside a component you need the proxy from the occurrence:

```python
for i in range(root.occurrences.count):
    occ = root.occurrences.item(i)
    for j in range(occ.bRepBodies.count):    # proxies, not occ.component.bRepBodies
        b = occ.bRepBodies.item(j)
```

This native-versus-proxy distinction is a general assembly-scripting trap, not specific to contact sets. `occ.bRepBodies` gives assembly-context proxies; `occ.component.bRepBodies` gives natives in component space.

## Shell has no direction enum, and a closed shell still needs the body (2026-07-18)

`adsk.fusion.ThicknessDirections` does not exist. There is no direction parameter on `ShellFeatureInput`. Direction is expressed purely by which of two independent properties you set:

| Intent | Set |
|---|---|
| Inward (the common case) | `insideThickness` |
| Outward | `outsideThickness` |
| Both | both, independently |

Setting `insideThickness` while intending "outside" is a silent wrong result, not an error: you get a shell of the right wall thickness growing the wrong way.

**A closed shell (hollow, no opening) still needs the body in the input collection.** An empty collection is rejected by `ShellFeatures.add`. Pass faces to remove for an open shell, or the body itself for a closed one.

Verify with volume, which is exact and unambiguous. For a 20x20x20 mm cube: open-top with 2 mm inside walls is 1952 mm3; fully closed with 2 mm outside walls is 4064 mm3.

## Chamfer's createInput2 takes no arguments (2026-07-18)

The chamfer API changed shape. `createInput2()` now takes no arguments at all, and edge sets are added through a `chamferEdgeSets` collection:

```python
chm_in = root.features.chamferFeatures.createInput2()          # no args
chm_in.chamferEdgeSets.addEqualDistanceChamferEdgeSet(
    edges, adsk.core.ValueInput.createByString("1 mm"), False)  # isTangentChain
```

The older `add*ChamferEdges` methods on the input object no longer exist. Argument order is a live trap on the two-value variants: `isFlipped` comes **before** `isTangentChain`.

| Set | Signature |
|---|---|
| Equal | `addEqualDistanceChamferEdgeSet(edges, distance, isTangentChain)` |
| Two distance | `addTwoDistancesChamferEdgeSet(edges, d1, d2, isFlipped, isTangentChain)` |
| Distance and angle | `addDistanceAndAngleChamferEdgeSet(edges, distance, angle, isFlipped, isTangentChain)` |

Note this also means chamfer supports tangent chaining, which the previous single-call form did not expose.

## Ribs are not scriptable (2026-07-18)

`RibFeatures` is a read-only collection in 2704.1.23. It has `item`, `itemByName`, and `count`, but no `createInput` and no `add`. There is no way to create a rib from the API.

Do not spend time debugging this; it is not a signature problem. Model the rib as a thin extrude instead: sketch the rib cross-section as a closed profile and extrude it with `operation='join'`. That is parametric, survives rebuilds, and gives you direct control over the wall thickness that the rib feature would have inferred.

Worth re-testing on future Fusion releases, since a read-only collection suggests the feature is exposed but not yet writable.

## An unset pattern direction two produces 3 coincident bodies (2026-07-18)

`RectangularPatternFeatureInput` does not treat an unconfigured direction two as "a single row". Leaving `setDirectionTwo` uncalled multiplies every instance by three, in place:

| Direction two | quantity=1 | quantity=4 |
|---|---|---|
| Not set | 3 bodies | 12 bodies |
| `setDirectionTwo(axis, 1, "0 mm")` | 1 body | 4 bodies |

**This is invisible to almost every check.** The feature is created, the API reports success, the positions along direction one are correct, and each body has exactly the right volume. Only the body count is wrong, and the duplicates are coincident so they are hard to see in the viewport too.

Always configure direction two, even for a single-direction pattern:

```python
pat_in.setDirectionTwo(
    root.yConstructionAxis,                          # must differ from direction one
    adsk.core.ValueInput.createByReal(1),
    adsk.core.ValueInput.createByString("0 mm"),
)
```

The second axis must not be the same entity as the first, or Fusion rejects the input. If direction one is Y, use Z.

**General lesson: count entities before and after any feature that replicates geometry.** Position and volume checks pass clean here.

## Hole placement picks a face, and "tallest" is the wrong heuristic (2026-07-18)

Positioning a hole by world XY requires choosing a face to place the sketch point on. Selecting the highest `+Z` face in the body is the obvious approach and it breaks on any stepped part: a hole aimed at a lower step gets placed on the plane of the taller one, floating in mid-air above its intended target.

The failure mode depends on the extent:

- Distance extent: `No target body found to cut or intersect!`
- Through-all: no error at all, but the hole starts from the wrong plane, so the depth and any counterbore land wrong.

**Prefer the highest `+Z` face whose XY extent actually contains the target point**, and fall back to tallest only when none does:

```python
for i in range(body.faces.count):
    f = body.faces.item(i)
    ok, n = f.evaluator.getNormalAtPoint(f.pointOnFace)
    if not (ok and abs(n.z - 1.0) < 1e-3):
        continue
    bb = f.boundingBox
    contains = (bb.minPoint.x <= tx <= bb.maxPoint.x and
                bb.minPoint.y <= ty <= bb.maxPoint.y)
    ...
```

Return the chosen face's Z in the result so callers can see which plane the hole actually started from. Note this whole approach is world-Z locked: rotate the body and there is no `+Z` face at all.

## areaProperties is a method, not a property (2026-07-18)

```python
prof.areaProperties.area        # returns a bound method's attribute: garbage
prof.areaProperties().area      # correct
```

The property form does not raise. It silently yields `None` in any downstream arithmetic, so area-based logic (matching profiles by size, sorting, picking the largest) degrades to whatever the fallback path is and appears to work.

This had been silently broken in profile matching for the lifetime of the code before anyone noticed, because the fallback (take profile 0) is correct in the single-profile case that covers most designs. If you have code selecting profiles by area and it "always seems to pick the first one", check for this.

## The .profile getter itself raises on a stale feature (2026-07-18)

Reading inputs from a broken feature is not safe. On an `ExtrudeFeature` whose sketch curves were deleted, the `.profile` getter raises rather than returning `None` or an empty collection:

```
InternalValidationError: res == 0
```

This matters for any "capture the inputs, delete, recreate" repair routine (see G10). The crash happens during capture, before you have anything to work with, and an uncaught exception rolls back the whole `execute` transaction.

Wrap every input read from a suspect feature, and treat a raising getter as "not rebuildable" so the original feature is preserved rather than destroyed by a repair that cannot finish.

**Related rule for any delete-then-recreate routine: validate everything you can before `deleteMe()`.** Check that the target sketch resolves unambiguously *and* that it still has at least one closed profile. A sketch that resolves but has `profiles.count == 0` passes a naive preflight, lets the delete run, then fails recreation, leaving the design with the feature simply gone.

## Generating Python? json.dumps(None) is not `None` (2026-07-18)

Specific to tools that generate Fusion scripts rather than calling the API directly, but it is a silent killer.

Interpolating a value with `json.dumps()` is correct for strings and wrong for everything else, because JSON's literals are not Python's:

| Value | `json.dumps()` emits | Valid Python? |
|---|---|---|
| `"45 deg"` | `"45 deg"` | yes |
| `None` | `null` | **no** |
| `True` | `true` | **no** |

The generated script then dies inside Fusion with `NameError: name 'null' is not defined`, at whatever line the token landed on.

**`ast.parse()` does not catch this.** `null`, `true`, and `false` are all syntactically valid Python identifiers, so the script parses cleanly and only fails at run time. A generator test suite built on `ast.parse` will pass while every real call fails.

Use `repr()` for anything that is not guaranteed to be a string, and test by walking the AST for `Name` nodes matching those three tokens:

```python
leaks = [n.id for n in ast.walk(ast.parse(src))
         if isinstance(n, ast.Name) and n.id in {"null", "true", "false"}]
```
