"""The "grafli at a glance" page (#324): how to work with grafli and its
agent, and every key by mode, as one HTML page.

The keys come from :mod:`grafli.keymap`, the table the F1 help renders, so
the two cannot drift apart. The page needs no server and no internet: the
F1 help writes it next to the installed version and opens it in the
browser, and the website publishes the same page as ``docs/at-a-glance.html``.
Regenerate that copy after changing the table::

    python -m grafli.helppage docs/at-a-glance.html
"""

from __future__ import annotations

import os
import sys
import tempfile
from html import escape
from pathlib import Path

from grafli import keymap

SITE = "https://grafli.mistergc.dev"
DOCS_COPY = Path("docs") / "at-a-glance.html"

_LINKS = (
    ("watch", "Watch link", "follows the presenter, points, reads"),
    ("edit", "Edit link", "builds and asks the agent, by key or mouse"),
    ("present", "Present link", "yours: the others follow it"),
)

# Accent per group: the agent's purple, the presenter's orange.
_ACCENT = {"tab-agent": "agent", "tab-reveal": "present"}


def _e(text: str) -> str:
    return escape(text, quote=False)


def _cap(name: str) -> str:
    # ⇧, ⌘ and the arrows are drawn far too small by monospace fonts.
    glyph = not any(ch.isascii() for ch in name)
    cls = ' class="glyph"' if glyph else ""
    return f"<kbd{cls}>{_e(name)}</kbd>"


def keys_html(k: keymap.Key) -> str:
    """The row's keys as keycaps: alternatives split by a slash, a
    sequence side by side, a chord joined by ``+``."""
    if k.is_gesture:
        return f'<span class="gest">{_e(k.keys)}</span>'
    alts = []
    for alt in keymap.parse_keys(k.keys):
        steps = []
        for chord in alt:
            caps = [_cap(keymap.key_name(p)) for p in chord]
            steps.append('<span class="plus">+</span>'.join(caps))
        alts.append('<span class="seq">' + "".join(steps) + "</span>")
    return '<span class="or">/</span>'.join(alts)


def _kbd(notation: str) -> str:
    return keys_html(keymap.key(notation, ""))


def row_html(k: keymap.Key) -> str:
    """One row of a card: its keys beside what they do."""
    return (f'<div class="row"><div class="k">{keys_html(k)}</div>'
            f'<div class="d">{_e(k.does)}</div></div>')


def card_html(page: str, group_id: str) -> str:
    """The card of group ``group_id`` cut out of the rendered ``page``."""
    return page.split(f'id="k-{group_id}"', 1)[1].split("</article>", 1)[0]


def _card(g: keymap.Group) -> str:
    accent = _ACCENT.get(g.id, "")
    cls = f"card {accent}".strip()
    head = f'<h3>{_e(g.title)}'
    if g.enter:
        head += f' <span class="enter">{_kbd(g.enter)}</span>'
    head += "</h3>"
    rows = "\n".join(row_html(k) for k in g.keys)
    blurb = f'<p class="blurb">{_e(g.blurb)}</p>' if g.blurb else ""
    return (f'<article class="{cls}" id="k-{g.id}">\n{head}\n{blurb}\n'
            f'<div class="rows">\n{rows}\n</div>\n</article>')


def _short(does: str) -> str:
    return does.split(" (")[0].split(":")[0].split(",")[0]


def _mode_map() -> str:
    """Select in the middle, a spoke per mode one key away."""
    spokes = []
    modes = next(g for g in keymap.GROUPS if g.id == "modes")
    for k in modes.keys:
        if k.keys in ("v", "Esc"):
            continue
        spokes.append((k.keys, _short(k.does), "k-modes"))
    for g in keymap.groups(keymap.APP):
        if g.enter:
            spokes.append((g.enter, g.title, f"k-{g.id}"))
    items = "\n".join(
        f'<a class="spoke" href="#{href}">{_kbd(keys)}'
        f'<span>{_e(name)}</span></a>'
        for keys, name, href in spokes
    )
    return (
        '<div class="modemap">\n'
        '<div class="hub"><span class="hub-name">Select</span>'
        f'<span class="hub-keys">{_kbd("v / Esc")}</span>'
        '<span class="hub-note">home: every topic below works here</span>'
        "</div>\n"
        f'<div class="spokes">\n{items}\n</div>\n</div>'
    )


