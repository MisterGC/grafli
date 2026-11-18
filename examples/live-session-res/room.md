Draws each version for every tab.

An edit is applied to the version its sender saw and merged into the file as it is now (`grafli/serve/room.py:760`), then written (`grafli/serve/room.py:770`). The render worker, a separate offscreen-Qt process, draws each version.
