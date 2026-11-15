"""The climate controller: every module of the proposal wired together.

| Job                          | Structure (ds/)                       |
|------------------------------|---------------------------------------|
| sensor intake                | CircularQueue                         |
| room registry                | HashTable  room id -> Room            |
| alerts, most urgent first    | IndexedHeap (max) with update-key     |
| patient comfort profiles     | AVLTree    patient id -> Patient      |
| patient name search          | Trie                                  |
| rolling max/min/average      | SlidingWindow (monotonic deques)      |
| building layout, faults      | Graph: BFS, DFS, Dijkstra             |
| climate zones                | UnionFind                             |
| maintenance schedule         | merge_sort                            |
| floor / room-range averages  | SegmentTree (one per metric)          |
| history and undo             | LinkedList log + Stack                |

The controller never sleeps or reads the wall clock: time is the simulation
minute passed in by the caller, so scenarios and tests are repeatable.
"""

from .ds import (
    AVLTree, CircularQueue, HashTable, IndexedHeap, LinkedList, SegmentTree, Stack, Trie,
    UnionFind, merge_sort,
)
from .model import Alert, Patient, Room, deviation


class ControlError(Exception):
    """A request the controller refuses (unknown room, value out of range, ...)."""


class LogEntry:
    __slots__ = ("minute", "actor", "text")

    def __init__(self, minute, actor, text):
        self.minute = minute
        self.actor = actor
        self.text = text

    def __repr__(self):
        return "[%s] %s: %s" % (clock_text(self.minute), self.actor, self.text)


class Action:
    """One undoable control command; a zone command changes several rooms at once."""
    __slots__ = ("kind", "changes", "description")

    def __init__(self, kind, changes, description):
        self.kind = kind            # "setpoint" or "ventilation"
        self.changes = changes      # list of (room_id, old value, new value)
        self.description = description


class Task:
    __slots__ = ("id", "title", "room_id", "deadline", "priority", "done")

    def __init__(self, tid, title, room_id, deadline, priority):
        self.id = tid
        self.title = title
        self.room_id = room_id
        self.deadline = deadline  # simulation minute
        self.priority = priority  # 1 (low) .. 5 (critical)
        self.done = False

    def __repr__(self):
        return "Task(#%d %s, due %s, P%d)" % (self.id, self.title, clock_text(self.deadline), self.priority)


