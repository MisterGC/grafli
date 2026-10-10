The board stack remembers every board you entered and how you left the one above it, so `gu` brings you back exactly there.

A `BoardFrame` (`grafli/buffers.py:55`) holds the parent board, its view state, the box entered through and a paused tour. It is session state only and is never written into a file.
