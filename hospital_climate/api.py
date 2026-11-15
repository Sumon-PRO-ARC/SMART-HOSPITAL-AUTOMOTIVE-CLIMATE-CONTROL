"""The dashboard's API, independent of how it is served.

handle_api(app, method, path, query, body) answers one request with
(status, JSON-able object). Two hosts use it:

* the local web server (web.py), over HTTP;
* the live site on GitHub Pages, where the browser runs this same Python code
  with Pyodide (web/js/py-worker.js), because a static site cannot run a server.

So this module imports nothing that needs a full computer (no sockets, no
browser launching).
"""

import threading

from .controller import ControlError, clock_text
from .model import ROOM_TYPES
from .scenarios import SCENARIOS, make_demo

SPEEDS = (1, 5, 15, 60)  # simulated minutes per real second
NOT_FOUND = object()     # marker: no such endpoint


class BadRequest(Exception):
    pass


class App:
    """The live simulation plus everything the API needs to read or change it."""

    def __init__(self, seed=7):
        self.lock = threading.Lock()
        self.seed = seed
        self.running = False
        self.speed = 1
        self.last_report = None
        self.reset()

    def reset(self, sim=None, label="demo hospital"):
        self.sim = sim or make_demo(self.seed)
        if sim is None:
            self.sim.run(5)  # a few readings so the plan is not empty on first load
        self.ctl = self.sim.ctl
        self.label = label

    # ---- background clock ---------------------------------------------------

    def tick_clock(self):
        """Called once a real second by whoever hosts the app: advances the
        simulation while the clock is running."""
        if self.running:
            self.sim.run(self.speed)

    def clock_loop(self, stop):
        """Background-thread loop for the local web server."""
        while not stop.wait(1.0):
            with self.lock:
                self.tick_clock()

    # ---- read models ------------------------------------------------------

    def state(self):
        ctl, sim = self.ctl, self.sim
        rooms = []
        for r in ctl.all_rooms():
            x = r.latest
            alert = ctl.alerts.value_of(r.id) if r.id in ctl.alerts else None
            rooms.append({
                "id": r.id, "floor": r.floor, "wing": r.wing, "type": r.type.code,
                "temp": None if x is None else round(x.temperature, 1),
                "humidity": None if x is None else round(x.humidity),
                "co2": None if x is None else x.co2,
                "safe": {"temp": r.type.temp, "humidity": r.type.humidity, "co2": r.type.co2_max},
                "setpoint": r.setpoint, "supply": r.supply,
                "zone": ctl.zones.find(r.id) if ctl.zones.set_size(r.id) > 1 else None,
                "alert": None if alert is None else round(alert.priority_at(ctl.minute)),
                "patients": len(r.patients),
            })
        floors = []
        seen = []
        for r in ctl.all_rooms():
            if r.floor not in seen:
                seen.append(r.floor)
        for f in seen:
            t = ctl.floor_summary(f)
            floors.append({
                "floor": f, "ahu": "AHU-F%d" % f, "ahu_failed": ctl.graph.is_failed("AHU-F%d" % f),
                "avg": None if not t.count else round(t.average, 1),
                "max": None if not t.count else round(t.maximum, 1),
            })
        return {
            "label": self.label,
            "clock": sim.now(), "minute": ctl.minute,
            "running": self.running, "speed": self.speed, "speeds": SPEEDS,
            "outside": {"temp": round(sim.outside_temp, 1), "humidity": round(sim.outside_humidity)},
            "processed": ctl.processed, "dropped": ctl.dropped,
            "undo_depth": len(ctl.undo_stack), "undo_next": None if ctl.undo_stack.is_empty() else ctl.undo_stack.peek().description,
            "alerts": [self._alert(a) for a in ctl.open_alerts()[:12]],
            "alert_count": len(ctl.alerts),
            "unsupplied": ctl.unsupplied_rooms(),
            "rooms": rooms, "floors": floors,
            "types": [{"code": t.code, "label": t.label, "weight": t.weight} for t in ROOM_TYPES],
        }

    def _alert(self, a):
        r = self.ctl.room(a.room_id)
        return {"room": r.id, "type": r.type.code, "priority": round(a.priority_at(self.ctl.minute)),
                "since": clock_text(a.created), "reasons": a.reasons}

    def room(self, room_id):
        ctl = self.ctl
        r = ctl.room(room_id)
        path, cost = ([], None)
        if r.supply is not None:
            path, cost = ctl.route(r.supply, r.id)
        x = r.latest
        return {
            "id": r.id, "number": r.number, "floor": r.floor, "wing": r.wing,
            "type": r.type.code, "type_label": r.type.label,
            "safe": {"temp": r.type.temp, "humidity": r.type.humidity, "co2": r.type.co2_max},
            "setpoint": r.setpoint, "ventilation": r.ventilation,
            "latest": None if x is None else {"time": clock_text(x.minute), "temp": x.temperature,
                                              "humidity": x.humidity, "co2": x.co2},
            "window": r.window.values(), "rolling": ctl.rolling(r.id),
            "supply": r.supply, "route": path, "route_cost": cost,
            "zone": ctl.zone_members(r.id),
            "patients": [self._patient(ctl.find_patient(p)) for p in r.patients],
            "alert": self._alert(ctl.alerts.value_of(r.id)) if r.id in ctl.alerts else None,
            "extra_heat": self.sim.state[r.id].extra_heat,
        }

    @staticmethod
    def _patient(p):
        return {"id": p.id, "name": p.name, "room": p.room_id, "temp": p.temp, "humidity": p.humidity,
                "lighting": p.lighting, "noise": p.noise}

    def network(self):
        g = self.ctl.graph
        nodes = [{"id": n, "kind": g.kind(n), "failed": g.is_failed(n)} for n in g.nodes() if g.kind(n) != "room"]
        ducts = []
        for n in g.nodes():
            if g.kind(n) == "room":
                continue
            for e in g._adj[g._index[n]]:
                other = g._ids[e.to]
                if g.kind(other) != "room" and n < other:
                    ducts.append({"a": n, "b": other, "resistance": e.weight, "failed": e.failed})
        parts = [{"units": u, "rooms": r} for u, r in self.ctl.components()]
        return {"nodes": nodes, "ducts": ducts, "parts": parts, "unsupplied": self.ctl.unsupplied_rooms()}

    def tasks(self):
        return [{"id": t.id, "title": t.title, "room": t.room_id, "due": clock_text(t.deadline),
                 "overdue": t.deadline < self.ctl.minute, "priority": t.priority} for t in self.ctl.schedule()]

    def zones(self):
        return {"count": self.ctl.zones.set_count(),
                "groups": [{"root": root, "rooms": members} for root, members in self.ctl.zone_list()]}

    def history(self, n):
        return [{"time": clock_text(e.minute), "actor": e.actor, "text": e.text} for e in reversed(self.ctl.history(n))]

    def get(self, path, q):
        """Read-only API calls. q maps query names to strings. NOT_FOUND = unknown path."""
        def arg(name, default=None):
            return q.get(name, default)

        ctl = self.ctl
        if path == "/api/health":
            return {"ok": True}
        if path == "/api/state":
            return self.state()
        if path == "/api/room":
            return self.room(arg("id", ""))
        if path == "/api/range":
            s = ctl.range_summary(int(arg("first")), int(arg("last")), arg("metric", "temperature"))
            return {"count": s.count, "avg": s.average,
                    "min": s.minimum if s.count else None, "max": s.maximum if s.count else None}
        if path == "/api/patients":
            lo, hi = int(arg("lo", 0)), int(arg("hi", 10 ** 9))
            return [App._patient(p) for p in ctl.patients_in_range(lo, hi)]
        if path == "/api/patients/search":
            text = arg("q", "")
            return [App._patient(p) for p in ctl.search_names(text, 20)] if text.strip() else []
        if path == "/api/network":
            return self.network()
        if path == "/api/route":
            p, cost = ctl.route(arg("from", ""), arg("to", ""))
            return {"path": p, "cost": cost}
        if path == "/api/spread":
            hops = int(arg("hops", 2))
            if not 0 <= hops <= 10:
                raise BadRequest("hops must be 0-10")
            room = ctl.room(arg("room", "")).id
            return [{"room": r, "hops": h} for r, h in ctl.affected_by(room, hops)]
        if path == "/api/zones":
            return self.zones()
        if path == "/api/tasks":
            return self.tasks()
        if path == "/api/history":
            return self.history(min(200, int(arg("n", 50))))
        if path == "/api/stats":
            return {"hash_table": ctl.rooms.stats(), "alerts": len(ctl.alerts),
                    "patients": len(ctl.patients), "avl_height": ctl.patients.height(),
                    "trie_names": len(ctl.names), "zones": ctl.zones.set_count(),
                    "graph_nodes": ctl.graph.node_count(), "graph_ducts": ctl.graph.edge_count(),
                    "queue_capacity": ctl.intake.capacity, "log_entries": len(ctl.log),
                    "undo_depth": len(ctl.undo_stack)}
        if path == "/api/report":
            return self.last_report
        if path == "/api/scenarios":
            return [{"name": n, "doc": (f.__doc__ or "").strip()} for n, f in SCENARIOS.items()]
        return NOT_FOUND

    # ---- actions ----------------------------------------------------------

    def post(self, path, body):
        ctl, sim = self.ctl, self.sim
        if path == "/api/tick":
            minutes = _int(body, "minutes", 1, 24 * 60)
            sim.run(minutes)
            return {"message": "Ran %d minutes. Now %s." % (minutes, sim.now())}
        if path == "/api/clock":
            self.running = bool(body.get("running", self.running))
            speed = body.get("speed", self.speed)
            if speed not in SPEEDS:
                raise BadRequest("speed must be one of %s" % (SPEEDS,))
            self.speed = speed
            return {"message": ("Clock running at %d simulated minutes a second." % speed) if self.running else "Clock paused."}
        if path == "/api/weather":
            t = _num(body, "temp", -20, 55)
            h = _num(body, "humidity", 0, 100)
            sim.outside_temp, sim.outside_humidity = t, h
            return {"message": "Outside air set to %.1f C, %.0f %% RH." % (t, h)}
        if path == "/api/heat":
            r = ctl.room(_str(body, "room"))
            v = _num(body, "value", 0, 2)
            sim.state[r.id].extra_heat = v
            return {"message": ("Room %s: equipment heat %.2f C per minute." % (r.id, v)) if v else "Room %s: equipment heat off." % r.id}
        if path == "/api/serve":
            served = sim.dispatch(_int(body, "n", 1, 20))
            if not served:
                return {"message": "No open alerts."}
            return {"message": "Team sent to " + ", ".join("room %s" % a.room_id for a in served) + ".",
                    "served": [a.room_id for a in served]}
        if path == "/api/setpoint":
            room = _str(body, "room")
            ctl.set_setpoint(room, _num(body, "value", 10, 35), whole_zone=bool(body.get("zone")))
            return {"message": _cap(ctl.log.last().text) + "."}
        if path == "/api/ventilation":
            ctl.set_ventilation(_str(body, "room"), _int(body, "level", 1, 5))
            return {"message": _cap(ctl.log.last().text) + "."}
        if path == "/api/undo":
            action = ctl.undo()
            return {"message": "Undone: " + action.description + "."}
        if path == "/api/patients/add":
            p = ctl.add_patient(_int(body, "id", 1, 10 ** 9), _str(body, "name"), _str(body, "room"),
                                _num(body, "temp", 15, 30), _num(body, "humidity", 20, 70),
                                _int(body, "lighting", 1, 5), _int(body, "noise", 20, 80))
            return {"message": "Admitted %s to room %s." % (p.name, p.room_id)}
        if path == "/api/patients/discharge":
            p = ctl.discharge_patient(_int(body, "id", 1, 10 ** 9))
            return {"message": "Discharged %s." % p.name}
        if path == "/api/fail":
            if body.get("b"):
                ctl.fail_duct(_str(body, "a"), _str(body, "b"))
                return {"message": "Duct %s-%s marked failed." % (body["a"], body["b"])}
            unit = _str(body, "a")
            hops = _int(body, "hops", 1, 6) if "hops" in body else 2
            hit = ctl.fail_unit(unit, hops)
            return {"message": "%s failed: %d rooms within %d ducts. Supply re-routed where possible." % (unit, len(hit), hops),
                    "affected": [r for r, _ in hit]}
        if path == "/api/repair":
            if body.get("b"):
                ctl.repair_duct(_str(body, "a"), _str(body, "b"))
                return {"message": "Duct %s-%s repaired." % (body["a"], body["b"])}
            unit = _str(body, "a")
            if not ctl.graph.has_node(unit):
                raise ControlError("no unit " + unit)
            ctl.repair_unit(unit)
            return {"message": "%s repaired." % unit}
        if path == "/api/zones/merge":
            merged = ctl.merge_zone(_str(body, "a"), _str(body, "b"))
            return {"message": "Zones merged." if merged else "Those rooms are already in one zone."}
        if path == "/api/zones/type":
            n = ctl.zone_by_type(_str(body, "type"))
            return {"message": "Every %s room is now in one zone of %d rooms." % (body["type"].upper(), n)}
        if path == "/api/zones/reset":
            ctl.reset_zones()
            return {"message": "Every room is its own zone again."}
        if path == "/api/tasks/add":
            room = (body.get("room") or "").strip() or None
            t = ctl.add_task(_str(body, "title"), room, ctl.minute + _int(body, "in_minutes", 1, 7 * 24 * 60),
                             _int(body, "priority", 1, 5))
            return {"message": "Task #%d added." % t.id}
        if path == "/api/tasks/done":
            t = ctl.complete_task(_int(body, "id", 1, 10 ** 9))
            return {"message": "Task #%d done." % t.id}
        if path == "/api/scenario":
            name = _str(body, "name")
            if name not in SCENARIOS:
                raise BadRequest("unknown scenario " + name)
            report = SCENARIOS[name](seed=self.seed)
            self.running = False
            self.reset(report.sim, label="after scenario: " + name.replace("_", " "))
            self.last_report = {"name": name, "text": report.text()}
            return {"message": "Scenario finished; the dashboard now shows its final state.", "report": report.text()}
        if path == "/api/reset":
            self.running = False
            self.reset()
            self.last_report = None
            return {"message": "Started a fresh demo hospital."}
        return NOT_FOUND


