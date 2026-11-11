The keys that move you between levels: Return or `gd` enters, `gu` goes back, `gv` peeks at a box's doc, `gt` lists the tours through a box.

Return in select mode calls `_open_resource` (`grafli/view/resources.py:142`); the `g` chords are dispatched together, `gd` into `_go_down` (`grafli/view/core.py:1401-1414`). During a tour only `gd`, Return and `gu` leave it, because `_flow_player` owns the other keys (`grafli/view/core.py:1133-1142`).
