"""Stub source for examples/showcase.grafli."""


def assess_danger(npc, threat):
    if threat.power / npc.power > 2.0:
        return "flee"
    if threat.count > npc.allies:
        return "guards"
    return "fight"
