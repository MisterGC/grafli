The keys that move you between levels: Return or `gd` enters, `gu` goes back, `gv` peeks at a box's doc, `gt` lists the tours through a box.

Return in select mode calls `_open_resource` (`grafli/view/core.py:1748`); the `g` chords are dispatched together (`grafli/view/core.py:1383-1396`). During a tour only `gd`, Return and `gu` leave it (`grafli/view/core.py:1115-1124`).
