`_go_up` is `gu`: it pops the frame and restores the parent board exactly as you left it, then resumes a paused tour.

`_go_up` is defined at `grafli/app.py:796`; the tour picks up in `_resume_tour` (`grafli/app.py:824`).
