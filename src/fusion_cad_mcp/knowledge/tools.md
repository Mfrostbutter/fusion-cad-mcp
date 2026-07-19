# Fusion MCP tool reference

Complete reference for the 75 typed tools exposed by `fusion-cad-mcp`. Every signature, enum, return key, and error code here was read out of the server source and verified against a live Fusion build, not inferred.

74 of the 75 are usable. `rib` is registered but permanently returns `rib_not_scriptable`, because the Fusion API exposes `RibFeatures` as a read-only collection. It is documented in Group 5 along with the workaround.

`SKILL.md` is the operating manual and tells you *which* tool to reach for. This file tells you *exactly* how to call it. Load this when you need a signature, an enum, or an error code.

## How to read this file

Tools are grouped the way the server registers them. Within a group, shared behavior is stated once at the top of the group and not repeated per tool.

Three conventions hold everywhere and are not repeated:

- **Units in, units out.** You pass mm. You get mm back. Fusion's internal unit is cm and the server converts at the boundary. The exceptions are called out explicitly per tool (angles, volumes, and a handful of `*_cm` fields).
- **Expression strings are not numbers.** Any parameter documented as an expression (`radius`, `offset`, `expression`, `min_value`, …) is passed verbatim to Fusion's `ValueInput.createByString`. It must carry its own unit (`"8 mm"`, `"45 deg"`) or be a user-parameter name (`"corner_r"`, `"wall_t * 2"`). A bare number inherits the document's default units.
- **Two failure layers.** Client-side validation fails before Fusion is ever called, and returns a generic code (`invalid_input`, `invalid_confirm`, `invalid_count`) with the specific message in `message`. In-Fusion failures return a specific code (`body_not_found`, `handle_invalid`, …). Match on both.

## The envelope

Every one of the 75 tools returns the same shape. This is the single parsing contract:

```python
{
  "ok": bool,              # always present
  "message": str,          # raw stdout from the generated script
  "result": dict | None,   # the tool's payload
  "state": dict | None,    # reserved; no tool populates this today
  "image": dict | None,    # {data: <base64>, mime_type: "image/png"}
  "error": str | None,     # error code, present only when ok is False
  "traceback": str | None  # Fusion traceback, when one exists
}
```

Keys whose value is `None` are dropped, except `ok`.

Two traps worth internalizing:

- **`ok: True` does not mean what you asked for happened.** `doc_state` returns `ok: True` with `{"active_design": false}` when no design is open. `interference_check` returns `ok: True` with `pair_count: 0`. `assert_profiles` is the tool that turns a mismatch into `ok: False`. Read `result`, not just `ok`.
- **Parse failures are their own class.** If a generated script raises before printing its JSON line, you get `error: "<tool_name>_parse_failed"` and the raw traceback in `message`. That means the operation may have partially applied. It is not a validation error and re-running blindly can double-apply.

## Handles: the two addressing modes

The server uses two ways to name things, and mixing them up is the most common source of confusion.

**Name-addressed.** Bodies, sketches, components, occurrences, joints, features, construction geometry. You pass a plain string: `"main_body"`, `"outer"`, `"Hinge:1"`. Lookup is exact and case-sensitive, first-match-wins, with no ambiguity detection. Duplicate names silently resolve to whichever the traversal hits first.

**Handle-addressed.** Faces, edges, vertices, sketch points. These have no stable name, so they are addressed by an opaque handle:

```
kind:path:token
```

- `kind` is one of: `sketch, profile, body, face, edge, vertex, feature, component, occurrence, param, joint, ucs, plane, axis, point`
- `path` is human-readable debug decoration (`main_body/face[3]`). It is *not* used for resolution.
- `token` is Fusion's `entityToken` and is the actual resolver key.

`list_body_entities` is the bridge: give it a body name, get back handles for its faces, edges, and vertices. That is the only way to reach sub-entity geometry.

Handles go stale. When an edit deletes or regenerates the entity behind a token, any tool consuming it returns:

```json
{"ok": false, "error": "handle_invalid",
 "detail": {"handle": "<the handle>", "reason": "not_found_in_active_doc"}}
```

Re-run `list_body_entities` to get fresh handles. Never cache handles across a feature edit.

**Which tools emit handles:** `create_sketch` (`handle`), `add_rectangle` (`start_point_handle` / `end_point_handle` per line), `list_body_entities` (`handle` per face/edge/vertex), `create_joint` (`joint_token`, a bare token you must assemble into a handle yourself). Everything else returns names or bare integer indices.

---

# Group 1: Document and state

Shared: none of these tools take a component scope. `doc_state` and the counts it returns are **root-component only**.

## `doc_state()`

The orientation tool. Call it first when the document state is uncertain.

**Returns one of two structurally different shapes.** Branch on `result.active_design`, not on `ok`:

No design open (still `ok: True`):
```json
{"active_design": false}
```

Design open, exactly ten keys:

| Key | Type | Meaning |
|---|---|---|
| `active_design` | bool | always `true` in this shape |
| `doc_name` | str \| null | `null` if no document object |
| `is_dirty` | bool \| null | unsaved changes. Gate `close()` on this |
| `workspace` | str \| null | display name, e.g. `"Design"` |
| `units` | str | document default length units, e.g. `"mm"` |
| `bodies_count` | int | root only |
| `sketches_count` | int | root only; includes leaked construction helper sketches |
| `features_count` | int | root only |
| `components_count` | int | `allOccurrences`, which counts *instances*, so one component placed 3 times contributes 3 |
| `parameters_count` | int | user parameters only |

Errors: `doc_state_parse_failed`.

## `list_open_docs()`

Passthrough to Fusion's `document/recent`. Despite the name this is Fusion's **recent** list, not strictly currently-open documents. Result shape is Fusion's, not normalized by the server.

## `list_projects()`

Passthrough. Returns all projects/hubs visible to the user. Result shape is Fusion's.

## `search_docs(query, project=None)`

Fuzzy document-name search. `project` scopes it; omit to search everywhere. No client-side validation, so an empty query reaches Fusion. Result shape is Fusion's.

## `open_doc(name, project=None)`

Fuzzy-matched open by name. No validation. Result shape is Fusion's.

## `save()`

Saves the active document. **Untitled documents are refused by Fusion**: the initial Save As must happen in the Fusion UI. The refusal surfaces as a structured error; surface it to the user rather than retrying.

## `save_as(path)`

Note: on the wire this is still `operation: "save"` with a `path` key, because Fusion's execute schema has no documented save-as. Fusion may accept it or return its own error, passed through verbatim. Fusion may still refuse programmatic Save As on Untitled documents. No client-side path validation.

## `close(confirm="prompt")`

| `confirm` | Effect |
|---|---|
| `"prompt"` (default) | Fusion shows its own dialog if dirty |
| `"save"` | saves, then closes |
| `"discard"` | closes, losing unsaved changes |

Error `invalid_confirm`: `confirm must be one of ['discard', 'prompt', 'save'], got '<x>'`.

