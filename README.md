# fusion-cad-mcp

An MCP server that gives Autodesk Fusion a named, typed tool surface: `create_sketch`, `extrude`, `add_hole`, `create_joint`, `export`, and 70 more.

Fusion ships its own MCP server, but it exposes four broad tools that take raw Python. That works, and it means every call is an opportunity to get the Fusion API wrong. This sits in front of it and turns the common operations into validated tools with structured errors, so an agent can do CAD without carrying a large prose skill in context.

**Status: beta (0.2.x).** 75 tools, 467 tests, and a full pass of live verification against Fusion 2704.1.23 that found and fixed 17 bugs. Used in production for parametric part design.

## Requirements

- Autodesk Fusion, running, with a design open
- **Preferences > General > API > Fusion MCP Server** enabled
- Python 3.11+

## Install

```bash
pip install "fusion-cad-mcp @ git+https://github.com/Mfrostbutter/fusion-cad-mcp.git"
```

Then point your MCP client at it. For Claude Code or Claude Desktop:

```json
{
  "mcpServers": {
    "fusion": {
      "command": "fusion-cad-mcp"
    }
  }
}
```

See [CONNECT.md](CONNECT.md) for per-client details and troubleshooting.

## How it works

```
MCP client (Claude, Cursor, Cline, ...)
  -> fusion-cad-mcp            this package, stdio MCP server
    -> httpx
      -> 127.0.0.1:27182/mcp   Fusion's own MCP
        -> adsk.fusion / adsk.core
```

Each tool generates a Python script and runs it through Fusion's `execute`. It is a peer of Autodesk's bridge, not a replacement, so anything you can do in the Fusion API you can still do here via the `execute` escape hatch.

## The tools

75 registered, 74 usable. Full reference with signatures, enums, return keys, and error codes is in [`tools.md`](src/fusion_cad_mcp/knowledge/tools.md), or search it in place with the `find_tool` tool.

| Group | Tools |
|---|---|
| Document and state | `doc_state`, `list_open_docs`, `list_projects`, `search_docs`, `open_doc`, `save`, `save_as`, `close`, `undo`, `redo` |
| Parameters | `add_parameters`, `update_parameter`, `list_parameters` |
| Sketch | `create_sketch`, `add_line`, `add_rectangle`, `add_circle`, `add_arc`, `add_ellipse`, `add_spline`, `add_polygon`, `add_geometric_constraint`, `add_dimension`, `assert_profiles`, `probe_sketch_dimensions`, `edit_sketch_dimension` |
| Construction | `create_construction_plane`, `create_construction_axis`, `create_construction_point`, `delete_construction` |
| Features | `extrude`, `revolve`, `combine`, `shell`, `add_hole`, `fillet_edges_by_geometry`, `chamfer_edges_by_geometry`, `mirror_feature`, `pattern_rectangular`, `pattern_circular`, `move_body`, `rebuild_feature` |
| Assembly and joints | `bodies_to_components`, `move_component`, `ground_component`, `unground_component`, `create_rigid_group`, `create_contact_set`, `interference_check`, `create_joint`, `set_joint_limits`, `drive_joint` |
| Handles and measurement | `list_body_entities`, `measure`, `fillet_edges`, `chamfer_edges`, `project_to_sketch`, `find_mesh_using_ray`, `ray_collision_with_mesh` |
| Verify and visualize | `bounding_box`, `volume`, `mass`, `center_of_mass`, `audit_feature_health`, `screenshot`, `set_view`, `screenshot_compare_with_marker` |
| Import, export, knowledge | `export`, `import_geometry`, `find_tool`, `find_gotcha`, `find_pattern`, `find_api` |
| Escape hatch | `execute` |

`rib` is registered but always returns `rib_not_scriptable`: Fusion exposes `RibFeatures` as a read-only collection, so ribs cannot be created through the API at all. Model one as a thin join-extrude instead.

## Every tool returns the same envelope

```python
{
  "ok": bool,
  "message": str,          # stdout from the generated script
  "result": dict | None,   # the payload
  "image": dict | None,    # base64 PNG, for screenshots
  "error": str | None,     # error code when ok is False
  "traceback": str | None
}
```

**`ok: true` does not always mean the thing happened.** Fusion has several operations that decline silently, and the tools surface that rather than hiding it:

- `drive_joint` returns `applied: false` when a drive past a joint limit was ignored
- `move_component` returns `moved: false` when a joint solver overrode the move
- `export` returns `bytes_written: 0` when nothing was written
- `doc_state` returns `active_design: false` when no design is open

Read `result`, not just `ok`.

## The knowledge tools

Four tools answer questions without touching Fusion, so they work with it closed:

| Tool | Searches |
|---|---|
| `find_tool` | this server's tool reference |
| `find_gotcha` | a catalog of Fusion API failure modes |
| `find_pattern` | reusable Python recipes for `execute` |
| `find_api` | Autodesk's Fusion API help |

The first three ship with the package. `find_api` needs a local copy of Autodesk's help, which is their content and is not redistributed, so you build your own once:

```bash
pip install "fusion-cad-mcp[corpus] @ git+https://github.com/Mfrostbutter/fusion-cad-mcp.git"
fusion-cad-mcp corpus build --i-accept-autodesk-terms
```

That crawls at 1 request/second into `~/.fusion-cad/corpus/`, which is where the server looks first. Set `FUSION_CAD_CORPUS_DIR` to keep it elsewhere. Everything else works without it.

## Development

```bash
pip install -e ".[dev]"
pytest              # 467 tests, no Fusion required
```

The tests cover script generation, envelope parsing, argument validation, and packaging integrity. They deliberately do not need Fusion running, which is also their limit: **passing tests prove the generated Python is valid, not that Fusion accepts it.** Several of the bugs found in this project passed every unit test and only surfaced against a live document, so verify behavioral changes in Fusion and check entity counts rather than trusting a success envelope.

One test guards a bug class worth knowing about: `json.dumps(None)` emits `null`, which is not valid Python, and `ast.parse` cannot catch it because `null` is a legal identifier. Generated code must embed Python values with `repr()`.

## License

MIT. See [LICENSE](LICENSE).
