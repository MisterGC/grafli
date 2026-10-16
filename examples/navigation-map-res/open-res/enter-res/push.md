`push_frame` records entering a board; entering from a board off the current chain starts a new chain.

`push_frame` is defined at `grafli/buffers.py:146` and called from `switch()` in `_enter_board` (`grafli/app.py:743`).
