# Changelog

## 0.2.2

### Fixed: a clean install pulled `mcp` 2.x and could not start

Reported in [#2](https://github.com/Mfrostbutter/fusion-cad-mcp/issues/2). The
dependency was declared as `mcp>=1.2.0` with no ceiling. `mcp` 2.0.0 removed
`mcp.server.fastmcp`, which `server.py` imports, so pip resolved to a release
the server cannot run on: the install reported success and every invocation of
the entry point died with `ModuleNotFoundError`. To an MCP client that looks
like a server that will not start, with nothing pointing at the cause.

The requirement is now `mcp>=1.2.0,<2`. Supporting 2.x is a port from
`fastmcp` to `mcpserver` and is not in this release.

### Fixed: `corpus build --resume` scraped nothing and reported success

Reported in [#3](https://github.com/Mfrostbutter/fusion-cad-mcp/issues/3). The
crawl frontier only ever existed in memory, discovered by parsing links out of
pages as they were fetched. `--resume` skipped pages already on disk, so their
links were never extracted, the queue was never repopulated, and an empty queue
read as a finished crawl. A `--limit` smoke test followed by `--resume`, which
is what the `--limit` help text invites, produced a corpus of five pages that
announced `Corpus ready` and exited 0. `find_api` then returned almost nothing,
with no signal pointing back at the build.

Three changes, in the order they take effect:

- **The frontier is persisted.** `frontier.json` holds the pending queue and
  the visited set, written every 250 pages and again on the way out, including
  on Ctrl-C. `--resume` restores it and continues. An interrupted page is
  requeued rather than left marked visited with nothing on disk.
- **A missing frontier is rebuilt from the pages already scraped.** Raw HTML is
  not kept, so the links are re-derived from the converted markdown. This is
  what lets a corpus built by an earlier version resume without re-fetching
  what it already has.
- **A suspicious finish is no longer a success.** A resume that scrapes zero
  pages and recovers no frontier now warns and exits non-zero instead of
  printing `Corpus ready` over a near-empty corpus.

Verified against the live site: a `--limit 5` build followed by `--resume`
restores all 18,223 pending URLs and continues the crawl, and a resume with
`frontier.json` removed rebuilds 18,063 URLs from the pages on disk.

## 0.2.1

### Fixed: `corpus build` was missing from the release entirely

Reported in [#1](https://github.com/Mfrostbutter/fusion-cad-mcp/issues/1). A
`.gitignore` rule meant to keep the built Autodesk corpus out of the repo,
`corpus/`, matched any directory of that name at any depth. It swallowed
`src/fusion_cad_mcp/corpus/`, the builder package itself, so 0.2.0 shipped a
CLI entry point, a README section, and an optional dependency group for code
that was never published. `fusion-cad-mcp corpus build` died on
`ModuleNotFoundError`, and `find_api` had no way to get a corpus.

The ignore rules are now anchored to build output only, and the package is
committed. Three bugs it was hiding are fixed with it:

- `build()` passed `corpus_path=` to a `backfill_metadata.main()` that took no
  arguments, so a completed scrape crashed on the metadata pass.
- `backfill_metadata` read and wrote `corpus.jsonl` beside its own module, not
  the directory the scraper was told to use. Under a normal install that is
  inside site-packages. Both paths now come from the scraper's configured
  output directory.
- The scraper parsed with `lxml`, which was not in the `[corpus]` extra. bs4
  only resolves the parser at first parse, so this surfaced mid-crawl rather
  than at import. `lxml` is now declared, and a missing one falls back to
  `html.parser` instead of failing.

Verified end to end: build, metadata backfill, and a `find_api` query against
the result.

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
