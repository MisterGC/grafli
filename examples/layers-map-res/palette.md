The map palette names one colour per layer, once for every board of the map.

`load_palette` (`grafli/map_palette.py:139`) reads the outermost `palette.json` among the board's vault and the vaults it sits in; a box names an entry with `%name`, and the legend lists the entries the board uses.