def _link_strip() -> str:
    cols = []
    for link, name, does in _LINKS:
        chips = "".join(
            f'<a class="chip {_ACCENT.get(g.id, "")}" href="#k-{g.id}">'
            f"{_e(g.title)}</a>"
            for g in keymap.groups(keymap.TAB) if link in g.links
        )
        cols.append(
            f'<div class="link {link}"><h3>{name}</h3>'
            f'<p>{does}</p><div class="chips">{chips}</div></div>'
        )
    return '<div class="links">\n' + "\n".join(cols) + "\n</div>"


_ICON = {
    "app": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2.5" '
           'y="4" width="19" height="15" rx="2"/><path d="M2.5 8h19"/>'
           '<rect x="6" y="11" width="5" height="4" rx="1"/>'
           '<path d="M11 13h4.5v-2.5"/></svg>',
    "file": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 2.5h8'
            'l4.5 4.5v14.5h-12.5z"/><path d="M14 2.5V7h4.5M9 12h6M9 15.5h6'
            'M9 19h3.5"/></svg>',
    "session": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2.5" '
               'y="4" width="19" height="16" rx="2"/><path d="M6.5 10l3 2.5'
               '-3 2.5M12 15.5h5"/></svg>',
    "serve": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" '
             'y="3.5" width="17" height="7" rx="1.5"/><rect x="3.5" y="13.5"'
             ' width="17" height="7" rx="1.5"/><path d="M7 7h.01M7 17h.01"/>'
             '</svg>',
    "tabs": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="2.5" '
            'y="5" width="19" height="15" rx="2"/><path d="M2.5 9.5h19M6 '
            '5v4.5M11 5v4.5"/></svg>',
}


def _node(icon: str, name: str, sub: str, cls: str = "") -> str:
    klass = f"node {cls}".strip()
    return (f'<div class="{klass}">{_ICON[icon]}'
            f"<b>{name}</b><span>{sub}</span></div>")


def _wire(fwd: str, back: str) -> str:
    return (
        '<div class="wire">'
        f'<span class="fwd"><i class="ar r">→</i><i class="ar d">↓'
        f'</i>{fwd}</span>'
        f'<span class="back"><i class="ar r">←</i><i class="ar d">'
        f'↑</i>{back}</span>'
        "</div>"
    )


def _steps(steps) -> str:
    items = "\n".join(
        f'<li><div class="do">{do}</div><div class="get">{get}</div></li>'
        for do, get in steps
    )
    return f'<ol class="steps">\n{items}\n</ol>'


def _desk() -> str:
    flow = (
        '<div class="flow">'
        + _node("app", "grafli", "your keys, saved as you go")
        + _wire("saves", "redraws on change")
        + _node("file", "board.grafli", "plain text, in git", "file")
        + _wire("reads the notes", "writes the board")
        + _node("session", "Claude Code", "with the grafli skill", "agent")
        + "</div>"
    )
    notes = (
        '<div class="notes">'
        '<span class="note task"><b>T:</b> split the cache in two</span>'
        '<span class="note question"><b>Q:</b> why two queues?</span>'
        "</div>"
    )
    steps = _steps([
        ("<code>grafli skill install claude</code>",
         "Once: the session learns to write boards that read well."),
        ("Ask: <q>draw the request path as a grafli board</q>",
         "The session writes <code>board.grafli</code> and checks it with "
         "<code>grafli render</code>."),
        ("<code>grafli board.grafli</code>",
         "The app opens it and redraws whenever the session changes the "
         "file."),
        (f"{_kbd('t')} click, type <code>T:</code> or <code>Q:</code>",
         "A task for the session, or a question it answers on the board."),
        ("Ask: <q>work the notes on the board</q>",
         "It does the tasks and answers the questions beside them."),
        ("<code>git diff</code>",
         "The board is text: review what changed, line by line."),
    ])
    return (
        '<article class="way desk">\n'
        '<p class="eyebrow">At your desk</p>\n'
        "<h3>The session edits the file, the app shows it</h3>\n"
        f"{flow}\n{notes}\n{steps}\n</article>"
    )


