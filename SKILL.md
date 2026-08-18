---
name: fusion-cad
description: "Use this skill whenever the user wants to do CAD work through Autodesk Fusion, either via the fusion-cad-mcp server (75 named tools: create_sketch, add_rectangle, extrude, add_hole, fillet_edges, create_joint, export, and so on) or via Autodesk's own Fusion MCP (fusion_mcp_execute, fusion_mcp_read, fusion_mcp_update, fusion_mcp_electronics_read). Covers parametric constrained sketches, extrudes, holes, fillets, chamfers, shells, multi-body modeling, assemblies and components, as-built joints, motion (hinges, sliders), print-in-place mechanisms and print orientation, exports to STL/3MF/STEP, undo/redo, screenshots, API documentation lookup, and explicit camera control. Trigger on any mention of Fusion 360, the Fusion MCP, .f3d/.f3z/.step files, parametric CAD design, building or editing 3D models programmatically, sketches, extrudes, fillets, counterbore holes, components, joints, hinges, sliders, assemblies, print-in-place parts, print orientation, or when the user asks to model a bracket, tray, mount, panel, organizer, rack mount, or any functional 3D-printed product. Use even if the user does not name the MCP explicitly: if they ask Claude to design something in Fusion or build a part, this skill applies."
---

# Fusion CAD

Drive Autodesk Fusion safely and efficiently through an MCP server.

> Built from production Fusion sessions plus a dedicated live test battery against Fusion 2704.1.23. Free to use and modify.

## Which server are you talking to?

This matters before anything else, because the tool surface is completely different.

**`fusion-cad-mcp` (this project).** 75 named, typed tools: `create_sketch`, `extrude`, `add_hole`, `create_joint`. Each one validates arguments, returns a structured envelope, and encodes the gotchas so you do not have to. **Prefer this whenever it is available.**

**Autodesk's own Fusion MCP.** Four fat tools that take raw Python or query objects:

- `fusion_mcp_execute` runs a Python script, or does file operations
- `fusion_mcp_read` screenshots, API doc lookup, document and project queries
- `fusion_mcp_update` undo and redo
- `fusion_mcp_electronics_read` read-only Electronics data (Preview API; do not depend on it in distributed work)

`fusion-cad-mcp` sits **in front of** Autodesk's server rather than replacing it: it generates Python and pushes it through `fusion_mcp_execute`. So both are the same Fusion underneath, and every gotcha in `gotchas.md` applies to both.

If only the four-tool server is connected, skip to "Writing raw scripts" at the bottom and lean on `patterns.md`.

## Reference files

Load on demand. This file is the operating manual; those are the depth.

| File | What it is | When to load |
|---|---|---|
| `tools.md` | All 75 tools: signatures, exact enums, return keys, error codes | Before calling a tool whose arguments you are not sure of |
| `gotchas.md` | Failure-mode catalog, each with symptom and fix | When something behaves unexpectedly, or before a risky operation |
| `patterns.md` | Reusable Python for `execute` | When no typed tool covers the operation |

The server can also search these for you without loading them: `find_tool`, `find_gotcha`, `find_pattern`, and `find_api` for Autodesk's API help. **These work with Fusion closed.**

## Six rules that prevent most failures

1. **Parametric first.** Every dimension that might change goes in `add_parameters` and gets referenced by name. Hardcoded numbers in sketches are forbidden. Re-running should be safe.
2. **One feature per call.** Faster debugging, cleaner timeline, scoped failures.
3. **Name everything.** Sketches, features, bodies, planes. Name-addressing is how you reach things later, and an unnamed timeline is unreadable when something breaks.
4. **Assert profiles after every sketch.** `assert_profiles(sketch, expected)`. A self-intersecting polygon returns 2 profiles rather than raising, and that is the only signal you get.
5. **Verify with numbers, not pictures.** `bounding_box` and `volume` after every body-adding feature. Screenshots deceive about orientation and sometimes render blank; volume tracks intended geometry to under 1 mm3 and catches missed cuts that look fine on screen.
6. **Count entities across anything that replicates.** Patterns, mirrors, joins. Position and volume can all be correct while the count is wrong. This is not hypothetical: an unset pattern direction two silently tripled body counts with every other check passing.

## The two things every tool shares

**The envelope.** Every tool returns `{ok, message, result, state, image, error, traceback}`. One parsing contract.

**`ok: true` does not mean success.** `doc_state` returns `ok: true` with `{"active_design": false}`. `drive_joint` returns `ok: true` when Fusion silently ignored a beyond-limit drive; check `applied`. `move_component` returns `ok: true` when a joint solver overrode the move; check `moved`. `export` returns `ok: true` with `bytes_written: 0`. **Read `result`, not just `ok`.**

