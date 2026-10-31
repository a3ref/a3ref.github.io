# Arma 3 MCP server: SQF reference and linter for AI agents

The a3ref MCP server gives Claude Code, Codex, Antigravity, Cursor, VS Code and any other
[MCP](https://modelcontextprotocol.io) client the complete Arma 3 scripting reference: every scripting command,
every `BIS_fnc_*` function and the core concept pages (data types, locality, scheduler, event handlers), mirrored
daily from the Bohemia Interactive Community Wiki. It also checks SQF for the mistakes language models make most:
made-up commands, missing operands, unknown functions and deprecated commands.

It is free and open source (MIT), needs no account or API key, and runs on Windows, macOS and Linux.

## What the agent gets

| Tool | What it does |
|---|---|
| `search` | Find commands, functions and topics by name, partial name, operator symbol (`>>`, `!=`) or by what they do ("delete vehicle") |
| `get` | Read a page: syntax, typed parameters, return value, locality, examples, community notes. Any spelling works (`SETPOS`, `spawnGroup`, `bis fnc spawngroup`); `section` returns one part of a long topic, e.g. one event handler |
| `list_group` | Everything in a command or function group ("Multiplayer", "Object Manipulation", ...) |
| `lint_sqf` | Check SQF: made-up commands, commands used without their left operand or argument, unknown `BIS_fnc_*` functions, deprecated or broken commands, diagnostic-build-only commands, `format` strings missing values, unknown event handler names |
| `recent_changes` | What changed on the wiki recently |

What `lint_sqf` reports:

```text
Checked 3 lines: 2 errors, 1 warnings, 0 notes.

1:8 error: Unknown command setUnitHealth (used as a binary command).
2:1 error: setPos needs a left operand. Syntax: `object setPos pos`.
3:4 warning: ctrlSetEventHandler is deprecated. Use ctrlAddEventHandler instead.
```

The linter only reports what cannot be valid SQF, so it stays quiet on correct code. Run over the 5,500 SQF
examples on the wiki, it reports 23 errors, nearly all of them config or prose pasted into code blocks.

## Install

Every client starts the same command, `npx -y github:a3ref/mcp`, which needs
[Node.js](https://nodejs.org/) 18 or newer. The server is a single file with no dependencies: the first start
downloads it, later starts reuse the copy npm keeps.

### Claude Code

As a plugin, which adds the MCP server and the `sqf` skill (it tells Claude to check commands and lint SQF before
showing it). Type in Claude Code:

```text
/plugin marketplace add a3ref/mcp
/plugin install a3ref@a3ref
```

The server only, for every project (leave out `--scope user` for the current project only):

```sh
claude mcp add --scope user a3ref -- npx -y github:a3ref/mcp
```

Check with `/mcp` in Claude Code: `a3ref` should be listed as connected.

### Claude Desktop

Settings, Developer, Edit Config opens `claude_desktop_config.json`
(`%APPDATA%\Claude\` on Windows, `~/Library/Application Support/Claude/` on macOS). Add the server and restart
Claude Desktop:

```json
{
  "mcpServers": {
    "a3ref": {
      "command": "npx",
      "args": ["-y", "github:a3ref/mcp"]
    }
  }
}
```

### Codex

As a plugin, with the MCP server and the `sqf` skill:

```sh
codex plugin marketplace add a3ref/mcp
codex plugin add a3ref@a3ref
```

Or, after adding the marketplace, install `a3ref` from the Plugins directory of the ChatGPT desktop app. The Codex
CLI, the Codex IDE extension and the ChatGPT desktop app share plugins and configuration, so one install covers
all three.

The server only:

```sh
codex mcp add a3ref -- npx -y github:a3ref/mcp
```

Or add it to `~/.codex/config.toml` yourself (or to `.codex/config.toml` in a trusted project):

```toml
[mcp_servers.a3ref]
command = "npx"
args = ["-y", "github:a3ref/mcp"]
```

Check with `codex mcp list` in a terminal or `/mcp` in the Codex CLI.

### Antigravity

As a plugin, with the MCP server and the `sqf` skill:

```sh
agy plugin install https://github.com/a3ref/mcp
```

Plugins installed with the CLI or the Antigravity app are available in the app, the IDE and the CLI.

The server only: the Antigravity app, the Antigravity IDE and the Antigravity CLI (`agy`) read the same file:
`~/.gemini/config/mcp_config.json` for every project, or `.agents/mcp_config.json` in a workspace for that
workspace only. In the IDE, the agent panel's menu (…), MCP Servers, Manage MCP Servers, View raw config opens it.

```json
{
  "mcpServers": {
    "a3ref": {
      "command": "npx",
      "args": ["-y", "github:a3ref/mcp"]
    }
  }
}
```

In the CLI, `/mcp` opens the MCP manager, which shows whether the server is connected and reloads the
configuration. Antigravity CLI replaced Gemini CLI in 2026; set the server up there as shown here.

### Cursor

`.cursor/mcp.json` in a project, or `~/.cursor/mcp.json` for every project:

```json
{
  "mcpServers": {
    "a3ref": {
      "command": "npx",
      "args": ["-y", "github:a3ref/mcp"]
    }
  }
}
```

### Windsurf

`~/.codeium/windsurf/mcp_config.json`, with the same `mcpServers` entry as for Cursor.

### VS Code (Copilot agent mode)

`.vscode/mcp.json` in the workspace:

```json
{
  "servers": {
    "a3ref": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "github:a3ref/mcp"]
    }
  }
}
```

### Other clients

Any client that runs local (stdio) MCP servers works: give it the command `npx` with the arguments
`-y github:a3ref/mcp`. Most take the `mcpServers` JSON shown for Cursor.

## Try it

Ask the agent something that needs the reference, for example:

- "Which command deletes a vehicle with its crew? Check the locality."
- "Spawn a group of four NATO riflemen near the player, then lint the script."
- "What changed on the Arma 3 wiki this week?"

The agent should call `search`, `get` or `lint_sqf` instead of answering from memory.

## Troubleshooting

- **The server does not start.** Run `node --version` (18 or newer is needed), then
  `npx -y github:a3ref/mcp` in a terminal: it should start and wait for input without printing anything
  (Ctrl+C ends it).
- **Windows: the client cannot find `npx`.** Some clients do not run `.cmd` files directly. Use the command `cmd`
  with the arguments `/c npx -y github:a3ref/mcp`, e.g. `"command": "cmd", "args": ["/c", "npx", "-y", "github:a3ref/mcp"]`.
- **Your own copy of the site.** The server reads https://a3ref.github.io/; set the environment variable
  `A3REF_BASE_URL` to read a mirror instead.

## How it works

The server downloads what it needs from this site (`index.json`, `syntax.json` and the pages the agent asks for)
and keeps it in memory for an hour. Nothing is bundled, so answers follow the wiki without updating the server.

No MCP client? Every page of this site is also plain Markdown and JSON at a stable URL; an agent that can fetch
web pages can start from [llms.txt](https://a3ref.github.io/llms.txt). The source code, issues and release notes
are on [GitHub](https://github.com/a3ref/mcp).
