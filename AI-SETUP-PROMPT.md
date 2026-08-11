# AI Setup Prompt

This is a guided setup. You do not need to know how to code. You paste one prompt into an AI assistant and it walks you through installing this server, connecting it to your assistant, and proving it can actually drive Fusion.

It takes about fifteen minutes, most of it waiting on installs.

---

## Before you start: what you need

- **Autodesk Fusion, installed and running**, on the same computer you are setting this up on. Windows or Mac both work. This talks to Fusion locally, so it cannot reach a copy running somewhere else.
- **A Fusion version new enough to have the MCP server built in.** Check **Preferences > General > API**. If you see **Fusion MCP Server** there, you are good. If you do not, update Fusion first.
- **Python 3.11 or newer.** If you do not have it, the prompt below tells you how to get it. On Windows, install from [python.org](https://www.python.org/downloads/) rather than the Microsoft Store, because the Store version puts things in places MCP clients struggle to find.
- **An AI assistant that can run terminal commands.** [Claude Code](https://claude.com/claude-code) is the easiest path since it can do the install itself. Claude Desktop works too; it will hand you commands to paste. ChatGPT or Gemini in a browser can also coach you through it, you will just be doing more of the typing.
- **Use a reasoning-capable model.** Claude Opus or Sonnet, GPT-5, or Gemini 2.5 Pro. Smaller and faster models will get you through it but tend to skip the verification steps, which is where setup problems actually show up.

---

## One thing to understand first

This lets an AI edit your CAD models. It creates sketches, cuts holes, moves bodies, and can overwrite files when it exports or saves.

Fusion has undo, and this server exposes it, so most mistakes are one `undo` away. But an assistant working fast can stack up ten operations before you notice the third one was wrong.

So:

- **Do not point it at a design you care about on the first run.** Make a new empty design to test with.
- Save a version before you let it work on something real. Fusion keeps version history, use it.
- Watch what it does the first few times. Ask it to take a screenshot after each significant step. It has a `screenshot` tool for exactly this reason.

Nothing here phones home, and it only talks to Fusion on your own machine. The risk is not privacy, it is an assistant confidently modeling the wrong thing.

---

## Step 1: turn on Fusion's API server

In Fusion: **Preferences > General > API > Fusion MCP Server**, turn it on.

This is the piece that actually talks to Fusion. Everything else connects through it, so if this is off, nothing works. Leave Fusion running with a design open.

## Step 2: paste this prompt to your assistant

Copy everything in the box and send it.

```
I want to set up fusion-cad-mcp, an MCP server that lets you drive Autodesk
Fusion directly: sketches, extrudes, holes, joints, exports. The repo is at
https://github.com/Mfrostbutter/fusion-cad-mcp and the setup details are in its
README.md and CONNECT.md. Read those first if you can fetch them.

I am not a developer. Please walk me through this one step at a time, wait for
me after each step, and stop and explain if something looks wrong instead of
pushing through it. Tell me what each command does before I run it.

Here is what I would like you to do:

1. Tell me what operating system and shell I should be typing commands into,
   and confirm with me before assuming. On Windows, use PowerShell.

2. Check whether Python 3.11 or newer is installed. If it is not, walk me
   through installing it from python.org, and on Windows make sure "Add Python
   to PATH" gets checked. Do not use the Microsoft Store version.

3. Check whether git is installed. If it is not, either walk me through
   installing it, or use the ZIP download route instead: download
   https://github.com/Mfrostbutter/fusion-cad-mcp/archive/refs/heads/main.zip ,
   unzip it, and pip install that folder.

4. Install the server:
   pip install "fusion-cad-mcp @ git+https://github.com/Mfrostbutter/fusion-cad-mcp.git"
   Then confirm it landed by running: fusion-cad-mcp --help
   Also find and show me the full path to the installed command, because some
   MCP clients need an absolute path rather than just the name.

5. Confirm Fusion's own API server is reachable. A request to
   http://127.0.0.1:27182/mcp should come back 405, which means the route
   exists and only accepts POST. That is the healthy answer. Explain what 404
   and connection-refused would mean instead, and help me fix it if I get one.

6. Connect it to my AI assistant. Ask me which one I use first, then give me
   the exact config for that client using the real path from step 4. CONNECT.md
   in the repo has the per-client details. Tell me if I need to restart the
   client.

7. Verify it actually works, and do not skip this. With an empty Fusion design
   open, call doc_state and confirm active_design is true. Then create a sketch,
   draw a 40mm square, extrude it 10mm, and take a screenshot so I can see the
   result. Show me the screenshot.

8. Optional, ask me if I want it: build the local Autodesk API documentation
   corpus so the find_api tool works. It crawls Autodesk's help site at 1
   request per second and takes a while, and everything else works without it.
   Explain what it is before I decide.

Two things to keep in mind while we work:

- Every tool returns an "ok" flag, and ok being true does not always mean the
  thing happened. Fusion declines some operations silently. Read the "result"
  payload, not just "ok".
- If a Fusion-specific error comes up, use the find_gotcha tool. It searches a
  catalog of known Fusion API failure modes, including several that report
  success while doing the wrong thing.
```

## Step 3: try it

Once step 7 above has produced a screenshot of a real extruded block, you are connected. Things worth asking for next:

- "Make me a parametric box, 100 by 60 by 40mm, 3mm walls, open top. Use parameters so I can change the dimensions later."
- "Add four M3 clearance holes to that plate, inset 8mm from each corner."
- "This part is 140mm tall. Will it fit on a 256mm bed if I lay it flat? Check the bounding box."
- "Show me the current design from an isometric view."
- "Export the active body as a 3MF to my desktop."
- "What is the volume of this body? Roughly how much filament is that at 20 percent infill?"

Ask it to screenshot as it goes. Watching each step is how you catch a wrong turn on step three instead of step twelve.

---

## If something goes wrong

**"Every call fails with a connection error."** Fusion is not running, or its API server is off. Go back to Step 1. This is by far the most common one, and it also happens if you quit Fusion mid-session.

**"It worked, then everything broke after I restarted Fusion."** The server reconnects on its own for most cases. If it does not, your assistant's connection is the stale part, not the server. Reconnect the MCP server in your client (`/mcp` in Claude Code) or restart the client. No amount of retrying the tool will fix it.

**"My client says the command was not found."** It cannot see `fusion-cad-mcp` on your PATH. Use the full absolute path from step 4 of the prompt instead. Claude Desktop in particular does not always inherit your PATH.

**"pip is not recognized."** Python is not installed, or it was not added to PATH during install. On Windows, reinstalling from python.org with "Add Python to PATH" checked fixes it. Try `py -m pip` instead of `pip` as a workaround.

**"find_api says corpus_not_built."** Expected. That one tool needs the optional documentation corpus from step 8. The other 74 tools work without it.

**"The AI said it did something but Fusion looks unchanged."** Not always a bug. Some Fusion operations decline silently and this server reports it rather than hiding it. Ask your assistant to read the full `result` payload, and to count bodies rather than trusting that a pattern or mirror looks right.

**"My assistant is stuck or going in circles."** Tell it to stop and re-read `README.md` and `CONNECT.md` from the repo, then start over from whichever step last succeeded. If it still cannot get past it, open an issue on the repo with what you ran and what came back. Plain language is fine.
