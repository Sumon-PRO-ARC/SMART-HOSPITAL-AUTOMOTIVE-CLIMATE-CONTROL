"""Command-line interface.

  python -m hospital_climate                 web dashboard at http://127.0.0.1:8000 (opens the browser)
  python -m hospital_climate web --port N    the same, on another port; --no-browser to not open a tab
  python -m hospital_climate shell           text console instead of the web dashboard
  python -m hospital_climate scenario NAME   run normal | heatwave | hvac_failure | icu_flood | all
  python -m hospital_climate bench [--quick] run the naive-vs-efficient benchmarks
  python -m hospital_climate build-site      build the static live site for GitHub Pages into _site/
"""

import argparse
import cmd
import shlex
import sys

from .controller import ControlError, clock_text
from .scenarios import SCENARIOS, make_demo


class Console(cmd.Cmd):
    intro = (
        "Smart Hospital Climate Control - simulated 80-room hospital, clock %s.\n"
        "Type 'help' for commands, 'help <command>' for details, 'quit' to leave."
    )
    prompt = "climate> "

    def __init__(self, seed=7):
        super().__init__()
        self.sim = make_demo(seed)
        self.ctl = self.sim.ctl
        self.intro = self.intro % self.sim.now()

    # cmd.Cmd plumbing: report ControlError / bad input instead of crashing.
    def onecmd(self, line):
        try:
            return super().onecmd(line)
        except ControlError as e:
            print("  refused: %s" % e)
        except (ValueError, IndexError, KeyError) as e:
            print("  bad input (%s). Try 'help %s'." % (e, line.split()[0] if line.split() else ""))
        return False

    def emptyline(self):
        return False

    def _args(self, line, n_min, usage):
        args = shlex.split(line)
        if len(args) < n_min:
            raise ValueError("usage: " + usage)
        return args

    # ---- time and status ---------------------------------------------------

    def do_tick(self, line):
        """tick [minutes]  - run the simulation forward (default 10 minutes)."""
        minutes = int(line) if line.strip() else 10
        if not 1 <= minutes <= 24 * 60:
            raise ValueError("minutes must be 1-1440")
        self.sim.run(minutes)
        print("  now %s; %d readings processed so far; %d open alerts" % (
            self.sim.now(), self.ctl.processed, len(self.ctl.alerts)))

    def do_status(self, line):
        """status  - clock, outside air, alerts, floor averages (segment tree)."""
        print("  %s  outside %.1f C %.0f %% RH  plant power %.0f %%" % (
            self.sim.now(), self.sim.outside_temp, self.sim.outside_humidity, 100 * self.sim.hvac_factor))
        print("  readings processed %d, dropped %d, open alerts %d, undo depth %d" % (
            self.ctl.processed, self.ctl.dropped, len(self.ctl.alerts), len(self.ctl.undo_stack)))
        print("  floor   avg C   min C   max C   avg RH")
        for f in self._floors():
            t = self.ctl.floor_summary(f)
            h = self.ctl.floor_summary(f, "humidity")
            if t.count:
                print("  %5d   %5.1f   %5.1f   %5.1f   %6.1f" % (f, t.average, t.minimum, t.maximum, h.average))
            else:
                print("  %5d   (no readings yet - try 'tick')" % f)

    def _floors(self):
        floors = []
        for r in self.ctl.all_rooms():
            if not floors or floors[-1] != r.floor:
                floors.append(r.floor)
        return floors

    def do_room(self, line):
        """room ID  - one room: type, safe range, latest reading, rolling window, supply route."""
        r = self.ctl.room(self._args(line, 1, "room ID")[0])
        t = r.type
        size = self.ctl.zones.set_size(r.id)
        zone = "own zone" if size == 1 else "zone of %s (%d rooms)" % (self.ctl.zones.find(r.id), size)
        print("  room %s  %s, floor %d wing %s, %s" % (r.id, t.label, r.floor, r.wing, zone))
        print("  safe: %.0f-%.0f C, %.0f-%.0f %% RH, CO2 <= %d ppm; setpoint %.1f C, ventilation %d" % (
            t.temp[0], t.temp[1], t.humidity[0], t.humidity[1], t.co2_max, r.setpoint, r.ventilation))
        if r.latest:
            x = r.latest
            print("  latest (%s): %.1f C, %.0f %% RH, %d ppm" % (clock_text(x.minute), x.temperature, x.humidity, x.co2))
            s = self.ctl.rolling(r.id)
            print("  last %d readings: avg %.2f, min %.2f, max %.2f, change %+.2f C" % (
                s["n"], s["avg"], s["min"], s["max"], s["change"]))
        print("  supplied by %s%s" % (r.supply or "NOTHING", "" if r.supply is None else " (duct resistance %.1f)" % r.supply_cost))
        if r.patients:
            print("  patients: " + ", ".join("%d %s" % (p, self.ctl.find_patient(p).name) for p in r.patients))
        if r.id in self.ctl.alerts:
            a = self.ctl.alerts.value_of(r.id)
            print("  OPEN ALERT, priority %.0f: %s" % (a.priority_at(self.ctl.minute), "; ".join(a.reasons)))

    def do_range(self, line):
        """range FIRST LAST [temperature|humidity|co2]  - average/min/max over rooms FIRST..LAST (segment tree)."""
        a = self._args(line, 2, "range FIRST LAST [metric]")
        metric = a[2] if len(a) > 2 else "temperature"
        s = self.ctl.range_summary(a[0], a[1], metric)
        if not s.count:
            print("  no readings yet in that range")
        else:
            print("  rooms %s-%s %s: avg %.2f, min %.2f, max %.2f over %d rooms" % (
                a[0], a[1], metric, s.average, s.minimum, s.maximum, s.count))

    # ---- alerts --------------------------------------------------------------

    def do_alerts(self, line):
        """alerts [n]  - open alerts, most urgent first (default 10)."""
        n = int(line) if line.strip() else 10
        alerts = self.ctl.open_alerts()
        print("  %d open alerts" % len(alerts))
        for a in alerts[:n]:
            r = self.ctl.room(a.room_id)
            print("  %-4s %-4s priority %6.0f  open since %s  %s" % (
                r.id, r.type.code, a.priority_at(self.ctl.minute), clock_text(a.created), "; ".join(a.reasons)))

    def do_serve(self, line):
        """serve [n]  - dispatch the facilities team to the n most urgent alerts (heap pop)."""
        n = int(line) if line.strip() else 1
        served = self.sim.dispatch(n)
        if not served:
            print("  no open alerts")
        for a in served:
            print("  dispatched to room %s (%s): %s" % (a.room_id, self.ctl.room(a.room_id).type.code, a.reasons[0]))

    # ---- environment knobs ----------------------------------------------------

    def do_weather(self, line):
        """weather TEMP [HUMIDITY]  - set the outside air."""
        a = self._args(line, 1, "weather TEMP [HUMIDITY]")
        t = float(a[0])
        h = float(a[1]) if len(a) > 1 else self.sim.outside_humidity
        if not (-20 <= t <= 55 and 0 <= h <= 100):
            raise ValueError("temperature -20..55, humidity 0..100")
        self.sim.outside_temp, self.sim.outside_humidity = t, h
        print("  outside air now %.1f C, %.0f %% RH" % (t, h))

    def do_heat(self, line):
        """heat ROOM C_PER_MINUTE  - add equipment heat to a room (0 to stop)."""
        a = self._args(line, 2, "heat ROOM C_PER_MINUTE")
        r = self.ctl.room(a[0])
        v = float(a[1])
        if not 0 <= v <= 2:
            raise ValueError("0..2 C per minute")
        self.sim.state[r.id].extra_heat = v
        print("  room %s extra heat %.2f C/min" % (r.id, v))

    # ---- control and undo -------------------------------------------------------

    def do_setpoint(self, line):
        """setpoint ROOM C [zone]  - change a room's setpoint; add 'zone' for its whole zone."""
        a = self._args(line, 2, "setpoint ROOM C [zone]")
        self.ctl.set_setpoint(a[0], float(a[1]), whole_zone=len(a) > 2 and a[2] == "zone")
        print("  " + self.ctl.log.last().text)

    def do_vent(self, line):
        """vent ROOM LEVEL  - ventilation level 1-5."""
        a = self._args(line, 2, "vent ROOM LEVEL")
        self.ctl.set_ventilation(a[0], int(a[1]))
        print("  " + self.ctl.log.last().text)

    def do_undo(self, line):
        """undo  - revert the latest operator setpoint/ventilation command (stack pop)."""
        action = self.ctl.undo()
        print("  undone: " + action.description)

    def do_history(self, line):
        """history [n]  - the latest n entries of the event log (default 15)."""
        n = int(line) if line.strip() else 15
        for e in self.ctl.history(n):
            print("  %r" % e)

    # ---- patients -------------------------------------------------------------

    def do_patient(self, line):
        """patient ID | patient add ID "NAME" ROOM TEMP [HUMIDITY LIGHT NOISE] | patient discharge ID"""
        a = self._args(line, 1, "patient ID | patient add ... | patient discharge ID")
        if a[0] == "add":
            if len(a) < 5:
                raise ValueError('usage: patient add ID "NAME" ROOM TEMP [HUMIDITY LIGHT NOISE]')
            extra = [float(a[5]) if len(a) > 5 else 45.0, int(a[6]) if len(a) > 6 else 3, int(a[7]) if len(a) > 7 else 40]
            p = self.ctl.add_patient(int(a[1]), a[2], a[3], float(a[4]), *extra)
            print("  admitted %r; room %s setpoint now %.1f C" % (p, p.room_id, self.ctl.room(p.room_id).setpoint))
        elif a[0] == "discharge":
            p = self.ctl.discharge_patient(int(a[1]))
            print("  discharged %r" % p)
        else:
            p = self.ctl.find_patient(int(a[0]))
            if p is None:
                print("  no patient %s" % a[0])
            else:
                print("  %d %s, room %s: prefers %.1f C, %.0f %% RH, lighting %d/5, noise <= %d dB" % (
                    p.id, p.name, p.room_id, p.temp, p.humidity, p.lighting, p.noise))

    def do_patients(self, line):
        """patients [LO HI]  - patients by ID in ascending order (AVL range query)."""
        a = shlex.split(line)
        lo, hi = (int(a[0]), int(a[1])) if len(a) >= 2 else (0, 10 ** 9)
        found = self.ctl.patients_in_range(lo, hi)
        print("  %d patients (AVL height %d)" % (len(found), self.ctl.patients.height()))
        for p in found:
            print("  %5d  %-20s room %s" % (p.id, p.name, p.room_id))

    def do_search(self, line):
        """search PREFIX  - patient name autocomplete (trie)."""
        prefix = line.strip()
        if not prefix:
            raise ValueError("usage: search PREFIX")
        found = self.ctl.search_names(prefix)
        if not found:
            print("  no patient name starts with %r" % prefix)
        for p in found:
            print("  %-20s id %d, room %s" % (p.name, p.id, p.room_id))

    # ---- layout, faults, routing ---------------------------------------------

    def do_fail(self, line):
        """fail UNIT [HOPS] | fail duct A B  - break an AHU (BFS shows who is hit) or a duct."""
        a = self._args(line, 1, "fail UNIT [HOPS] | fail duct A B")
        if a[0] == "duct":
            if len(a) < 3:
                raise ValueError("usage: fail duct A B")
            self.ctl.fail_duct(a[1], a[2])
            print("  duct %s-%s failed; rooms without supply: %s" % (a[1], a[2], " ".join(self.ctl.unsupplied_rooms()) or "none"))
        else:
            hops = int(a[1]) if len(a) > 1 else 2
            hit = self.ctl.fail_unit(a[0], hops)
            print("  %s failed. %d rooms within %d ducts: %s" % (a[0], len(hit), hops, " ".join(r for r, _ in hit)))
            print("  rooms without supply now: %s" % (" ".join(self.ctl.unsupplied_rooms()) or "none (re-routed)"))

    def do_repair(self, line):
        """repair UNIT | repair duct A B"""
        a = self._args(line, 1, "repair UNIT | repair duct A B")
        if a[0] == "duct":
            if len(a) < 3:
                raise ValueError("usage: repair duct A B")
            self.ctl.repair_duct(a[1], a[2])
        else:
            if not self.ctl.graph.has_node(a[0]):
                raise ControlError("no unit " + a[0])
            self.ctl.repair_unit(a[0])
        print("  repaired; rooms without supply: %s" % (" ".join(self.ctl.unsupplied_rooms()) or "none"))

    def do_spread(self, line):
        """spread ROOM HOPS  - rooms within HOPS ducts of a contaminated room (BFS)."""
        a = self._args(line, 2, "spread ROOM HOPS")
        hit = self.ctl.affected_by(self.ctl.room(a[0]).id, int(a[1]))
        print("  %d rooms: %s" % (len(hit), " ".join("%s(%d)" % (r, h) for r, h in hit)))

    def do_parts(self, line):
        """parts  - connected parts of the working duct network (DFS)."""
        for units, rooms in self.ctl.components():
            print("  AHUs [%s], %d rooms%s" % (", ".join(units) or "none", len(rooms),
                                               "  <- NO AIR SUPPLY" if rooms and not units else ""))

    def do_route(self, line):
        """route UNIT ROOM  - lowest-resistance duct path (Dijkstra)."""
        a = self._args(line, 2, "route UNIT ROOM")
        path, cost = self.ctl.route(a[0], a[1])
        print("  unreachable" if not path else "  %s  (resistance %.1f)" % (" -> ".join(path), cost))

    # ---- zones ------------------------------------------------------------------

    def do_zone(self, line):
        """zone merge A B | zone type ICU|NICU|OT|ISO|WARD|WAIT | zone list | zone reset"""
        a = self._args(line, 1, "zone merge A B | zone type CODE | zone list | zone reset")
        if a[0] == "merge" and len(a) >= 3:
            merged = self.ctl.merge_zone(a[1], a[2])
            print("  merged" if merged else "  already in the same zone")
        elif a[0] == "type" and len(a) >= 2:
            print("  zone now has %d rooms" % self.ctl.zone_by_type(a[1]))
        elif a[0] == "list":
            zones = self.ctl.zone_list()
            print("  %d zones in total; multi-room zones:" % self.ctl.zones.set_count())
            for root, members in zones:
                print("  zone of %s: %s" % (root, " ".join(members)))
        elif a[0] == "reset":
            self.ctl.reset_zones()
            print("  every room is its own zone again")
        else:
            raise ValueError("usage: zone merge A B | zone type CODE | zone list | zone reset")

    # ---- maintenance ---------------------------------------------------------------

    def do_task(self, line):
        """task add "TITLE" ROOM|- IN_MINUTES PRIORITY | task done ID | task list"""
        a = self._args(line, 1, "task add ... | task done ID | task list")
        if a[0] == "add":
            if len(a) < 5:
                raise ValueError('usage: task add "TITLE" ROOM|- IN_MINUTES PRIORITY')
            room = None if a[2] == "-" else a[2]
            t = self.ctl.add_task(a[1], room, self.ctl.minute + int(a[3]), int(a[4]))
            print("  added %r" % t)
        elif a[0] == "done":
            print("  completed %r" % self.ctl.complete_task(int(a[1])))
        else:
            tasks = self.ctl.schedule()
            print("  %d open tasks, earliest deadline first:" % len(tasks))
            for t in tasks:
                print("  #%-3d due %s  P%d  %s%s" % (t.id, clock_text(t.deadline), t.priority, t.title,
                                                     "  (room %s)" % t.room_id if t.room_id else ""))

    def do_stats(self, line):
        """stats  - data structure sizes (hash table chains, AVL height, heap size, ...)."""
        print("  room registry hash table: " + ", ".join("%s %s" % (k.replace("_", " "), v)
                                                       for k, v in self.ctl.rooms.stats().items()))
        print("  alert heap: %d open; patient AVL: %d nodes, height %d, %d rebalances" % (
            len(self.ctl.alerts), len(self.ctl.patients), self.ctl.patients.height(), self.ctl.patients.rotations))
        print("  name trie: %d names; zones: %d sets; graph: %d nodes, %d ducts" % (
            len(self.ctl.names), self.ctl.zones.set_count(), self.ctl.graph.node_count(), self.ctl.graph.edge_count()))
        print("  intake queue: %d/%d; event log: %d entries; undo stack: %d" % (
            len(self.ctl.intake), self.ctl.intake.capacity, len(self.ctl.log), len(self.ctl.undo_stack)))

    def do_quit(self, line):
        """quit  - leave."""
        return True

    do_exit = do_quit
    do_EOF = do_quit


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m hospital_climate",
                                     description="Smart hospital climate and patient comfort control (simulation).")
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("scenario", help="run a scripted scenario")
    p.add_argument("name", choices=list(SCENARIOS) + ["all"])
    p.add_argument("--seed", type=int, default=7)
    b = sub.add_parser("bench", help="naive vs efficient benchmarks; writes docs/benchmarks/")
    b.add_argument("--quick", action="store_true", help="small sizes only (a few seconds)")
    w = sub.add_parser("web", help="the web dashboard (the default)")
    w.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1: this computer only)")
    w.add_argument("--port", type=int, default=8000)
    w.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    w.add_argument("--seed", type=int, default=7)
    s = sub.add_parser("shell", help="text console instead of the web dashboard")
    s.add_argument("--seed", type=int, default=7)
    b2 = sub.add_parser("build-site", help="build the static live site (GitHub Pages) into a folder")
    b2.add_argument("--out", default="_site")
    args = parser.parse_args(argv)

    if args.command == "scenario":
        names = list(SCENARIOS) if args.name == "all" else [args.name]
        for name in names:
            print(SCENARIOS[name](seed=args.seed).text())
            print()
        return 0
    if args.command == "bench":
        from benchmarks.run import main as bench_main
        return bench_main(quick=args.quick)
    if args.command == "shell":
        Console(seed=args.seed).cmdloop()
        return 0
    if args.command == "build-site":
        from .build_site import main as build_main
        return build_main(args.out)
    from .web import serve
    if args.command == "web":
        return serve(args.host, args.port, not args.no_browser, args.seed)
    return serve()


if __name__ == "__main__":
    sys.exit(main())
