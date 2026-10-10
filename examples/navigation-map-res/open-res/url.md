`_open_url_string` resolves a link relative to the board and opens `.md` in the zen editor, `.grafli` as a board, the rest in the system.

`grafli/view/resources.py:221`. A `.grafli` link with `#<id>` keeps the id as the URL fragment.