**Policy, not enforced by code:** never pick `"save"` or `"discard"` on your own initiative for a dirty document. Both are accepted values; the constraint is on you. Pass `"prompt"` or ask the user. Check `doc_state().is_dirty` first.

## `undo(count=1)` / `redo(count=1)`

Error `invalid_count`: `count must be >= 1`. No upper bound.

**Undo is atomic on the entire prior `execute` call, not on one CAD operation.** A script that added parameters *and* geometry loses both, silently. Prefer targeted deletion over undo.

The loop returns early on first failure and returns only the last envelope on success, so a partial failure at step 3 of 5 is not distinguishable from a step-1 failure. Result shape is Fusion's.

---

# Group 2: Parameters

## `add_parameters(defs)`

Idempotent. Existing names are **skipped, never overwritten**, so use `update_parameter` to change one.

`defs` is a list of objects: `{name, expression, units?, comment?}`. `units` and `comment` default to `""`.

Validation (fail-fast on the first bad def, all returning `error: "invalid_defs"`):

| Condition | Message |
|---|---|
| not a list | `defs must be a list` |
| empty | `defs must be non-empty` |
| element not an object | `defs[i] must be an object` |
| name not a non-empty string | `defs[i].name must be a non-empty string` |
| expression not a non-empty string | `defs[i].expression must be a non-empty string` |
| name is a reserved math identifier | `defs[i].name '<x>' is a reserved math identifier; ...` |
| name starts with a digit | `defs[i].name '<x>' must start with a letter or underscore` |

**Reserved math names are blocked at generation time** because Fusion silently binds expressions referencing them to the math function instead of your parameter. All 27, matched case-sensitively (so `PI` and `Max` slip through and will bite you):

```
sin cos tan asin acos atan atan2 sinh cosh tanh
abs sqrt exp log ln log10 min max round floor ceil pi e
```

Returns: `ok`, `added` (`[{name, expression}]`, the *requested* expression, not read back), `skipped` (`[{name, current_expression}]`), `total_params`.

**Partial-application trap:** the per-parameter `add` is not individually guarded. If Fusion rejects one def mid-loop, earlier adds are already applied, no JSON is printed, and you get `parse_failed` with no record of what landed. Re-run is safe because the tool is idempotent.

## `update_parameter(name, expression)`

Errors: `invalid_name`, `invalid_expression` (both `must be a non-empty string`), `param_not_found`.

Only `userParameters` is searched. Model and feature parameters are unreachable.

Returns: `ok`, `name`, `before`, `after` (read back), `value` (**raw internal units**: cm for lengths, radians for angles, no conversion).

Note this tool does *not* apply the reserved-math-name guard. A rejected expression raises inside Fusion and surfaces as `parse_failed`, not a descriptive error.

## `list_parameters()`

No arguments. Returns `ok`, `count`, `parameters`, each entry `{name, expression, value, units, comment}`.

`value` is raw internal units (cm / radians), unconverted. The output key is `units` but it comes from Fusion's singular `unit` property. User parameters only.

---

# Group 3: Sketch geometry

**The single biggest gotcha in this group:** most sketch tools look up sketches in the **root component only**. A sketch inside a sub-component is invisible to them and returns `sketch_not_found`, with no `component_name` parameter to fix it.

| Lookup behavior | Tools |
|---|---|
| Root component only | `create_sketch`, `add_line`, `add_rectangle`, `add_circle`, `add_ellipse`, `add_arc`, `add_spline`, `add_polygon`, `add_geometric_constraint`, `add_dimension`, `assert_profiles` |
| Recursive, ambiguity-aware, accepts `component_name` | `probe_sketch_dimensions`, `edit_sketch_dimension` |

Shared errors across the group: `no_active_design`, `sketch_not_found`, `<tool>_parse_failed`.

Points are `[x, y]` in mm. Z is always 0, since these are 2D sketch coordinates.

## Entity references

`add_geometric_constraint` and `add_dimension` address sketch geometry through a small ref grammar, parsed before Fusion is called:

| Ref | Resolves to |
|---|---|
| `origin` | the sketch origin point |
| `line:N` | line N |
| `line:N:start` / `line:N:end` | its endpoints |
| `circle:N` | circle N |
| `circle:N:center` | its center point |
| `arc:N` | arc N |
| `arc:N:start` / `arc:N:end` / `arc:N:center` | its points |
| `point:N` | sketch point N (no sub-entity allowed) |
| `dim:N` | dimension N (no sub-entity allowed) |

**There is no `ellipse:` or `spline:` ref form.** Ellipses and fitted splines cannot be constrained or dimensioned through these tools at all.

Indices are positional into the live collection and shift when geometry is deleted. Ref errors all surface as `invalid_input`: `malformed entity ref`, `<ref>: index must be an int`, `<ref>: unknown sub-entity`, `<ref>: unknown entity kind`.

## `create_sketch(plane, name)`

`plane` is `xy`, `xz`, or `yz`, case-insensitive. Root component only.

Errors: `invalid_input` (`plane must be one of xy / xz / yz`), `sketch_name_taken`.

Returns: `ok`, `sketch_name`, `plane` (lowercased), `handle`, formatted as `sketch:<name>:<token>`.

**Sketch plane orientation is a live trap.** XY is the safe default. XZ maps sketch Y to *negative* world Z. YZ extrudes along world X and inverts sketch X. For any non-XY plane, drop a test point and read its `worldGeometry` before committing coordinates.

## `add_line(sketch, p1, p2)`

`p1`, `p2` are `[x, y]` mm, exactly 2 elements. Error `invalid_input`: `p1 and p2 must be [x, y] in mm`.

Returns: `ok`, `line_index`.

## `add_rectangle(sketch, kind, p1, p2, p3=None)`

| `kind` | Points |
|---|---|
| `"center"` | p1 = center, p2 = a corner |
| `"corner"` | p1, p2 = opposite corners |
| `"3pt"` | p1, p2 define one edge; p3 sets the other edge direction |

Errors. `invalid_input`: `p1 and p2 must be [x, y] in mm`, `kind must be one of ['3pt', 'center', 'corner']`, `kind=3pt requires p3 as [x, y] in mm`.

Returns: `ok`, `kind`, `line_indices` (the 4 new indices), `line_handles`.

`line_handles` is a list of `{index, start_point_handle, end_point_handle}` where the handles are `point:<sketch>/line[<i>]/start|end:<token>`. Sketch lines themselves have no `entityToken`; only their endpoints do, which is why you get point handles rather than line handles.

**Silent degradation:** if token capture throws for a line, its entry degrades to just `{index}` with the handles missing, and the call still reports `ok: True`. Check for the keys before using them.

## `add_circle(sketch, kind, center=, radius_mm=, p1=, p2=, p3=)`

| `kind` | Required |
|---|---|
| `"center_radius"` | `center` `[x,y]` mm, `radius_mm` (radius, not diameter) |
| `"3pt"` | `p1`, `p2`, `p3` each `[x,y]` mm |