def _meeting() -> str:
    flow = (
        '<div class="flow">'
        + _node("tabs", "Browser tabs", "present, edit, watch", "present")
        + _wire(f"edits, {_kbd(':')} requests", "drawings, live")
        + _node("serve", "grafli serve", "on your LAN or VPN")
        + _wire("requests", "edits it")
        + _node("session", "Claude Code", "connected via grafli agent",
                "agent")
        + "</div>"
    )
    steps = _steps([
        ("<code>claude mcp add -s user grafli -- grafli agent</code>",
         "Once: Claude Code knows grafli's tools."),
        ("<code>grafli serve boards/ --host 192.168.1.20</code>",
         "Three links per board: open <em>present</em> yourself, hand out "
         "<em>edit</em> or <em>watch</em>."),
        ("<code>claude --dangerously-load-development-channels "
         "server:grafli</code>, then <code>/mcp__grafli__connect</code>",
         "Your session is the agent: every tab shows it in the bar, in "
         "purple."),
        (f"{_kbd(':')} plain language, or {_kbd('a')} on the selection",
         f"Its edit lands and glows. More than 5 changes wait as a proposal: "
         f"{_kbd('Enter')} takes it, {_kbd('x')} drops it."),
        (_kbd("Shift+U"),
         "Takes back the agent's last edit; what the others changed stays."),
        ("Ask: <q>disconnect from grafli</q>",
         "Leaving: the tabs show the agent as gone. Stop "
         "<code>grafli serve</code> and the board is gone from every tab; "
         "the files never left your machine."),
    ])
    return (
        '<article class="way meet">\n'
        '<p class="eyebrow">In a meeting</p>\n'
        "<h3>grafli serve in a tab, your session as the agent</h3>\n"
        f"{flow}\n{steps}\n</article>"
    )