**Handles.** Bodies, sketches, components, and joints are addressed by **name**. Faces, edges, and vertices have no stable name and are addressed by an opaque handle, `kind:path:token`. `list_body_entities` converts a body name into handles for its faces, edges, and vertices; that is the only route to sub-entity geometry. Handles go stale after edits and return `handle_invalid`, so never cache them across a feature change.

## Standard build

1. **`doc_state`.** Confirm a design is open and check units before touching anything.
2. **`add_parameters`.** Idempotent, so existing names are skipped. Do this before geometry to catch typos early.
3. **`create_sketch` then geometry.** XY is the safe default plane. XZ maps sketch Y to *negative* world Z; YZ inverts sketch X. On any non-XY plane, verify a point's world position before committing coordinates.
4. **Constrain and dimension.** Use parameter-name expressions in `add_dimension`; they propagate when the parameter changes. Anchor rectangles to a specific corner rather than a diagonal midpoint.
5. **`assert_profiles`.** Non-negotiable.
6. **Feature.** `extrude`, `revolve`, `add_hole`, and so on, one per call, each named.
7. **`bounding_box` and `volume`.** Compare against intent.
8. **`audit_feature_health`** after anything that edits sketches, parameters, or features. It catches downstream breakage the API otherwise reports as healthy.
9. **Export** with an absolute path, and check `bytes_written`.

## Traps that cost the most time

Full catalog in `gotchas.md`. These bite first.

**Sub-components are mostly invisible.** Most sketch tools resolve sketches in the **root component only**, and there is no parameter to reach a sketch inside a component. `extrude`, `revolve`, and `project_to_sketch` all behave this way. Features are the same for `mirror_feature` and both pattern tools.

**Internal units are centimeters.** Tools convert for you at the boundary, so you pass and receive mm. Raw scripts do not: `Point3D.create` takes cm, and `parameter.value` returns cm. Use `ValueInput.createByString("30 mm")` and let Fusion convert.

**Edge length is chord distance, not arc length.** The geometric fillet and chamfer filters measure straight-line distance between endpoints, so a closed circular edge measures 0 and is never selected, and arcs are under-measured.

**`add_hole` is world-Z locked.** It drills a `+Z`-facing face, prefers the one containing your XY, and **ignores the Z you pass**. Rotate the body and there is no `+Z` face at all. Check `position_on_face` in the response.

**Undo is atomic on the whole prior call.** A script that added parameters *and* geometry loses both, silently. Prefer targeted deletion.

**An exception rolls back the entire script.** There are no partial commits inside one `execute`.

**Joint limits and drives report in internal units** (radians, centimeters), not what you passed in.

**`rib` is not scriptable.** `RibFeatures` is read-only in the current API. The tool returns `rib_not_scriptable` rather than crashing. Model a rib as a thin extrude with `operation="join"`.

**Screenshots are the weakest check you have.** Keep width at or below roughly 400 px or the base64 blows the tool-result token limit. Use them to show a human, not to verify geometry.

**Preview API badges are release gates.** If `find_api` reports a page as Preview, do not build distributed work on it without the user explicitly accepting the risk.

## Writing raw scripts

`execute` is the escape hatch, and it is the only tool with no validation. Reach for it when no typed tool covers the operation, after checking `find_api` and `find_pattern`.

```python
import adsk.core, adsk.fusion

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    # work here
    print(f"bodies={root.bRepBodies.count}")
```

1. The entry point must be exactly `def run(_ctx):`. No other name works. (Autodesk's `fusion_mcp_execute` uses `def run(_context: str):`.)
2. **Never wrap the body in try/except.** Exceptions return as the tool error with a full traceback; catching them destroys it.
3. `print()` is the return channel; stdout becomes `message`.
4. Print the bounding box after any extrude.

Look the API up before writing against an unfamiliar method. `find_api` costs one call; a failed round trip plus debugging costs far more. Always pass a category when using Autodesk's `apiDocumentation` query, since omitting it returns success with empty data.

## Setup

`fusion-cad-mcp` is at **https://github.com/Mfrostbutter/fusion-cad-mcp**:

```bash
pip install "fusion-cad-mcp @ git+https://github.com/Mfrostbutter/fusion-cad-mcp.git"
```

Then point your MCP client at the `fusion-cad-mcp` command. `CONNECT.md` in that repo has per-client config and troubleshooting.

The server talks to Autodesk's MCP at `127.0.0.1:27182`, which is enabled in **Preferences > General > API > Fusion MCP Server**. Fusion must be running with a design open.

`find_api` needs a local corpus of Autodesk's API help, which is not redistributed. Build it once:

```
pip install "fusion-cad-mcp[corpus] @ git+https://github.com/Mfrostbutter/fusion-cad-mcp.git"
fusion-cad-mcp corpus build --i-accept-autodesk-terms
```

Everything else works without it.

If Fusion is restarted, the server re-handshakes automatically on the next call. If the *client* session goes stale instead, that shows up as repeated 4xx and needs a client-side reconnect, which only the user can do.