def _cap(text):
    return text[:1].upper() + text[1:]


def _str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or not v.strip() or len(v) > 200:
        raise BadRequest("%s is required" % key)
    return v.strip()


def _num(body, key, lo, hi):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise BadRequest("%s must be a number" % key)
    if not lo <= v <= hi:
        raise BadRequest("%s must be between %g and %g" % (key, lo, hi))
    return float(v)


def _int(body, key, lo, hi):
    v = _num(body, key, lo, hi)
    if v != int(v):
        raise BadRequest("%s must be a whole number" % key)
    return int(v)



def handle_api(app, method, path, query=None, body=None):
    """One API request -> (HTTP status, JSON-able object). Thread-safe."""
    try:
        with app.lock:
            if method == "GET":
                out = app.get(path, query or {})
            elif method == "POST":
                if not isinstance(body, dict):
                    return 400, {"error": "Body must be a JSON object."}
                out = app.post(path, body)
            else:
                return 405, {"error": "Method not allowed."}
    except (ControlError, BadRequest) as e:
        return 400, {"error": _cap(str(e)) + "."}
    except (TypeError, ValueError):
        return 400, {"error": "Check the values you entered."}
    if out is NOT_FOUND:
        return 404, {"error": "No such API endpoint."}
    return 200, out
