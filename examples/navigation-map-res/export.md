The HTML export writes this board and every board reachable from it into one page that plays the levels, docs, overlays and tours in a browser.

`reachable_boards` (`grafli/htmlexport.py:128`) follows the same `&graph`, `.grafli` `&link` and tour-stop targets the app opens. Run `grafli export-html navigation-map.grafli navigation-map.html`.
