The parser turns a box's `&doc:` / `&graph:` / `&link:` token into an attachment kind and a target.

`split_attach` (`grafli/format.py:451`) takes the kind; `split_board_fragment` (`grafli/format.py:468`) splits `open#b_graph` into the sub-board and the id it opens framed on. A board using `#<id>` links carries a `#!grafli v3` header.
