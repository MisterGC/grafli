grafli never starts it.

It loads `grafli agent` as one of its MCP servers (`grafli/serve/mcp.py:1`) and calls its tools: read, write, undo, render.
