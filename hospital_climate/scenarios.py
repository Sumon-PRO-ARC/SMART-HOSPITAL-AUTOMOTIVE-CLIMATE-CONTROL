"""Scripted scenarios from the proposal: normal day, heatwave, HVAC failure, ICU alert flood.

Each scenario builds a fresh 80-room hospital, runs the simulator and
returns a ScenarioResult (text report plus the numbers the tests check).
Run one with:  python -m hospital_climate scenario heatwave
"""

from .simulation import Simulator

# Fictional sample patients for the demo hospital.
SAMPLE_PATIENTS = [
    (1042, "Ayesha Rahman", "211", 22.0, 45, 2, 35),
    (1043, "Rahim Uddin", "212", 23.5, 50, 3, 40),
    (1007, "Nusrat Jahan", "301", 24.5, 50, 1, 30),
    (1101, "Rahima Khatun", "311", 22.5, 45, 3, 45),
    (1102, "Tanvir Hasan", "312", 21.5, 40, 4, 45),
    (1150, "Farhana Akter", "401", 22.0, 45, 2, 35),
    (1003, "Imran Hossain", "415", 23.0, 50, 3, 40),
    (1200, "Rafiq Islam", "102", 23.0, 50, 3, 45),
]


class ScenarioResult:
    def __init__(self, name):
        self.name = name
        self.lines = []
        self.data = {}
        self.sim = None  # the simulator in its final state (the web app keeps running it)

    def say(self, text=""):
        self.lines.append(text)

    def text(self):
        return "\n".join(self.lines)


def make_demo(seed=7):
    sim = Simulator(seed=seed)
    for p in SAMPLE_PATIENTS:
        sim.ctl.add_patient(*p)
    return sim


def _floor_table(sim, out):
    out.say("  floor   avg C   max C   avg RH   max CO2")
    for f in range(1, 5):
        t = sim.ctl.floor_summary(f, "temperature")
        h = sim.ctl.floor_summary(f, "humidity")
        c = sim.ctl.floor_summary(f, "co2")
        out.say("  %5d   %5.1f   %5.1f   %6.1f   %7d" % (f, t.average, t.maximum, h.average, c.maximum))


def _top_alerts(sim, out, n=5):
    alerts = sim.ctl.open_alerts()
    out.say("  open alerts: %d" % len(alerts))
    for a in alerts[:n]:
        r = sim.ctl.room(a.room_id)
        out.say("    room %s %-4s priority %6.0f  %s" % (r.id, r.type.code, a.priority_at(sim.minute), a.reasons[0]))


def normal_day(minutes=120, seed=7):
    out = ScenarioResult("normal")
    sim = make_demo(seed)
    sim.run(minutes)
    out.say("NORMAL DAY - %d minutes, outside %.0f C, %d rooms" % (minutes, sim.outside_temp, len(sim.ctl.order)))
    out.say("Readings processed through the circular queue: %d (dropped: %d)" % (sim.ctl.processed, sim.ctl.dropped))
    _floor_table(sim, out)
    _top_alerts(sim, out)
    out.data = {"open_alerts": len(sim.ctl.alerts), "processed": sim.ctl.processed}
    out.sim = sim
    return out


def heatwave(minutes=240, seed=7):
    """Outside air climbs from 30 C to 42 C in two hours; the plant cannot keep up everywhere."""
    out = ScenarioResult("heatwave")
    sim = make_demo(seed)
    sim.run(20)
    out.say("HEATWAVE - outside temperature rises 30 C -> 42 C over 2 hours.")
    out.say("The facilities team can handle 2 alerts every 10 minutes; each visit doubles that room's")
    out.say("cooling for 15 minutes. The max-heap decides who goes first.\n")
    dispatched = []
    for m in range(minutes):
        sim.outside_temp = min(42.0, 30.0 + 12.0 * m / 120.0)
        sim.step()
        if sim.minute % 10 == 0:
            dispatched += sim.dispatch(2)
        if sim.minute % 60 == 0:
            out.say("%s  outside %.1f C" % (sim.now(), sim.outside_temp))
            _floor_table(sim, out)
            _top_alerts(sim, out)
            out.say()
    order = [sim.ctl.room(a.room_id).type.code for a in dispatched]
    out.say("Dispatch order by room type (first 20): " + ", ".join(order[:20]))
    out.say("Rolling window for ICU room 211: %s" % _rolling_text(sim, "211"))
    out.data = {"dispatch_types": order, "open_alerts": len(sim.ctl.alerts)}
    out.sim = sim
    return out