_CSS = """
:root {
  --bg: #F6F3EE; --card: #FFFDF9; --ink: #2F3437; --muted: #5A5A5A;
  --faint: #8A8580; --rule: #D5D0C8; --cap: #FFFFFF; --cap-edge: #B3AB9E;
  --surface: #ECE8E1; --teal: #2F5D5C; --agent: #7048E8;
  --present: #C9692F; --task: #C53030; --question: #805AD5;
  --agent-soft: #7048E81A; --present-soft: #D4804E22;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #1C1B18; --card: #24221E; --ink: #E8E4DD; --muted: #C4BFB6;
    --faint: #8C877F; --rule: #3B372F; --cap: #2F2C27; --cap-edge: #5A554C;
    --surface: #2A2823; --teal: #6FB3B0; --agent: #A48BF5;
    --present: #DB8B5C; --task: #E07070; --question: #A98BE8;
    --agent-soft: #A48BF524; --present-soft: #DB8B5C24;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #1C1B18; --card: #24221E; --ink: #E8E4DD; --muted: #C4BFB6;
  --faint: #8C877F; --rule: #3B372F; --cap: #2F2C27; --cap-edge: #5A554C;
  --surface: #2A2823; --teal: #6FB3B0; --agent: #A48BF5;
  --present: #DB8B5C; --task: #E07070; --question: #A98BE8;
  --agent-soft: #A48BF524; --present-soft: #DB8B5C24;
  color-scheme: dark;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.5 Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI",
    sans-serif;
  -webkit-font-smoothing: antialiased;
}
code, kbd { font-family: "JetBrains Mono", ui-monospace,
  SFMono-Regular, Menlo, Consolas, monospace; }
a { color: inherit; }
.top {
  display: flex; flex-wrap: wrap; align-items: baseline; gap: .25rem 1.5rem;
  padding: 1rem clamp(1rem, 4vw, 3rem); border-bottom: 1px solid var(--rule);
}
.mark { font-weight: 800; font-size: 1.25rem; letter-spacing: -.02em;
  text-decoration: none; }
.top nav { display: flex; flex-wrap: wrap; gap: .25rem 1.25rem;
  font-size: .9rem; }
.top nav a { color: var(--muted); text-decoration: none; }
.top nav a:hover { color: var(--ink); text-decoration: underline; }
main { max-width: 76rem; margin: 0 auto;
  padding: 0 clamp(1rem, 4vw, 3rem) 4rem; }
.hero { padding: 3rem 0 1rem; }
.hero h1 { font-size: clamp(2rem, 6vw, 3.25rem); line-height: 1.05;
  letter-spacing: -.03em; margin: 0 0 .75rem; font-weight: 800; }
.hero p { font-size: 1.1rem; color: var(--muted); max-width: 44rem;
  margin: 0; }
section { padding-top: 2.5rem; }
h2 { font-size: 1.5rem; letter-spacing: -.02em; margin: 0 0 .25rem; }
.lede { color: var(--muted); margin: 0 0 1.25rem; max-width: 48rem; }
.ways { display: grid; gap: 1.25rem;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 30rem), 1fr)); }
.way { background: var(--card); border: 1px solid var(--rule);
  border-radius: 14px; padding: 1.25rem 1.25rem 1rem; min-width: 0; }
.eyebrow { margin: 0; font-size: .75rem; font-weight: 700;
  letter-spacing: .08em; text-transform: uppercase; color: var(--teal); }
.meet .eyebrow { color: var(--present); }
.way h3 { margin: .15rem 0 1rem; font-size: 1.15rem; letter-spacing: -.01em; }
.flow { display: flex; align-items: stretch; gap: 0; margin-bottom: .75rem; }
.node { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column;
  align-items: center; text-align: center; gap: .1rem; padding: .7rem .4rem;
  border: 1.5px solid var(--ink); border-radius: 10px;
  background: var(--bg); }
.node svg { width: 26px; height: 26px; fill: none; stroke: currentColor;
  stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round;
  margin-bottom: .15rem; }
.node b { font-size: .92rem; }
.node span { font-size: .75rem; color: var(--muted); line-height: 1.3; }
.node.file { border-style: dashed; }
.node.agent { border-color: var(--agent); background: var(--agent-soft); }
.node.agent svg, .node.agent b { color: var(--agent); }
.node.present { border-color: var(--present); background: var(--present-soft); }
.node.present svg, .node.present b { color: var(--present); }
.wire { flex: 0 0 6.25rem; display: flex; flex-direction: column;
  justify-content: center; gap: .35rem; padding: 0 .35rem;
  font-size: .72rem; color: var(--muted); line-height: 1.2; }
.wire span { display: flex; align-items: baseline; gap: .25rem; }
.wire .back { justify-content: flex-end; text-align: right;
  flex-direction: row-reverse; }
.wire .ar { font-style: normal; color: var(--ink); font-size: .95rem; }
.wire .ar.d { display: none; }
.wire kbd { font-size: .68rem; padding: 0 .3em; min-width: 1.3em; }
.notes { display: flex; flex-wrap: wrap; gap: .5rem; justify-content: center;
  margin: 0 0 .75rem; }
.note { font-size: .82rem; padding: .3rem .6rem; border-radius: 6px;
  border: 1px solid currentColor; background: var(--bg); }
.note.task { color: var(--task); }
.note.question { color: var(--question); }
.steps { list-style: none; counter-reset: s; margin: 0; padding: 0; }
.steps li { counter-increment: s; display: grid;
  grid-template-columns: 1.75rem 1fr; column-gap: .5rem;
  padding: .55rem 0; border-top: 1px solid var(--rule); }
.steps li::before { content: counter(s); grid-row: span 2; width: 1.5rem;
  height: 1.5rem; border-radius: 50%; background: var(--surface);
  font-size: .78rem; font-weight: 700; display: grid; place-items: center;
  margin-top: .05rem; }
.do { font-weight: 600; font-size: .9rem; overflow-wrap: anywhere; }
.get { color: var(--muted); font-size: .88rem; }
.do code, .get code { font-size: .82em; background: var(--surface);
  padding: .05em .35em; border-radius: 4px; font-weight: 500; }
q { font-style: italic; font-weight: 500; }
kbd { display: inline-block; min-width: 1.6em; padding: .05em .4em;
  border: 1px solid var(--cap-edge); border-bottom-width: 2.5px;
  border-radius: 5px; background: var(--cap); color: var(--ink);
  font-size: .8rem; line-height: 1.45; text-align: center;
  font-weight: 600; white-space: nowrap; }
kbd.glyph { font-family: ui-sans-serif, system-ui, -apple-system,
  "Segoe UI", sans-serif; font-size: .9rem; line-height: 1.3; }
.plus { color: var(--faint); font-size: .75rem; margin: 0 .12em; }
.or { color: var(--faint); margin: 0 .3em; font-size: .85rem; }
.seq { display: inline-flex; gap: .15em; align-items: center;
  white-space: nowrap; }
.gest { font-size: .8rem; color: var(--teal); font-weight: 600;
  font-style: italic; line-height: 1.3; }
.modemap { display: grid; grid-template-columns: minmax(11rem, 15rem) 1fr;
  align-items: center; margin: 0 0 1.5rem; }
.hub { display: flex; flex-direction: column; align-items: flex-start;
  gap: .35rem; padding: 1rem 1.1rem; border: 2px solid var(--ink);
  border-radius: 14px; background: var(--card); position: relative;
  z-index: 1; }
.hub-name { font-size: 1.35rem; font-weight: 800; letter-spacing: -.02em; }
.hub-note { font-size: .78rem; color: var(--muted); }
.spokes { display: grid; gap: .5rem;
  grid-template-columns: repeat(auto-fill, minmax(10.5rem, 1fr));
  margin-left: 1.5rem; padding: .25rem 0 .25rem 1.25rem;
  border-left: 2px solid var(--ink); position: relative; }
.spokes::before { content: ""; position: absolute; left: -1.5rem;
  top: 50%; width: 1.5rem; border-top: 2px solid var(--ink); }
.spoke { display: flex; align-items: center; gap: .55rem;
  padding: .45rem .6rem; border: 1px solid var(--rule); border-radius: 9px;
  background: var(--card); text-decoration: none; font-size: .88rem;
  font-weight: 600; }
.spoke:hover { border-color: var(--ink); }
.cards { columns: 3 20rem; column-gap: 1rem; }
.card { background: var(--card); border: 1px solid var(--rule);
  border-radius: 12px; padding: .9rem 1rem .6rem; min-width: 0;
  scroll-margin-top: 1rem; break-inside: avoid; margin: 0 0 1rem;
  display: inline-block; width: 100%; }
.card:target { outline: 2px solid var(--teal); }
.card h3 { margin: 0; font-size: 1rem; display: flex; align-items: center;
  justify-content: space-between; gap: .5rem; }
.card.agent { border-color: var(--agent); }
.card.agent h3 { color: var(--agent); }
.card.present { border-color: var(--present); }
.card.present h3 { color: var(--present); }
.blurb { margin: .1rem 0 .5rem; font-size: .8rem; color: var(--faint); }
.rows { display: grid; grid-template-columns: max-content 1fr;
  column-gap: .75rem; }
.row { display: contents; }
.row > div { padding: .32rem 0; border-top: 1px solid var(--rule); }
.k { display: flex; flex-wrap: wrap; align-items: center; row-gap: .2rem;
  max-width: 10rem; }
.d { font-size: .87rem; }
.links { display: grid; gap: 1rem; margin: 0 0 1.5rem;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr)); }
.link { border-radius: 12px; padding: .9rem 1rem; border: 1px solid
  var(--rule); background: var(--card); }
.link.present { border: 2px solid var(--present); }
.link h3 { margin: 0; font-size: 1rem; }
.link.present h3 { color: var(--present); }
.link p { margin: .15rem 0 .6rem; color: var(--muted); font-size: .85rem; }
.chips { display: flex; flex-wrap: wrap; gap: .35rem; }
.chip { font-size: .8rem; font-weight: 600; text-decoration: none;
  padding: .15rem .55rem; border-radius: 999px; background: var(--surface); }
.chip.agent { background: var(--agent-soft); color: var(--agent); }
.chip.present { background: var(--present-soft); color: var(--present); }
footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid
  var(--rule); color: var(--faint); font-size: .82rem; }
footer code { font-size: .9em; }
@media (max-width: 40rem) {
  .flow { flex-direction: column; align-items: stretch; }
  .node { flex-direction: row; text-align: left; gap: .6rem;
    padding: .55rem .75rem; flex-wrap: wrap; }
  .node svg { margin: 0; }
  .node span { flex-basis: 100%; padding-left: calc(26px + .6rem);
    margin-top: -.2rem; }
  .wire { flex: none; flex-direction: row; justify-content: center;
    gap: 1.25rem; padding: .35rem 0; }
  .wire .back { flex-direction: row; text-align: left; }
  .wire .ar.r { display: none; }
  .wire .ar.d { display: inline; }
  .modemap { grid-template-columns: 1fr; }
  .spokes { margin: 0 0 0 1.25rem; padding-top: 1rem;
    grid-template-columns: 1fr 1fr; }
  .spokes::before { left: -2px; top: -1px; width: 0; height: 0; }
  .spoke { font-size: .82rem; }
  .k { max-width: 8.5rem; }
}
"""


