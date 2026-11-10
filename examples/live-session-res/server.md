Checks each key; passes cursors on, stores none.

It routes `WS /ws/<board>` for tabs and `WS /agent` for the bridge (`grafli/serve/server.py:530`) and writes the state file with the agent key at start (`grafli/serve/server.py:772`). Presence never reaches the file.
