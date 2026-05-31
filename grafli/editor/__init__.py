"""Reusable text-editor components.

These widgets are deliberately free of any grafli-specific concepts
(no `Note` model, no scene, no view) so they can be lifted into a
standalone editor package — offering both a dedicated app and embeddable
components — without untangling dependencies. The only collaborators are
the editor-internal vim handler and Markdown highlighter, which would
move with them.
"""

from grafli.editor.inline_editor import InlineVimEditor

__all__ = ["InlineVimEditor"]