Errors. `invalid_input`: `kind must be one of ['3pt', 'center_radius']`, `kind=center_radius requires center=[x,y] and radius_mm`, `kind=3pt requires p1, p2, p3 each as [x, y] in mm`.

Returns: `ok`, `circle_index`, `kind`. Unknown keyword arguments are silently ignored, so a typo like `radius=5` produces the "requires radius_mm" error rather than a name error.

## `add_polygon(sketch, sides, center, vertex, inscribed=True)`

`sides` >= 3. `vertex` is a point on the polygon and defines both radius and rotation. `inscribed=True` puts vertices on the radius; `False` circumscribes.

Errors. `invalid_input`: `sides must be >= 3`, `center and vertex must be [x, y] in mm`.

Returns: `ok`, `sides`, `line_indices`.

## `add_ellipse(sketch, center, major_axis_end, minor_axis_end)`

All three are `[x, y]` mm. Error `invalid_input`: `center / major_axis_end / minor_axis_end must each be [x, y] in mm`.

Returns: `ok`, `ellipse_index`. **Cannot be constrained or dimensioned** (no `ellipse:` ref form).

## `add_arc(sketch, kind, ...)`

| `kind` | Required |
|---|---|
| `"3pt"` | `p1`, `p2`, `p3` |
| `"center_start_end"` | `center`, `start`, `end` |
| `"center_start_sweep"` | `center`, `start`, `sweep_radians` |

**`sweep_radians` is radians, passed through unscaled.** Positive is counter-clockwise. Not degrees, not mm.

Errors: `invalid_input` with `kind must be one of ['3pt', 'center_start_end', 'center_start_sweep']` or the matching per-kind requirement message.

Returns: `ok`, `arc_index`, `kind`.

## `add_spline(sketch, points, closed=False)`

`points` is a list of at least 2 `[x, y]` mm points.

Errors. `invalid_input`: `points must be a list of at least 2 [x, y] points in mm`, `points[i] must be [x, y]`.

Returns: `ok`, `spline_index`, `point_count`, `closed`. **Cannot be constrained or dimensioned** (no `spline:` ref form).

## `add_geometric_constraint(sketch, kind, entities)`

| `kind` | Entities | Expects |
|---|---|---|
| `horizontal`, `vertical` | 1 | a line |
| `fix` | 1 | any |
| `parallel`, `perpendicular` | 2 | lines |
| `coincident`, `tangent`, `equal` | 2 | any |
| `concentric` | 2 | circle or arc |
| `midpoint` | 2 | point and line |
| `symmetric` | 3 | two entities about a line |

**The expected shape is not checked.** Passing `parallel` two circle refs generates valid Python that fails inside Fusion. Entity count *is* checked.

Errors. `invalid_input`: `kind must be one of [...]`, `kind=<x> requires N entity refs, got M`, plus any ref-grammar error.

Returns: `ok`, `kind`, `applied_to` (your refs, echoed). No constraint index is returned, so you cannot address the constraint afterwards.

## `add_dimension(sketch, kind, entities, expression, text_pos=None)`

| `kind` | Entities | Expects |
|---|---|---|
| `distance_h`, `distance_v`, `distance` | 2 | point refs |
| `angle` | 2 | line refs |
| `radial`, `diameter` | 1 | circle or arc ref |

`expression` is passed verbatim to the dimension's parameter. **Parameter-name expressions work and propagate** when the parameter changes (`"length / 2"`, `"wall_t * 2"`). Use a literal like `"25 mm"` only when you want a baked value.

`text_pos` is `[x, y]` mm for the dimension text. A wrong-length value is **silently replaced with `[0, 0]`**, not rejected.

Errors. `invalid_input`: `kind must be one of [...]`, `expression must be a non-empty string`, `kind=<x> requires 2 point refs`, etc. Note `kind` and `expression` are validated *before* entity count, so a bad expression masks a bad count.

Returns: `ok`, `kind`, `dim_index`, `expression` (read back, Fusion-normalized), `value_cm`, `value_mm`.

**Angular dimensions report garbage in `value_cm` / `value_mm`.** The internal value is radians and this tool multiplies by 10 regardless. For angles, ignore both fields and read back with `probe_sketch_dimensions`.

## `assert_profiles(sketch, expected)`

The correctness gate. Run it after closing every sketch, before extruding.

`expected` must be a non-negative int. Error `invalid_input`: `expected must be a non-negative int`.

Returns (on both pass and fail): `ok`, `actual`, `expected`, `isFullyConstrained`.

On mismatch the envelope carries `error: "profile_count_mismatch"` with the counts still in `result` for diagnosis. This is deliberately distinct from a script error so you can tell "the assertion failed" from "the script broke".

**Why this matters:** a self-intersecting polygon returns `profiles.count == 2` silently rather than raising. A closed simple profile is 1. Zero means the sketch never closed. Checking this is the only reliable signal.

## `probe_sketch_dimensions(sketch, component_name=None)`

Recursive lookup. Dumps every dimension with its parameter name, expression, value, and the coordinates of the geometry it constrains. Use it to work out which auto-named dim (`d278`) drives which feature.

Errors: `sketch_name_ambiguous` (includes `matches` and a hint to pass `component_name`), `sketch_not_found`.

Returns: `ok`, `sketch_name`, `component`, `plane`, `isFullyConstrained`, `profile_count`, `dimension_count`, `dimensions`.

Each dimension entry: `dim_class`, `param_name`, `expression`, `unit`, `entity_one`, `entity_two`, plus **one of** `value_mm` (length units), `value` + `unit` (other units), or `value_error`.

Entity descriptors carry `type` and whichever of `point_mm`, `start_mm`/`end_mm`, `center_mm`, `radius_mm`, `major_radius_mm`/`minor_radius_mm` apply.

## `edit_sketch_dimension(sketch, dim_name, new_expression, component_name=None)`

Recursive lookup. Changes a dimension's expression by parameter name, then runs `computeAll()` before returning, so the reported values reflect the recomputed model.

Errors: `invalid_input` (`new_expression must be a non-empty string`), `sketch_name_ambiguous`, `sketch_not_found`, `dim_not_found`, `expression_rejected`.

`dim_not_found` helpfully includes `available_dims` so you can correct course without another call. `expression_rejected` includes `tried`, `old_expression`, and `detail`.

Returns: `ok`, `sketch`, `component`, `param_name`, `old_expression`, `new_expression`, `unit`, `isFullyConstrained_after`, plus **one of** `new_value_deg` (angular), `new_value_mm` (length), or `new_value_raw`.

**Always follow this with `audit_feature_health`.** Moving a dimension commonly breaks downstream fillets whose target edges shifted.

---

# Group 4: Construction geometry

Shared: all coordinates are `[x, y, z]` in mm. `offset` and `angle` are expression strings. Everything resolves against the **root component only**.