def _rolling_text(sim, room_id):
    s = sim.ctl.rolling(room_id)
    return "last %d readings avg %.2f, min %.2f, max %.2f, change %+.2f C" % (
        s["n"], s["avg"], s["min"], s["max"], s["change"])


def hvac_failure(minutes=150, seed=7):
    """Floor 2's AHU fails, then three ducts break and cut the operating-theatre wing off."""
    out = ScenarioResult("hvac_failure")
    sim = make_demo(seed)
    ctl = sim.ctl
    sim.run(20)
    out.say("HVAC FAILURE\n")
    affected = ctl.fail_unit("AHU-F2", hops=2)
    out.say("%s  AHU-F2 fails. BFS: %d rooms within 2 ducts of it:" % (sim.now(), len(affected)))
    out.say("  " + " ".join(rid for rid, _ in affected))
    r = ctl.room("211")
    out.say("Dijkstra re-routes supply: ICU room 211 is now fed by %s (duct resistance %.1f)" % (r.supply, r.supply_cost))
    path, cost = ctl.route("AHU-F1", "211")
    out.say("  route AHU-F1 -> 211: %s  (cost %.1f)" % (" -> ".join(path), cost))
    sim.run(30)
    for a, b in (("C1A", "C2A"), ("C2A", "C3A"), ("C2A", "C2B")):
        ctl.fail_duct(a, b)
    comps = ctl.components()
    out.say("\n%s  ducts C1A-C2A, C2A-C3A and C2A-C2B break. DFS finds %d network parts:" % (sim.now(), len(comps)))
    for units, rooms in comps:
        out.say("  part with AHUs [%s] and %d rooms%s" % (
            ", ".join(units) or "none", len(rooms), "  <- NO AIR SUPPLY" if rooms and not units else ""))
    unsupplied = ctl.unsupplied_rooms()
    out.say("Rooms without supply: " + " ".join(unsupplied))
    ctl.add_task("Check OT sterility after outage", "201", sim.minute + 30, 5)
    ctl.add_task("Replace filter", "104", sim.minute + 600, 2)
    sim.run(minutes - 80)
    out.say("\n%s  after %d minutes without supply:" % (sim.now(), minutes - 80))
    _floor_table(sim, out)
    _top_alerts(sim, out)
    out.say("\nMaintenance schedule (merge sort: deadline, then priority):")
    for t in ctl.schedule():
        out.say("  %s" % t)
    ctl.repair_duct("C2A", "C2B")
    sim.run(30)
    out.say("\n%s  duct C2A-C2B repaired, 30 minutes later: rooms without supply: %d, open alerts: %d" % (
        sim.now(), len(ctl.unsupplied_rooms()), len(ctl.alerts)))
    out.data = {"affected": len(affected), "unsupplied": unsupplied, "parts": len(comps),
                "after_repair_unsupplied": len(ctl.unsupplied_rooms())}
    out.sim = sim
    return out


def icu_flood(seed=7):
    """Equipment heat hits ICU, neonatal, theatre, ward and waiting rooms at once."""
    out = ScenarioResult("icu_flood")
    sim = make_demo(seed)
    sim.run(10)
    hit = [r for r in sim.ctl.all_rooms() if r.type.code in ("ICU", "NICU", "OT", "WAIT")]
    hit += [sim.ctl.room(x) for x in ("411", "412", "413")]
    for r in hit:
        sim.state[r.id].extra_heat = 0.6
    out.say("ICU ALERT FLOOD - %d rooms overheat at once (equipment heat for 25 minutes)." % len(hit))
    out.say("One technician handles one alert every 2 minutes.\n")
    served = []
    for m in range(60):
        if m == 25:
            for r in hit:
                sim.state[r.id].extra_heat = 0.0
        sim.step()
        if m % 2 == 1:
            served += sim.dispatch(1, actor="technician")
        if m == 14:
            _top_alerts(sim, out, n=8)
    types = [sim.ctl.room(a.room_id).type.code for a in served]
    out.say("\nServed in this order:")
    for i in range(0, len(served), 10):
        out.say("  " + ", ".join("%s(%s)" % (a.room_id, sim.ctl.room(a.room_id).type.code) for a in served[i:i + 10]))
    out.data = {"served_types": types}
    out.sim = sim
    return out


SCENARIOS = {
    "normal": normal_day,
    "heatwave": heatwave,
    "hvac_failure": hvac_failure,
    "icu_flood": icu_flood,
}