def clock_text(minute):
    """Simulation minute -> 'D1 08:00' (minute 0 is 08:00 on day 1)."""
    total = 8 * 60 + minute
    day = total // (24 * 60) + 1
    total %= 24 * 60
    return "D%d %02d:%02d" % (day, total // 60, total % 60)


class ClimateController:
    UNDO_LIMIT = 50

    def __init__(self, room_specs, graph, window_size=12, queue_capacity=4096):
        self.minute = 0
        self.graph = graph
        self.rooms = HashTable()                     # room id -> Room
        self.order = []                              # index -> room id (room-number order)
        self.floor_ranges = HashTable()              # floor -> (first index, last index)
        for i, spec in enumerate(room_specs):
            if self.rooms.contains(spec.id):
                raise ControlError("duplicate room " + spec.id)
            if i and spec.number <= room_specs[i - 1].number:
                raise ControlError("rooms must be given in increasing number order")
            self.rooms.put(spec.id, Room(spec.id, spec.number, spec.floor, spec.wing, spec.type, i, window_size))
            self.order.append(spec.id)
            lo_hi = self.floor_ranges.get(spec.floor)
            self.floor_ranges.put(spec.floor, (i if lo_hi is None else lo_hi[0], i))
        n = len(self.order)
        if n == 0:
            raise ControlError("a hospital needs at least one room")
        self.temp_tree = SegmentTree(n)
        self.humidity_tree = SegmentTree(n)
        self.co2_tree = SegmentTree(n)

        self.intake = CircularQueue(queue_capacity)
        self.dropped = 0
        self.processed = 0
        self.alerts = IndexedHeap(max_heap=True)     # room id -> Alert
        self.patients = AVLTree()                    # patient id -> Patient
        self.names = Trie()                          # name -> patient ids
        self.zones = UnionFind()
        for room_id in self.order:
            self.zones.add(room_id)
        self.tasks = []                              # Task list; scheduled with merge_sort
        self._next_task = 1
        self.log = LinkedList()                      # append-only history
        self.undo_stack = Stack(capacity=self.UNDO_LIMIT)

        self.refresh_supply()

    # ---- helpers ------------------------------------------------------------

    def room(self, room_id):
        r = self.rooms.get(str(room_id))
        if r is None:
            raise ControlError("no room " + str(room_id))
        return r

    def all_rooms(self):
        for room_id in self.order:
            yield self.rooms[room_id]

    def _record(self, actor, text):
        self.log.append(LogEntry(self.minute, actor, text))

    def advance_to(self, minute):
        if minute < self.minute:
            raise ControlError("time cannot go backwards")
        self.minute = minute

    # ---- 5.1 sensor pipeline --------------------------------------------------

    def submit(self, reading):
        """A sensor pushes one reading. O(1). Returns False if the buffer was full."""
        if self.intake.enqueue(reading):
            return True
        self.dropped += 1
        return False

    def process(self, limit=None):
        """Handles queued readings in arrival order. Returns how many were handled."""
        done = 0
        while not self.intake.is_empty() and (limit is None or done < limit):
            self._apply(self.intake.dequeue())
            done += 1
        self.processed += done
        return done

    def _apply(self, reading):
        r = self.rooms.get(reading.room_id)
        if r is None:  # a sensor for a room we do not know: log it, do not crash
            self._record("sensor", "reading for unknown room %s ignored" % reading.room_id)
            return
        r.latest = reading
        r.window.add(reading.temperature)
        self.temp_tree.update(r.index, reading.temperature)
        self.humidity_tree.update(r.index, reading.humidity)
        self.co2_tree.update(r.index, reading.co2)
        self._evaluate(r, reading)

    # ---- 5.2 alerts -----------------------------------------------------------

    def _evaluate(self, r, reading):
        severity, reasons = deviation(r.type, reading, r.window)
        if severity <= 0:
            if r.id in self.alerts:
                self.alerts.remove(r.id)
                self._record("system", "alert cleared for room %s" % r.id)
            return
        base = r.type.weight * (1.0 + severity)
        if r.id in self.alerts:
            alert = self.alerts.value_of(r.id)
            alert.reasons, alert.severity, alert.base, alert.minute = reasons, severity, base, reading.minute
            self.alerts.update(r.id, alert.heap_key())  # update-key: O(log n)
        else:
            alert = Alert(r.id, reasons, severity, base, reading.minute, reading.minute)
            self.alerts.push(r.id, alert.heap_key(), alert)
            self._record("system", "alert raised for room %s (%s): %s" % (r.id, r.type.code, "; ".join(reasons)))

    def peek_alert(self):
        return None if self.alerts.is_empty() else self.alerts.peek()[2]

    def serve_alert(self, actor="operator"):
        """Takes the most urgent open alert off the heap and dispatches it. O(log n)."""
        if self.alerts.is_empty():
            return None
        _, _, alert = self.alerts.pop()
        self._record(actor, "dispatched to room %s, priority %.0f: %s" % (
            alert.room_id, alert.priority_at(self.minute), "; ".join(alert.reasons)))
        return alert

    def open_alerts(self):
        """Every open alert, most urgent first (sorted copy; the heap is not changed)."""
        alerts = [a for _, _, a in self.alerts.items()]
        return merge_sort(alerts, key=lambda a: (-a.heap_key(), a.created, self.room(a.room_id).number))

    # ---- 5.3 patients ---------------------------------------------------------

    def add_patient(self, pid, name, room_id, temp, humidity=45.0, lighting=3, noise=40):
        pid = int(pid)
        room = self.room(room_id)
        if pid in self.patients:
            raise ControlError("patient %d already exists" % pid)
        if not name.strip():
            raise ControlError("a patient needs a name")
        if not (15.0 <= temp <= 30.0 and 20.0 <= humidity <= 70.0 and 1 <= lighting <= 5 and 20 <= noise <= 80):
            raise ControlError("preference out of range (temp 15-30, humidity 20-70, lighting 1-5, noise 20-80)")
        p = Patient(pid, name.strip(), room.id, float(temp), float(humidity), int(lighting), int(noise))
        self.patients.insert(pid, p)
        self.names.insert(p.name, pid)
        room.patients.append(pid)
        self._record("admissions", "patient %d %s admitted to room %s" % (pid, p.name, room.id))
        self._apply_comfort(room)
        return p

    def discharge_patient(self, pid):
        p = self.patients.search(int(pid))
        if p is None:
            raise ControlError("no patient %s" % pid)
        self.patients.delete(p.id)
        self.names.remove(p.name, p.id)
        room = self.room(p.room_id)
        room.patients.remove(p.id)
        self._record("admissions", "patient %d %s discharged from room %s" % (p.id, p.name, room.id))
        self._apply_comfort(room)
        return p

    def _apply_comfort(self, room):
        """Room setpoint = average preference of its patients, kept inside the safe range."""
        if room.patients:
            total = 0.0
            for pid in room.patients:
                total += self.patients.search(pid).temp
            wanted = total / len(room.patients)
        else:
            wanted = room.type.comfort_setpoint()
        lo, hi = room.type.temp
        target = round(min(max(wanted, lo + 0.5), hi - 0.5), 1)
        if target != room.setpoint:
            self.set_setpoint(room.id, target, actor="comfort profile")

    def find_patient(self, pid):
        return self.patients.search(int(pid))

    def patients_in_range(self, lo, hi):
        return [p for _, p in self.patients.range(int(lo), int(hi))]

    def search_names(self, prefix, limit=10):
        out = []
        for name, ids in self.names.starts_with(prefix, limit):
            for pid in ids:
                out.append(self.patients.search(pid))
        return out

    # ---- 5.4 rolling statistics -------------------------------------------------

    def rolling(self, room_id):
        r = self.room(room_id)
        if len(r.window) == 0:
            return None
        w = r.window
        return {"n": len(w), "avg": w.average(), "min": w.minimum(), "max": w.maximum(), "change": w.change()}

    # ---- 5.5 layout, faults and routing ---------------------------------------

    def ahus(self):
        return list(self.graph.nodes("ahu"))

    def refresh_supply(self):
        """Multi-source Dijkstra from every working AHU: each room's cheapest supply route."""
        working = [a for a in self.ahus() if not self.graph.is_failed(a)]
        sp = self.graph.dijkstra(working) if working else None
        for r in self.all_rooms():
            if sp is not None and sp.reachable(r.id):
                r.supply, r.supply_cost = sp.source_of(r.id), sp.distance(r.id)
            else:
                r.supply, r.supply_cost = None, None
        return sp

    def route(self, source, room_id):
        """Lowest-resistance duct path from one unit to a room: (path, cost)."""
        self.room(room_id)
        if not self.graph.has_node(source):
            raise ControlError("no unit " + source)
        sp = self.graph.dijkstra(source, target=str(room_id))
        if not sp.reachable(str(room_id)):
            return [], None
        return sp.path(str(room_id)), sp.distance(str(room_id))

    def affected_by(self, node_id, hops):
        """Rooms within `hops` ducts of a faulty unit or contaminated room (BFS)."""
        if not self.graph.has_node(node_id):
            raise ControlError("no node " + node_id)
        return [(nid, h) for nid, h in self.graph.bfs_within(node_id, hops) if self.graph.kind(nid) == "room"]

    def components(self):
        """Connected parts of the working duct network (DFS), each with its AHUs and rooms."""
        out = []
        for comp in self.graph.components():
            units = [n for n in comp if self.graph.kind(n) == "ahu"]
            rooms = [n for n in comp if self.graph.kind(n) == "room"]
            out.append((units, rooms))
        return out

    def unsupplied_rooms(self):
        return [r.id for r in self.all_rooms() if r.supply is None]

    def fail_unit(self, ahu, hops=2):
        """An AHU breaks: trace who is hit (BFS), re-route supply (Dijkstra), book a repair."""
        if not self.graph.has_node(ahu) or self.graph.kind(ahu) != "ahu":
            raise ControlError("no air handling unit " + ahu)
        self.graph.set_node_failed(ahu, True)
        affected = self.affected_by(ahu, hops)
        self.refresh_supply()
        self._record("system", "%s FAILED: %d rooms within %d ducts" % (ahu, len(affected), hops))
        self.add_task("Repair " + ahu, None, self.minute + 120, 5, actor="system")
        return affected

    def repair_unit(self, ahu):
        self.graph.set_node_failed(ahu, False)
        self.refresh_supply()
        self._record("maintenance", ahu + " repaired")

    def fail_duct(self, a, b):
        try:
            self.graph.set_edge_failed(a, b, True)
        except KeyError:
            raise ControlError("no duct between %s and %s" % (a, b))
        self.refresh_supply()
        self._record("system", "duct %s-%s FAILED" % (a, b))
        self.add_task("Repair duct %s-%s" % (a, b), None, self.minute + 240, 4, actor="system")

    def repair_duct(self, a, b):
        try:
            self.graph.set_edge_failed(a, b, False)
        except KeyError:
            raise ControlError("no duct between %s and %s" % (a, b))
        self.refresh_supply()
        self._record("maintenance", "duct %s-%s repaired" % (a, b))

    # ---- 5.6 zones --------------------------------------------------------------

    def merge_zone(self, a, b):
        ra, rb = self.room(a), self.room(b)
        merged = self.zones.union(ra.id, rb.id)
        if merged:
            self._record("operator", "zone of %s merged with zone of %s" % (ra.id, rb.id))
        return merged

    def zone_by_type(self, type_code):
        """Puts every room of one type into a single zone. Returns the zone size."""
        rooms = [r for r in self.all_rooms() if r.type.code == type_code.upper()]
        if not rooms:
            raise ControlError("no rooms of type " + type_code)
        for r in rooms[1:]:
            self.zones.union(rooms[0].id, r.id)
        self._record("operator", "all %s rooms grouped into one zone" % type_code.upper())
        return self.zones.set_size(rooms[0].id)

    def zone_members(self, room_id):
        root = self.zones.find(self.room(room_id).id)
        return [rid for rid in self.order if self.zones.find(rid) == root]

    def zone_list(self):
        """[(representative room, [rooms])] for zones with more than one room."""
        out = []
        for root, members in self.zones.groups().items():
            if len(members) > 1:
                out.append((root, members))
        return merge_sort(out, key=lambda z: self.room(z[0]).number)

    def reset_zones(self):
        self.zones = UnionFind()
        for room_id in self.order:
            self.zones.add(room_id)
        self._record("operator", "zones reset: every room is its own zone")

    # ---- 5.8 control commands, history and undo ---------------------------------

    def set_setpoint(self, room_id, value, actor="operator", whole_zone=False):
        room = self.room(room_id)
        value = round(float(value), 1)
        targets = self.zone_members(room.id) if whole_zone else [room.id]
        changes = []
        for rid in targets:
            r = self.room(rid)
            lo, hi = r.type.temp
            if not lo <= value <= hi:
                raise ControlError("%.1f C is outside the safe range %.0f-%.0f C of room %s" % (value, lo, hi, rid))
            changes.append((rid, r.setpoint, value))
        for rid, _, new in changes:
            self.room(rid).setpoint = new
        where = ("zone of room %s (%d rooms)" % (room.id, len(changes))) if whole_zone else "room " + room.id
        text = "setpoint of %s set to %.1f C" % (where, value)
        self._push_undo(Action("setpoint", changes, text), actor)
        self._record(actor, text)

    def set_ventilation(self, room_id, level, actor="operator"):
        room = self.room(room_id)
        level = int(level)
        if not 1 <= level <= 5:
            raise ControlError("ventilation level must be 1-5")
        text = "ventilation of room %s set to %d" % (room.id, level)
        self._push_undo(Action("ventilation", [(room.id, room.ventilation, level)], text), actor)
        room.ventilation = level
        self._record(actor, text)

    def _push_undo(self, action, actor):
        if actor == "comfort profile":
            return  # automatic adjustments are logged but not operator-undoable
        if not self.undo_stack.push(action):
            # Full: drop the oldest by rebuilding without it (rare; keeps the latest 50).
            kept = list(self.undo_stack)[:-1]  # top first, minus the bottom
            self.undo_stack = Stack(capacity=self.UNDO_LIMIT)
            for a in reversed(kept):
                self.undo_stack.push(a)
            self.undo_stack.push(action)

    def undo(self, actor="operator"):
        """Reverts the latest operator command. O(rooms changed)."""
        if self.undo_stack.is_empty():
            raise ControlError("nothing to undo")
        action = self.undo_stack.pop()
        for rid, old, _ in action.changes:
            r = self.room(rid)
            if action.kind == "setpoint":
                r.setpoint = old
            else:
                r.ventilation = old
        self._record(actor, "UNDO: " + action.description)
        return action

    def history(self, n=20):
        return self.log.last_n(n)

    # ---- maintenance (sorting) -------------------------------------------------

    def add_task(self, title, room_id, deadline, priority, actor="operator"):
        if room_id is not None:
            room_id = self.room(room_id).id
        priority = int(priority)
        if not 1 <= priority <= 5:
            raise ControlError("priority must be 1-5")
        if not title.strip():
            raise ControlError("a task needs a title")
        t = Task(self._next_task, title.strip(), room_id, int(deadline), priority)
        self._next_task += 1
        self.tasks.append(t)
        self._record(actor, "task #%d added: %s" % (t.id, t.title))
        return t

    def complete_task(self, tid, actor="maintenance"):
        for t in self.tasks:
            if t.id == int(tid) and not t.done:
                t.done = True
                self._record(actor, "task #%d done: %s" % (t.id, t.title))
                return t
        raise ControlError("no open task #%s" % tid)

    def schedule(self):
        """Open tasks: earliest deadline first, then highest priority, then oldest (stable merge sort)."""
        open_tasks = [t for t in self.tasks if not t.done]
        return merge_sort(open_tasks, key=lambda t: (t.deadline, -t.priority, t.id))

    # ---- 5.7 range queries ------------------------------------------------------

    def _tree(self, metric):
        trees = {"temperature": self.temp_tree, "humidity": self.humidity_tree, "co2": self.co2_tree}
        if metric not in trees:
            raise ControlError("metric must be temperature, humidity or co2")
        return trees[metric]

    def floor_summary(self, floor, metric="temperature"):
        lo_hi = self.floor_ranges.get(int(floor))
        if lo_hi is None:
            raise ControlError("no floor %s" % floor)
        return self._tree(metric).query(lo_hi[0], lo_hi[1])

    def range_summary(self, first_number, last_number, metric="temperature"):
        """Summary over every room whose number is between the two, inclusive. O(log n)."""
        lo = self._lower_bound(int(first_number))
        hi = self._lower_bound(int(last_number) + 1) - 1
        if lo > hi:
            raise ControlError("no rooms numbered %s to %s" % (first_number, last_number))
        return self._tree(metric).query(lo, hi)

    def _lower_bound(self, number):
        """First index whose room number is >= number (binary search on the ordered rooms)."""
        lo, hi = 0, len(self.order)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.rooms[self.order[mid]].number < number:
                lo = mid + 1
            else:
                hi = mid
        return lo