**Plane and axis name resolution:** the principal names `xy`/`xz`/`yz` and `x`/`y`/`z` are matched case-insensitively and **shadow any user-created entity with the same name**. Anything else is an exact, case-sensitive scan of root construction geometry.

**Helper sketches leak.** Three of these tools create a permanent named sketch on root XY that is never cleaned up: `_cplane_helper_3pt`, `_caxis_helper_2pt`, `_cpoint_helper`. They inflate `doc_state().sketches_count` and repeated calls produce Fusion-disambiguated duplicates.

## `create_construction_plane(kind, name=None, ...)`

| `kind` | Required parameters |
|---|---|
| `"offset"` | `base_plane` + `offset` |
| `"midplane"` | `plane_a` + `plane_b` |
| `"at_angle"` | `axis` + `base_plane` + `angle` |
| `"3_points"` | `p1` + `p2` + `p3`, each `[x,y,z]` mm |

Errors. `invalid_input`: `kind must be one of ['3_points', 'at_angle', 'midplane', 'offset']`, or the per-kind requirement message. In-Fusion: `base_plane_not_found`, `plane_a_not_found`, `plane_b_not_found`, `axis_not_found`.

Note `base_plane_not_found` includes a `name` key from the `offset` branch but **not** from the `at_angle` branch. Do not rely on it.

Returns: `ok`, `kind`, `name`. **`name` is the handle**, so feed it back to other tools or to `delete_construction`.

## `create_construction_axis(kind, name=None, ...)`

| `kind` | Required |
|---|---|
| `"2_points"` | `p1` + `p2`, each `[x,y,z]` mm |
| `"normal_to_face_by_geometry"` | `body` + `face_normal` `[nx,ny,nz]` |

Face selection scans `body.faces` in index order and takes the **first** face whose normal matches componentwise within `1e-3`. On a cylinder or a patterned part several faces can match and you get the lowest index. Pass a unit vector; the comparison is not normalized.

Errors: `invalid_input` with `kind must be one of ['2_points', 'normal_to_face_by_geometry']` or the per-kind message. In-Fusion: `body_not_found`, `face_not_found_by_normal`.

Returns: `ok`, `kind`, `name`.

`face_point` appears in the signature but is **never read**. It is dead; passing it does nothing.

## `create_construction_point(coords, name=None)`

`coords` is `[x, y, z]` mm. Error `invalid_input`: `coords must be [x, y, z] in mm`.

Returns: `ok`, `name`, `coords_mm` (an echo of your input, not a readback).

## `delete_construction(name)`

Exact, case-sensitive. **No principal-name aliasing here**. `"xy"` matches only an entity literally named `xy`, and the principal planes cannot be deleted this way.

Sweeps planes, then axes, then points, and deletes **every** match across all three. This is a multi-delete: duplicate names all go.

Errors: `invalid_input` (`name must be a non-empty string`), `construction_not_found`.

Returns: `ok`, `deleted`, a list of `"<collection>/<name>"` strings.

---

# Group 5: Features

Shared behavior across this group:

- **Sketches resolve in the root component only** for `extrude` and `revolve`. A sketch inside a sub-component returns `sketch_not_found` and there is no parameter to reach it. `rebuild_feature` is the one exception; it walks the whole tree.
- **Features resolve in the root component only** for `mirror_feature`, `pattern_rectangular`, and `pattern_circular`. These look up a *feature* name first and fall back to a *body* name searched tree-wide, so a feature in a sub-component yields `target_not_found` unless a body happens to share the name.
- **Bodies resolve tree-wide**, first match wins, no ambiguity detection.
- `name` always renames *after* creation, so the returned `feature_name` is your name.
- Plane and axis arguments accept the principal names (`xy`/`xz`/`yz`, `x`/`y`/`z`, lowercased) or the exact case-sensitive name of root construction geometry.

## `extrude(sketch, profile_index=0, operation="new_body", extent_kind="distance", expression=None, direction="positive", is_full_length=True, participants=None, name=None)`

| `extent_kind` | Requires | Also uses |
|---|---|---|
| `"distance"` | `expression` | `direction` (`"positive"` / `"negative"`) |
| `"symmetric"` | `expression` | `is_full_length` |
| `"all_positive"` | nothing | nothing |
| `"all_negative"` | nothing | nothing |

`operation`: `new_body`, `join`, `cut`, `intersect`, `new_component`.

**`direction` and `is_full_length` are each consumed by exactly one extent kind** and silently ignored by the others. `all_positive` / `all_negative` ignore `expression` entirely.

`participants` (body names) scopes a cut/join/intersect to specific bodies. Without it, a cut can consume bodies you did not intend.

Errors: `invalid_input` (bad `operation`, bad `extent_kind`, `extent_kind=<x> requires an expression`, bad `direction`), `sketch_not_found`, `profile_index_out_of_range` (carries `got` and `count`), `participant_not_found`.

Returns: `ok`, `feature_name`, `operation`, `extent_kind`, `bodies_added` (names; `[]` for a cut).

**Use `all_negative` rather than a distance when cutting through unknown depth.** A fixed distance stops short when a flange or divider sits below the sketch plane.

## `revolve(sketch, profile_index=0, axis="z", operation="new_body", extent_kind="full", angle=None, is_symmetric=False, participants=None, name=None)`

`extent_kind` is `"full"` or `"angle"`. `"angle"` requires `angle` and honors `is_symmetric`.

**`"full"` hardcodes 360 degrees and ignores both `angle` and `is_symmetric`.**

`axis` must be a construction axis. Sketch lines cannot be used as the axis of revolution here.

Errors: `invalid_input`, `sketch_not_found`, `profile_index_out_of_range`, `axis_not_found`, `participant_not_found`.

Returns: same shape as `extrude`.

## `fillet_edges_by_geometry(body, radius, parallel_to="z", min_length_mm=None, is_tangent_chain=True, name=None)`

Selects edges by geometry rather than by handle, so no `list_body_entities` round trip.

`parallel_to`: `x`, `y`, `z`, or `any`. "Parallel to axis A" means the other two coordinates of the two endpoints match within `1e-6` cm and the A coordinate differs by more than that.

**Both filters use chord distance between the endpoints, not arc length.** Consequences worth internalizing:

- A closed circular edge has coincident endpoints, so it measures 0 and is never selected by an axis filter, and is always removed by any positive `min_length_mm`.
- A curved edge whose endpoints happen to share two coordinates is falsely classified as axis-parallel.
- Arcs are under-measured, so `min_length_mm` is more aggressive on curves than you expect.

Errors: `invalid_input` (`parallel_to must be one of ['any', 'x', 'y', 'z']`, `radius must be a non-empty expression string`, `min_length_mm must be >= 0`), `body_not_found`, `no_edges_matched` (carries `parallel_to` and `min_length_mm`).

Returns: `ok`, `feature_name`, `edges_filleted`, `radius`.

## `chamfer_edges_by_geometry(body, distance, parallel_to="z", kind="equal", distance2=None, angle=None, min_length_mm=None, name=None)`

