"""Stub source for examples/showcase.grafli, so its @path:line refs
resolve and `grafli diagnose` can check them."""

FLEE_RATIO = 2.0


def power_of(*args):
    """An NPC's combat power."""
    raise NotImplementedError


def allies_near(*args):
    """Allies within shouting range."""
    raise NotImplementedError


def is_hostile(*args):
    """Whether a creature means harm."""
    raise NotImplementedError


def threat_level(*args):
    """A threat's danger, 0 to 1."""
    raise NotImplementedError


def nearest_exit(*args):
    """The closest way out."""
    raise NotImplementedError


def call_guards(*args):
    """Ring the town bell."""
    raise NotImplementedError


def morale(*args):
    """An NPC's current morale."""
    raise NotImplementedError


def memory_of(*args):
    """What an NPC remembers of a threat."""
    raise NotImplementedError


def remember(*args):
    """Store an encounter."""
    raise NotImplementedError


def forget_old(*args):
    """Drop stale memories."""
    raise NotImplementedError


def path_to(*args):
    """A walking path to a place."""
    raise NotImplementedError


def is_night(*args):
    """Whether it is dark out."""
    raise NotImplementedError


def light_level(*args):
    """How well an NPC can see."""
    raise NotImplementedError


def weapon_of(*args):
    """An NPC's best weapon."""
    raise NotImplementedError


def armor_of(*args):
    """An NPC's armor."""
    raise NotImplementedError



def assess_danger(npc, threat):
    if threat.power / npc.power > FLEE_RATIO:
        return "flee"
    if threat.count > npc.allies:
        return "guards"
    return "fight"
