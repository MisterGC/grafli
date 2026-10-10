`frame_fragment` frames and selects what a link's `#<id>` names: a bookmark first, else an element.

`grafli/view/flows.py:58`. When neither exists, `_open_board_at` fits the board and toasts "No element" (`grafli/app.py:771`).