Same edge filter and same chord-distance caveats as the fillet above.

| `kind` | Requires |
|---|---|
| `"equal"` | `distance` |
| `"two_dist"` | `distance` + `distance2` |
| `"dist_angle"` | `distance` + `angle` |

Errors: `invalid_input` (bad `parallel_to`, bad `kind`, `distance is required`, `kind=two_dist requires distance2`, `kind=dist_angle requires angle`), `body_not_found`, `no_edges_matched` (no diagnostic keys here, unlike the fillet).

Returns: `ok`, `feature_name`, `edges_chamfered`, `kind`. Note it echoes `kind`, not the distances.

**Chamfer has no tangent-chain option**, unlike fillet. It is hardcoded off.

## `add_hole(body, position_mm, diameter, kind="simple", cbore_diameter=None, cbore_depth=None, csink_diameter=None, csink_angle=None, extent_kind="all", depth_expression=None, name=None)`

| `kind` | Requires |
|---|---|
| `"simple"` | `diameter` |
| `"counterbore"` | `cbore_diameter` + `cbore_depth` |
| `"countersink"` | `csink_diameter` + `csink_angle` |

`extent_kind` is `"all"` (drills downward through everything) or `"distance"` (requires `depth_expression`).

**Face selection.** The hole is placed on a `+Z`-facing face, chosen as: the highest `+Z` face whose bounding box contains your XY, falling back to the tallest `+Z` face overall. Two things follow:

- **`position_mm[2]` is ignored.** The Z comes from the chosen face. Pass it for readability; it does nothing.
- **The body must have a `+Z` face.** Rotate the body and you get `no_top_face_found`. This is world-Z locked.

Check `position_on_face` in the response. `false` means your XY was not inside any `+Z` face and the fallback was used, so the hole is probably misplaced. Compare `face_plane_z_mm` against the step you meant to drill.

Containment is a bounding-box test, so a target inside the bbox of a non-rectangular face but outside its real boundary still reports `true`.

Errors: `invalid_input` (per-kind requirement messages), `body_not_found`, `no_top_face_found`.

Returns: `ok`, `feature_name`, `kind`, `diameter`, `position_mm` (echo, including the ignored Z), `face_plane_z_mm`, `position_on_face`.

**Side effect:** every call leaves a sketch named `_hole_position_helper` in the design, and the hole is parametrically bound to it. Deleting that sketch breaks the hole.

## `shell(body, thickness, face_normals_to_remove=None, direction="inside", name=None)`

`direction` is `"inside"`, `"outside"`, or `"both"`. There is no direction enum in the Fusion API; direction selects which thickness property gets set.

**`"both"` gives a total wall of 2x `thickness`**, since it sets inside and outside to the same expression rather than splitting one thickness.

`face_normals_to_remove` is a list of `[nx, ny, nz]` unit vectors. Every face whose sampled normal matches within `1e-3` per component is removed, so `[[0,0,1]]` on a stepped part removes *every* upward face, not just the top one. Omit it for a closed hollow shell.

Normals are sampled at one arbitrary point per face, so this matches planar faces reliably and curved faces unpredictably.

Errors: `invalid_input` (`thickness expression required`, `direction must be inside/outside/both`), `body_not_found`, `no_faces_matched_normals` (only when you passed normals).

Returns: `ok`, `feature_name`, `faces_removed`, `thickness`, `direction`.

Verify with volume. For a 20 mm cube: open-top 2 mm inside is 1952 mm3; closed 2 mm outside is 4064 mm3.

## `pattern_rectangular(feature_or_body, x_axis="x", x_count=2, x_distance=None, y_axis=None, y_count=1, y_distance=None, name=None)`

`x_distance` and `y_distance` are **total extents**, not spacing. Four instances over `"60 mm"` sit at 0, 20, 40, 60.

`x_distance` is required when `x_count > 1`; `y_distance` when `y_axis` is given and `y_count > 1`.

Direction two is always configured internally, pinned to one instance when you omit `y_axis`. This is not optional: leaving it unset makes Fusion produce three coincident copies of every instance. See `gotchas.md`.

The internal fallback axis is Y, or Z when `x_axis` is `"y"`. **A named custom construction axis that is geometrically the Y axis will collide with the fallback**, since only principal names are known at build time.

Errors: `invalid_input` (`x_count must be >= 1`, `y_count must be >= 1`, `x_distance required when x_count > 1`, `y_distance required when y_axis given and y_count > 1`), `target_not_found`, `x_axis_not_found`, `y_axis_not_found`.

Returns: `ok`, `feature_name`, `x_count`, `y_count`.

**Count bodies after patterning.** Positions and volumes can be right while the count is wrong.

## `pattern_circular(feature_or_body, axis="z", count=6, total_angle="360 deg", name=None)`

`count` must be **>= 2** (stricter than the rectangular pattern).

Spacing depends on the angle: a full 360 spaces at `total/count` (no duplicate at the seam), a partial angle spaces at `total/(count-1)` so the last instance lands on the angle.

Errors: `invalid_input` (`count must be >= 2`, `total_angle required`), `target_not_found`, `axis_not_found`.

Returns: `ok`, `feature_name`, `count`, `total_angle`.

## `mirror_feature(feature_or_body, plane, name=None)`

`plane` is a principal plane or a root construction plane name. **No build-time validation**, so a bad plane surfaces as a runtime `plane_not_found`.

Feature names win over body names on a tie.

Errors: `target_not_found`, `plane_not_found`.

Returns: `ok`, `feature_name`, `mirrored_kind` (`"feature"` or `"body"`), `source`, `plane`.

## `combine(target_body, tool_bodies, operation="join", keep_tools=False, name=None)`

`operation` is `join`, `cut`, or `intersect`. **`new_body` and `new_component` are not valid here**, unlike `extrude`.

Errors: `invalid_input` (`operation must be one of ['cut', 'intersect', 'join']`, `tool_bodies must be non-empty`), `target_body_not_found`, `tool_body_not_found` (names the offending body).

Returns: `ok`, `feature_name`, `operation`, `keep_tools`.

**Body count is the cheapest correctness check after a join.** Two bodies that should have merged into one and did not is otherwise invisible.

## `move_body(body, translation_mm=None, rotation_axis=None, rotation_angle_deg=None, rotation_origin_mm=None, name=None)`

Needs at least one of `translation_mm` or `rotation_axis`; `rotation_axis` requires `rotation_angle_deg`. `rotation_origin_mm` defaults to the world origin and is ignored without a rotation.

Creates a real `MoveFeature` in the timeline, so it is parametric, not a free transform.

**Translation is applied before rotation** in one composed matrix. If exact placement matters, issue translation and rotation as two separate calls rather than reasoning about the composition.

Errors: `invalid_input`, `body_not_found`.

Returns: `ok`, `feature_name`, `body`.

## `rebuild_feature(feature_name, component_name=None)`

