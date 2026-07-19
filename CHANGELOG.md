# Changelog

## 0.2.0

First release that works for someone other than its author.

### Fixed: 17 bugs, all verified against live Fusion 2704.1.23

Unit tests can prove generated Python is valid. They cannot prove Fusion accepts
it. A full pass against a live document found 17 bugs that the test suite was
green on, in three classes.

**Generated code was invalid Python (4).** `json.dumps(None)` emits `null`,
which is not a Python name, so the script died inside Fusion with a `NameError`.
`ast.parse` cannot catch this, since `null` is a legal identifier. Hit
`pattern_rectangular` on its default path, `fillet_edges_by_geometry`, and
`set_joint_limits`. Values are now embedded with `repr()`, and a test walks the
AST of every generator's output for JSON literals used as names.

**Calls that could never have worked (9).** Each crashed on first real use
because the Fusion API differs from what the code assumed:

- `bodies_to_components` called `Features.createComponentFromBodyFeatures`,
  which does not exist. Now uses `BRepBody.createComponent()`, and restores the
  body name that Fusion silently resets to `Body1`.
- `set_joint_limits` looked for limits on the `JointMotion`. They live on
  `rotationLimits` / `slideLimits`, and `ValueInput.realValue` raises on string
  input, so expressions are evaluated through `unitsManager`.
- `drive_joint` hit the same `realValue` crash.
- `create_joint` ball motion accepts only pitch=Z, yaw=X out of nine
  principal-axis combinations.
- `create_rigid_group` and `create_contact_set` have no `createInput`, and
  contact sets live on the Design and need assembly-context body proxies.
- `shell` used a `ThicknessDirections` enum that does not exist, and closed
  shells need the body in the input collection.
- `chamfer_edges` and `chamfer_edges_by_geometry` needed the current
  `createInput2()` / `chamferEdgeSets` API.
- `rib` cannot work at all: `RibFeatures` is read-only in this Fusion version.
  It now returns `rib_not_scriptable` with a workaround instead of crashing.

**Silent wrong results (4).** These are the dangerous ones: they returned
`ok: true` while doing the wrong thing, and every check except one passed.

- `pattern_rectangular` produced **three times** the requested geometry. Fusion
  does not treat an unset direction two as a single row. Positions and per-body
  volumes were correct; only the body count was wrong.
- `move_component` reported success without moving, twice over: the timeline
  roll reverted the transform, and `snapshots.add()` snapped ground-to-parent
  occurrences back.
- `drive_joint` reported success when Fusion silently ignored a drive past a
  joint limit. It now reports `applied`.
- `add_hole` always drilled the tallest `+Z` face, so a hole aimed at a lower
  step started in mid-air. It now prefers the face containing the target XY.

`rebuild_feature` also had its destructive window narrowed: a sketch with zero
profiles now fails preflight instead of after the delete, and a profile getter
that raises on a stale feature is caught rather than crashing mid-repair.

### Added

- **`tools.md`**, a full reference for all 75 tools: signatures, exact enums,
  return keys, error codes, and per-tool traps.
- **`find_tool`**, searching that reference, so a client can look up a signature
  on demand instead of carrying 56 KB in context.
- **14 gotcha entries** from the live testing, written as reusable Fusion API
  knowledge rather than release notes.
- **`fusion-cad-mcp corpus build`**, the subcommand `find_api`'s error message
  had been promising without it existing. Behind an explicit Autodesk terms
  gate; the corpus is still never redistributed.
- **A `[corpus]` extra** for the scraper's dependencies, likewise documented but
  previously absent.

### Changed

- Knowledge markdown now ships inside the wheel, so `find_tool`, `find_gotcha`
  and `find_pattern` work on a plain `pip install`. Previously they only worked
  from a repo checkout. A test fails if the packaged copies drift from source.
- The adapter re-handshakes when Fusion rejects a stale session. It had claimed
  to do this in its docstring and did not, so a Fusion restart meant restarting
  the MCP server.
- Knowledge search ranks by term rarity and query coverage, with log-damped
  occurrence counts. Searching `"pattern_rectangular direction two"` used to
  return the `shell` section first.
- Status moved from alpha to beta. 467 tests.

### Known limitations

- `rib` is permanently unavailable pending a Fusion API change.
- `add_hole` only drills `+Z`-facing faces, so it cannot place a hole on a
  rotated body.
- Most sketch tools resolve sketches in the root component only.
- Edge filters measure chord distance, not arc length, so circular edges
  measure zero.
- `find_api` needs a user-built corpus.

## 0.1.0

Initial scaffold: adapter, envelope, entity handles, and the first tool groups.
