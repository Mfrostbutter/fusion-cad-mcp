# Connecting fusion-cad-mcp to an MCP client

Three steps: turn on Fusion's API server, install this package, point your client at it.

## 1. Enable Fusion's MCP server

In Fusion: **Preferences > General > API > Fusion MCP Server**, enable it.

This is what actually talks to Fusion. `fusion-cad-mcp` connects to it on `127.0.0.1:27182`, so it must be on or nothing works.

Confirm it is listening:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:27182/mcp
```

`405` means the route exists and only accepts POST, which is correct and healthy. `404` means the server is off. Connection refused means Fusion is not running.

## 2. Install

```bash
pip install "fusion-cad-mcp @ git+https://github.com/Mfrostbutter/fusion-cad-mcp.git"
```

Check it:

```bash
fusion-cad-mcp --help
```

Note the path it installed to, since some clients need an absolute one:

```bash
# macOS / Linux
which fusion-cad-mcp
# Windows PowerShell
(Get-Command fusion-cad-mcp).Source
```

## 3. Point your client at it

### Claude Code

```bash
claude mcp add fusion -- fusion-cad-mcp
```

Or edit the config directly. User scope, `~/.claude.json`, loads in every session:

```json
{
  "mcpServers": {
    "fusion": {
      "type": "stdio",
      "command": "fusion-cad-mcp"
    }
  }
}
```

Project scope, `.mcp.json` in a repo root, loads only in that repo. Use that if you only do CAD work in one place.

Verify with `/mcp` inside Claude Code. You should see `fusion` connected with 75 tools.

### Claude Desktop

Edit the config file:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "fusion": {
      "command": "fusion-cad-mcp"
    }
  }
}
```

Restart Claude Desktop. Desktop does not always resolve commands from PATH, so if it fails to start, use the absolute path from step 2.

### Cursor, Cline, and other MCP clients

Any client speaking stdio MCP works. The server is `fusion-cad-mcp` with no arguments.

### Running from a checkout instead of a wheel

```json
{
  "mcpServers": {
    "fusion": {
      "command": "python",
      "args": ["-m", "fusion_cad_mcp.server"],
      "env": { "PYTHONPATH": "/absolute/path/to/server/src" }
    }
  }
}
```

## Optional: the API documentation corpus

`find_api` searches Autodesk's Fusion API help. That is Autodesk's content and is not redistributed, so you build a local copy once:

```bash
pip install "fusion-cad-mcp[corpus] @ git+https://github.com/Mfrostbutter/fusion-cad-mcp.git"
fusion-cad-mcp corpus build --i-accept-autodesk-terms
```

It crawls at 1 request/second and takes a while. Output goes to `~/.fusion-cad/corpus/`, which is the first place the server looks. Override with `FUSION_CAD_CORPUS_DIR`.

The other 74 tools work without it. Only `find_api` returns `corpus_not_built` until you do this.

## Troubleshooting

**Every call fails with a connection error.** Fusion is not running, or the API server is off. Check step 1.

**Everything worked, then every call started failing after restarting Fusion.** The server re-handshakes automatically on a rejected session, so this should recover on the next call. If it does not, your *client* session is stale rather than the server's: reconnect the MCP server in your client (`/mcp` in Claude Code). No tool call can fix that from the inside.

**`find_api` returns `corpus_not_built`.** Expected until you build the corpus. See above.

**`find_tool` or `find_gotcha` returns `*_not_found`.** The packaged markdown is missing, which should not happen from a wheel. Reinstall.

**A tool returns `ok: true` but nothing changed in Fusion.** Not always a bug. Fusion declines some operations silently and the tools surface it: check `applied` on `drive_joint`, `moved` on `move_component`, `bytes_written` on `export`. If a pattern or mirror looks wrong, count bodies rather than trusting positions, which can be correct while the count is not.

**A tool errors with something Fusion-specific.** Try `find_gotcha` with the symptom. The catalog covers the failure modes found during live testing, including several that report success while doing the wrong thing.