Repairs a stale-reference extrude (see `gotchas.md` G10) by capturing its inputs, deleting it, and rebuilding from the current sketch. Walks the whole tree; `component_name` disambiguates, and a hint that matches nothing silently falls back to a global search.

**Only `ExtrudeFeature` is supported.** Anything else returns `not_supported_for_rebuild` without touching the model, and includes a `recommendation`: suppress fillets and chamfers (G11), delete and re-create everything else.

Also unsupported, all caught *before* the delete so the original survives: two-sided extrudes, non-distance extents, start definitions other than profile-plane or offset, an unreadable profile, an unknown or ambiguous sketch name, and a sketch with zero profiles.

**The destructive window.** If the delete succeeds and recreation then fails, the feature is gone. That response carries an uppercase `WARNING` key and the fix is Fusion's undo. Preflight closes every known case, but treat the presence of `WARNING` as "the model needs manual attention".

Profile matching is by closest area, greedily and without replacement.

Errors: `feature_not_found`, `not_supported_for_rebuild`, `unsupported_profile_shape`, `unsupported_extent_type`, `unsupported_start_type`, `two_sided_extrude_not_supported`, `sketch_name_unknown`, `sketch_name_ambiguous`, `sketch_not_found`, `sketch_has_no_profiles`, `delete_failed`.

Returns: `ok`, `feature_name`, `feature_class`, `component`, `old_health`, `old_message`, `new_health`, `captured`.

**Compare `old_health` against `new_health`** to confirm the rebuild actually fixed anything. `-1` means the health read failed.

## `rib(...)`: unavailable

Always returns `rib_not_scriptable` and never contacts Fusion. `RibFeatures` is a read-only collection in the current API, with no `createInput` and no `add`, so ribs cannot be created by script at any argument combination.

**Model a rib as a thin extrude instead**: sketch the cross-section as a closed profile and extrude with `operation="join"`.

---

# Group 6: Assembly and joints

Shared: components and joints are addressed by **name**, not by handle, except `create_joint`, which consumes two entity handles. Name lookup matches an occurrence name or a component name, first match wins.

Joint lookup is flat over the root component. **Joints owned by sub-components are not found.**

## `bodies_to_components(mapping)`

`mapping` is `{body_name: component_name}`. World positions are preserved.

**The body keeps its name.** Fusion renames a converted body to `Body1`; this restores your name afterwards, because every other tool here addresses bodies by name. Without that, converting several bodies would leave several bodies all called `Body1`.

**Not atomic.** A `body_not_found` or `create_component_failed` partway through aborts and leaves earlier conversions in place.

Errors: `invalid_input`, `body_not_found`, `create_component_failed`.

Returns: `ok`, `converted` (`[{from_body, to_component}]`), `total_components` (all root occurrences, not just new ones).

## `move_component(name, translation_mm=None, rotation_axis=None, rotation_angle_deg=None, rotation_origin_mm=None)`

Same argument rules as `move_body`. Translation is relative to the occurrence's current transform.

**Check `moved` in the response.** A joint solver can override or partially reject a move without raising, so success does not mean motion. Compare `before_translation_mm` against `after_translation_mm`.

`moved` is a translation-only diff, so **a pure rotation reports `moved: false`** even when it worked.

**Side effect:** clears `isGroundToParent` on the target occurrence and does not restore it. Occurrences created by `bodies_to_components` default to ground-to-parent, and leaving it set makes the move silently revert. Note this is a different flag from `isGrounded`, which `ground_component` sets.

Errors: `invalid_input`, `occurrence_not_found`.

Returns: `ok`, `component`, `translation_mm`, `rotation_axis`, `rotation_angle_deg`, `before_translation_mm`, `after_translation_mm`, `moved`.

## `ground_component(name)` / `unground_component(name)`

Sets `isGrounded`, which is **not** the `isGroundToParent` flag that `move_component` clears.

Errors: `invalid_input` (`name required`), `occurrence_not_found`.

Returns: `ok`, `component`, `isGrounded` (read back).

## `create_rigid_group(component_names, name=None)`

Two or more names. `includeChildren` is hardcoded on.

Errors: `invalid_input` (`rigid group requires at least 2 component names`), `occurrence_not_found`, `rigid_group_add_failed` (carries `detail` when Fusion raised, typically over-constrained by an existing joint).

Returns: `ok`, `rigid_group_name`, `components`.

## `create_contact_set(body_names)`

Two or more bodies, for physics and motion.

**Bodies inside components resolve to assembly-context proxies**, which is what the API requires. This is handled internally, but it is why the name restoration in `bodies_to_components` matters: the proxy inherits the body name.

Errors: `invalid_input`, `body_not_found`, `contact_set_add_failed`.

Returns: `ok`, `contact_set_name`, `bodies`.

## `interference_check(entity_names)`

Two or more names, resolved **body first, then occurrence**, so a body wins a name tie. Mixed lists are fine.

Coincident faces are excluded, so touching parts are not reported as interfering.

**Zero interference is a success**, not an error: `pair_count: 0`.

Errors: `invalid_input`, `entity_not_found`.

Returns: `ok`, `checked` (`[{name, kind}]`), `interference_pairs` (`[{entity_one, entity_two, interference_volume_cm3, interference_volume_mm3}]`), `pair_count`.

## `create_joint(geometry_one, geometry_two, motion_type="rigid", axis="z", offset_mm=None, angle_deg=None, name=None)`

Both geometries are **entity handles** of kind `face`, `edge`, `vertex`, or `point`. Get them from `list_body_entities` or the sketch tools.

| Handle kind | Joint origin |
|---|---|
| `face` | face center; planar, falling back to cylindrical and conical |
| `edge` | edge midpoint |
| `vertex` | the vertex |
| `point` | a sketch point |

| `motion_type` | DOF | Uses `axis`? |
|---|---|---|
| `rigid` | 0 | no |
| `revolute` | 1 rotation | yes |
| `slider` | 1 translation | yes |
| `cylindrical` | rotation + translation | yes |
| `ball` | 3 rotation | **no** |

**`axis` is relative to the first geometry's local frame, not world.** For the common "pin coming out of a face" hinge, use `z`, which is the face normal.

**Ball joints ignore `axis` entirely.** Fusion accepts only pitch=Z with yaw=X, so it is hardcoded. The `axis` you pass is still validated and echoed back but has no effect; do not infer the ball joint's orientation from it.

`offset_mm` and `angle_deg` are expression strings despite the names, so include units (`"9 mm"`, `"90 deg"`).

Errors: `invalid_input` (bad `motion_type`, bad `axis`, unsupported handle kind, malformed handle), `handle_invalid`, `joint_geometry_failed` (carries `kind` and `detail`), `joints_add_failed` (carries `detail`, `motion_type`, `axis`; usually over-constrained or an incompatible geometry pair).

Returns: `ok`, `joint_name`, `joint_token`, `motion_type`, `axis`, `offset_mm`, `angle_deg`.

**Carry `joint_name` forward**, not `joint_token`: the limit and drive tools address joints by name. `joint_token` is a bare token, not a full handle.

