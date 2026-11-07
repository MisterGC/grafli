"""``grafli serve``: a board live in a browser tab on the LAN or a VPN.

The server keeps the file the truth. A worker process renders a board with
the app's own view (offscreen Qt, the way ``grafli export-html`` does) and
the server pushes the drawing and its element rects over a WebSocket to
every tab on that board whenever the file changes. An edit from a tab is a
small operation, applied to the version the tab saw and merged into the
file through ``grafli.sync``.

Only ``render`` imports Qt, and only inside the worker process; ``ops``,
``room`` and ``server`` stay Qt-free.
"""
