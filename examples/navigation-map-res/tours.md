A tour is a flow of bookmarks; a stop written `<board>#<bookmark>` lies in another board, and playing it enters that board.

`play_flow` starts playback (`grafli/view/flows.py:82`); a stop's bookmark in another board is looked up by `_step_bookmark` (`grafli/app.py:1442`). Leaving a tour through a level keeps its `TourPosition` (`grafli/buffers.py:40`) in the frame, and `gu` resumes it.