## `set_joint_limits(joint_name, min_value=None, max_value=None, rest_value=None)`

At least one of the three. All are expression strings with units.

| Motion | Limits used |
|---|---|
| Revolute | rotation |
| Slider | slide |
| Cylindrical | **rotation**; its slide limits are unreachable here |
| Rigid, Ball | none, returns `joint_has_no_limits` |

Omitted values leave that limit untouched. **This tool never disables a limit.**

**Not atomic.** A bad expression returns immediately, so limits applied earlier in min, max, rest order stay applied.

Errors: `invalid_input`, `joint_not_found`, `joint_has_no_motion`, `joint_has_no_limits` (carries `motion_class`), `expression_invalid` (carries `expression`, `expected_units`, `detail`).

Returns: `ok`, `joint_name`, `limits_kind` (`"rotation"` or `"slide"`), `applied` (a dict of `min_enabled` / `min_value_internal` and the max and rest equivalents).

**`applied` is a readback in Fusion internal units: radians for rotation, centimeters for slide.** Setting `"45 deg"` reads back roughly `0.785`. Convert before comparing.

## `drive_joint(joint_name, value)`

`value` is an expression string with units.

Drives the first available attribute in order: `rotationValue`, `slideValue`, `rollValue`, `pitchValue`, `yawValue`, then stops. Consequences: a cylindrical joint always takes rotation, and **a ball joint can only ever be driven on roll**; pitch and yaw are unreachable.

**Check `applied`.** Fusion silently ignores a drive beyond an enabled limit: no exception, the value simply stays put. `ok: true` does not mean the joint moved. When `applied` is `false`, compare `value_internal` (where it actually sits, usually clamped) against `requested_internal`.

Both are in internal units, radians or centimeters, not your input units.

Errors: `invalid_input` (`value expression required`), `joint_not_found`, `joint_has_no_motion`, `no_drivable_motion_attribute` (carries `motion_class`).

Returns: `ok`, `joint_name`, `drove` (the attribute name), `value` (your expression), `value_internal`, `requested_internal`, `applied`.

---

# Group 7: Handles, measurement, and rays

`list_body_entities` is the bridge from names to handles. Everything else here consumes them.

`fillet_edges`, `chamfer_edges`, and `project_to_sketch` create their features on the **root component** regardless of which component owns the edges.

## `list_body_entities(body, kinds=None, face_normal_filter=None, edge_parallel_to=None, min_edge_length_mm=None)`

`kinds` defaults to all three of `face`, `edge`, `vertex`. **Walks sub-components** to find the body.

| Entry | Keys |
|---|---|
| Face | `index`, `handle`, `pointOnFace_mm` |
| Edge | `index`, `handle`, `length_mm` |
| Vertex | `index`, `handle`, `position_mm` |

**The filters compute more than they return.** `face_normal_filter` evaluates each face normal and then discards it; faces carry no normal, no area, and no centroid, only an arbitrary point on the surface. Edges carry no endpoints and no direction. If you need normals, filter *for* them and infer.

`face_normal_filter` matches componentwise within `1e-3` against a unit normal sampled at one arbitrary point, so pass a unit vector, and note it is direction-sensitive: `[0,0,1]` and `[0,0,-1]` differ.

`edge_parallel_to` tests the two endpoints within `1e-6` cm. **`length_mm` is chord distance, not arc length**, so a circular edge reports 0 and arcs are under-measured.

`index` is the raw index into the body's collection and survives filtering, so filtered results have gaps. The `*_count` fields are post-filter lengths, and an empty list is ambiguous between "not requested" and "everything filtered out".

Errors: `invalid_input` (`unknown entity kind`, `face_normal_filter must be [nx, ny, nz]`, `edge_parallel_to must be x, y, or z`, `min_edge_length_mm must be >= 0`), `body_not_found`.

Returns: `ok`, `body`, `face_count`, `edge_count`, `vertex_count`, `faces`, `edges`, `vertices`.

## `measure(entity_a, entity_b, kind="distance")`

| `kind` | Returns |
|---|---|
| `"distance"` | `value_cm`, `value_mm`, `point_a_cm`, `point_b_cm` |
| `"min_distance"` | `value_cm`, `value_mm` |
| `"angle"` | `value_radians`, `value_degrees` |

`distance` and `min_distance` call the same Fusion API; they differ only in whether the closest-approach points come back.

**The point arrays are in centimeters**, the only mm-less coordinates in the tool surface.

Entities inside occurrences are unwrapped to their native objects before measuring, so results are in **component space, not assembly space**.

Errors: `invalid_input` (bad `kind`, malformed handle), `handle_invalid`.

## `fillet_edges(edge_handles, radius, is_tangent_chain=True, name=None)`

Handle-driven fillet, the UI-selection equivalent. `edges_filleted` counts the handles you passed, **not** the edges Fusion actually touched after tangent chaining.

Errors: `invalid_input` (`edge_handles must be non-empty`, `radius expression required`), `handle_invalid`.

Returns: `ok`, `feature_name`, `edges_filleted`, `radius`.

## `chamfer_edges(edge_handles, distance, kind="equal", distance2=None, angle=None, name=None)`

Same `kind` rules as `chamfer_edges_by_geometry`. **No tangent-chain option**, unlike `fillet_edges`.

Errors: `invalid_input` (`edge_handles must be non-empty`, bad `kind`, `kind=two_dist requires distance2`, `kind=dist_angle requires angle`), `handle_invalid`.

Returns: `ok`, `feature_name`, `edges_chamfered`, `kind`.

## `project_to_sketch(sketch, entity_handles)`

Projects entities onto a named sketch, for cut-extrudes that reference body geometry.

**The sketch is looked up in the root component only**, so sketches inside sub-components are unreachable.

`entities_projected` counts handles submitted, not those that produced geometry. `curves_added` is the real output count, normally larger since one face yields several curves. **No handles are returned for the new curves.**

Errors: `invalid_input` (`entity_handles must be non-empty`), `handle_invalid`, `sketch_not_found`.

Returns: `ok`, `sketch`, `entities_projected`, `curves_added`.

## `find_mesh_using_ray(origin_mm, direction, component_name=None)`

Casts a ray and returns intersected mesh bodies **by name only**: no handles, no hit points, no distances. `direction` is unitless and is not normalized. Scoped to the root component unless `component_name` is given; that lookup walks sub-components.

Errors: `invalid_input` (`origin_mm must be [x, y, z] in mm`, `direction must be [dx, dy, dz]`), `component_not_found`.

Returns: `ok`, `meshes_found`, `names`.

## `ray_collision_with_mesh(mesh_handle, origin_mm, direction)`

Casts against one mesh and returns every intersection point in mm world coordinates. No ordering guarantee, no normals, no distances.

Errors: `invalid_input`, `handle_invalid`.

Returns: `ok`, `collisions`, `points_mm`.

---

# Group 8: Verify, visualize, import and export, knowledge