def render_page() -> str:
    """The whole page, as a string."""
    app_cards = "\n".join(_card(g) for g in keymap.groups(keymap.APP))
    tab_cards = "\n".join(_card(g) for g in keymap.groups(keymap.TAB))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>grafli at a glance</title>
<meta name="description" content="How to work with grafli and your agent, \
and every key by mode.">
<style>{_CSS}</style>
</head>
<body>
<header class="top">
<a class="mark" href="{SITE}/">grafli</a>
<nav>
<a href="#agent">With your agent</a>
<a href="#app">Desktop keys</a>
<a href="#tab">Browser tab keys</a>
<a href="{SITE}/keybindings/">Every key, in words ↗</a>
</nav>
</header>
<main>
<section class="hero">
<h1>grafli at a glance</h1>
<p>Draw a board with the keyboard, let your Claude Code session draw on it
with you, at your desk or live in a meeting, and find every key by the mode
it works in.</p>
</section>
<section id="agent">
<h2>Two ways to work with your agent</h2>
<p class="lede">The agent is a Claude Code session you already run. grafli
never starts one: at your desk the session edits the file, in a meeting you
connect it to the board.</p>
<div class="ways">
{_desk()}
{_meeting()}
</div>
</section>
<section id="app">
<h2>The desktop app, by mode</h2>
<p class="lede">Select is home: most keys work there, on what is selected.
One key enters a mode, <kbd>Esc</kbd> comes back. <kbd>F1</kbd> shows all
of this in the app, with a filter.</p>
{_mode_map()}
<div class="cards">
{app_cards}
</div>
</section>
<section id="tab">
<h2>The browser tab</h2>
<p class="lede"><code>grafli serve</code> prints three links per board. Each
link's tab has its own share of the keys:</p>
{_link_strip()}
<div class="cards">
{tab_cards}
</div>
</section>
<footer>
<p>Every key on this page comes from <code>grafli/keymap.py</code>, the
table the app's <kbd>F1</kbd> help shows. The words for each key are on the
<a href="{SITE}/keybindings/">keybindings page</a>, the browser tab in
<a href="{SITE}/navigating/#show-a-board-live-in-a-browser-tab">Show a board
live in a browser tab</a>.</p>
</footer>
</main>
</body>
</html>
"""


def write_page(path: Path) -> Path:
    path.write_text(render_page(), encoding="utf-8")
    return path


def local_copy() -> Path:
    """The page written for this installed version, for the F1 help.

    Each call makes a new file with a name nobody else can claim first:
    on Linux the temp directory is shared, and a fixed name there could
    already be another account's file or a symlink."""
    fd, name = tempfile.mkstemp(prefix="grafli-at-a-glance-", suffix=".html",
                                dir=tempfile.gettempdir())
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(render_page())
    return Path(name)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DOCS_COPY
    print(write_page(out))
