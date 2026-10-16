The HTML export writes every board reachable from one board into a single offline page.

`export_html` (`grafli/htmlexport.py:503`) follows the `&graph` and `&link` attachments and tour stops from the root, draws each board's scene to SVG and keeps its docs, overlays and tours beside it.
