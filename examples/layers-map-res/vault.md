The resource vault is the `<stem>-res/` folder that holds a board's docs, sub-boards, images, palette and data files.

`resolve_code_ref` (`grafli/format.py:565`) resolves a code ref against the board's `# source:` repo; docs and sub-boards resolve against the vault.

`load_palette` (`grafli/map_palette.py:199`) reads the outermost `palette.json` among the board's vault and the vaults it sits in; a box names an entry with `%name`, and the legend lists the entries the board uses.
