"""Builds a hospital: its rooms and the duct graph that connects them.

Every floor has one air handling unit (AHU-F<floor>) feeding two wing
corridors (C<floor>A, C<floor>B); each room hangs off its wing corridor.
Vertical risers link the same wing on neighbouring floors, so when a floor's
AHU fails, air can still be routed from the floor above or below - at a
higher duct resistance.

Duct resistance (edge weight, arbitrary units):
  AHU - corridor 2,  corridor A - corridor B 4,  riser 6,
  corridor - room 1 + 0.1 per room further down the corridor.
"""

from .ds import Graph
from . import model

# Room type of each wing, floor by floor; floors beyond this list are wards.
DEFAULT_PLAN = [
    (model.WAITING, model.WARD),       # floor 1
    (model.OT, model.ICU),             # floor 2
    (model.NEONATAL, model.WARD),      # floor 3
    (model.ISOLATION, model.WARD),     # floor 4
]
WINGS = ("A", "B")


class RoomSpec:
    __slots__ = ("id", "number", "floor", "wing", "type")

    def __init__(self, number, floor, wing, rtype):
        self.id = str(number)
        self.number = number
        self.floor = floor
        self.wing = wing
        self.type = rtype


def ahu_id(floor):
    return "AHU-F%d" % floor


def corridor_id(floor, wing):
    return "C%d%s" % (floor, wing)


def build_hospital(floors=4, rooms_per_wing=10, plan=None):
    """Returns (list of RoomSpec in room-number order, Graph)."""
    if floors < 1 or rooms_per_wing < 1:
        raise ValueError("need at least one floor and one room per wing")
    if rooms_per_wing * len(WINGS) > 99:
        raise ValueError("at most 49 rooms per wing (room numbers are floor*100 + 1..99)")
    plan = plan or DEFAULT_PLAN
    rooms = []
    g = Graph()
    for f in range(1, floors + 1):
        types = plan[f - 1] if f <= len(plan) else (model.WARD, model.WARD)
        g.add_node(ahu_id(f), "ahu")
        for w, wing in enumerate(WINGS):
            c = corridor_id(f, wing)
            g.add_node(c, "corridor")
            g.add_edge(ahu_id(f), c, 2)
            for k in range(rooms_per_wing):
                number = f * 100 + w * rooms_per_wing + k + 1
                spec = RoomSpec(number, f, wing, types[w])
                rooms.append(spec)
                g.add_node(spec.id, "room")
                g.add_edge(c, spec.id, round(1 + 0.1 * k, 1))
        g.add_edge(corridor_id(f, "A"), corridor_id(f, "B"), 4)
        if f > 1:
            for wing in WINGS:
                g.add_edge(corridor_id(f - 1, wing), corridor_id(f, wing), 6)
    return rooms, g