## `bounding_box(body_name=None)` / `volume(...)` / `mass(...)` / `center_of_mass(...)`

All four take an optional body name (exact, case-sensitive) and default to every body in the design. All walk sub-components, prefixing nested paths with the parent component name.

| Tool | Returns per body |
|---|---|
| `bounding_box` | `bbox_mm` (`min`, `max`), `extent_mm` |
| `volume` | `volume_cm3`, `volume_mm3` |
| `mass` | `mass_kg`, `volume_cm3`, `material`, `density_kg_m3` |
| `center_of_mass` | `center_of_mass_mm` |

Every entry carries `path` and `name`. A per-body failure becomes `{path, error}` rather than aborting the sweep.

Errors: `no_active_design`, `body_not_found` (only when a filter matched nothing), `<tool>_parse_failed`.

**These are the ground truth for verification.** Bounding box catches orientation errors that screenshots hide; volume catches missed cuts and wrong participant bodies. Pair them after every body-adding feature.

## `audit_feature_health(component_name=None, include_healthy=False)`

Sweeps the feature tree and reports features whose health is not clean.

| `healthState` | Label |
|---|---|
| 0 | `healthy` |
| 1 | `warning` (typically a stale profile reference using cached geometry) |
| 2, 3 | `failed` |

**States 2 and 3 both label as `failed`**, so read the integer to tell them apart.

`summary` counts every feature regardless of `include_healthy`. A feature whose health read failed increments `total` only, so the buckets can sum to less than the total.

Only component features are audited: not sketches, construction geometry, or joints.

Returns: `ok`, `summary` (`total`, `healthy`, `warning`, `failed`), `features`.

**Run this after any tool that edits sketch geometry, parameters, or features**, especially `edit_sketch_dimension`. The API can report healthy geometry while Fusion's UI shows stale cached display.

## `screenshot(direction="iso-top-right", width=None, height=None, transparent=True, anti_aliasing=True)`

Eleven directions: `current`, `front`, `back`, `top`, `bottom`, `left`, `right`, and the four `iso-*` corners. Fusion fits the view internally for named directions.

Returns the PNG as base64 in `envelope.image`.

**Keep `width` at or below roughly 400 px.** Larger images blow the tool-result token limit and the call fails after Fusion has already done the work.

**Screenshots are the weakest verification you have.** They deceive on orientation and sometimes render blank. Use `bounding_box` and `volume` to verify geometry; use screenshots to show a human.

Errors: `invalid_direction`.

## `set_view(direction="iso-top-right", fit=True)`

Orients the camera without capturing. `"current"` orients nothing but still honors `fit`.

Errors: `invalid_direction`, `no_active_viewport`.

## `screenshot_compare_with_marker(before_marker_position, direction="iso-top-right", ...)`

Rolls the timeline back, captures, rolls forward, captures again, from the same camera. An honest visual diff of one change.

`before_marker_position` must be within `[0, timeline.count]`.

**`restore_marker_failed` is the one to watch**: the roll forward failed and the design is left rolled back with features suppressed from view. The user must drag the marker back manually.

Returns: `before_image`, `after_image`, `before_marker`, `after_marker`, `direction`.

## `export(format, path, body=None, refinement="medium", units="mm")`

Formats: `stl`, `3mf`, `step`, `iges`, `obj`, `f3d`, `sat`, `smt`.

`body` is honored only by `stl`, `3mf`, and `obj`. **The solid formats always export the whole design** and ignore it silently.

`refinement` (`low`, `medium`, `high`) applies to `stl` and `obj`. `units` applies to `stl` only.

Paths must be **absolute**. Relative paths, `..` segments, and Windows reserved device names are rejected. Directories are created automatically and overwrite is silent.

Errors: `invalid_path` (`path must be absolute`, `path contains '..' parent-dir reference`, `path uses Windows reserved name`), `invalid_input` (bad format, refinement, or units), `body_not_found`.

Returns: `ok`, `path`, `bytes_written`, and `format` for the mesh formats.

**Check `bytes_written`.** A silently failed export returns `ok: true` with `bytes_written: 0`.

## `import_geometry(format, path)`

Formats: `step`, `iges`, `sat`, `smt`, `f3d`. Note `stl`, `3mf`, and `obj` are exportable but **not** importable.

Counts are deltas measured on the root component only, so bodies landing in sub-components are not counted.

Errors: `invalid_path`, `invalid_input`, `file_not_found` (checked inside Fusion, not locally).

Returns: `ok`, `format`, `path`, `bodies_added`, `occurrences_added`.

## `find_api(query, kind=None, namespace=None, limit=5)` / `find_pattern(query, limit=5)` / `find_gotcha(query, limit=5)` / `find_tool(query, limit=5)`

Local search. **These are the only tools that work with Fusion closed**; they never touch the adapter.

`find_tool` searches this file, `find_pattern` searches `patterns.md`, `find_gotcha` searches `gotchas.md`. All three search markdown shipped with the package and always work.

`find_tool` exists so a client can look up a signature or an error code on demand rather than carrying this whole reference in context, which is the point of the typed tool surface.

`find_api` searches a corpus of Autodesk's API help that is **not** redistributed. Until you build it, it returns `corpus_not_built`:

```
fusion-cad-mcp corpus build --i-accept-autodesk-terms
```

That writes to `~/.fusion-cad/corpus/`, which is where the server looks first. It needs the optional extras: `pip install "fusion-cad-mcp[corpus]"`. Set `FUSION_CAD_CORPUS_DIR` to keep it elsewhere.

Search is substring bag-of-words with hand-tuned weights, not embeddings and not BM25. There is no stemming and no word-boundary matching, so `"arc"` matches inside `"search"`. Zero hits is a success with an empty list, not an error.

**Call `find_api` before writing an `execute` script against an unfamiliar method.** One search is cheaper than a failed round trip, and it reports Preview status, which is a release gate.

Indexes are cached for the process lifetime, so edits to the markdown need a server restart.

Errors: `corpus_not_built`, `patterns_not_found`, `gotchas_not_found`, `empty_query`.

---

# `execute(script)`

The escape hatch, and the only tool with no validation of any kind.

```python
import adsk.core, adsk.fusion

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    # work here
    print("done")
```

Rules that are not optional:

1. The entry point must be exactly `def run(_ctx):`. No other name works.
2. **Do not wrap the body in try/except.** Exceptions come back as the tool error with a full traceback; catching them destroys the traceback and turns a 30-second fix into a long debug.
3. `print()` is the return channel. Stdout becomes the response `message`.
4. **An exception rolls back the entire script**, including geometry created before the failure. There are no partial commits.

Internal units are **centimeters**. `Point3D.create` takes cm and `parameter.value` returns cm. Use `ValueInput.createByString("30 mm")` for anything human-readable and let Fusion convert; multiply by 10 only when printing.

Reach for `execute` when no typed tool covers the operation. Reach for `find_api` first, then `find_pattern`, before writing it from scratch.
