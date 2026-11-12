Reads the agent key from a file.

Claude Code starts it as an MCP server over stdio; on connect it opens `WS /agent` with the key from `serve-<port>.json` (`grafli/serve/agent.py:81`), which no link carries.
