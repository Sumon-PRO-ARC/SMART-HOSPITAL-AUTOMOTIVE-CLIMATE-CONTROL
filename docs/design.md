# Design and complexity analysis

This document covers the design decisions, the complexity of every module,
and the assumptions behind the simulation. The proposal it implements is
"Smart Hospital Automated Climate & Patient Comfort Control System".

## 1. Architecture

```
 Simulator (simulation.py)          one noisy reading per room per simulated minute
      │ submit()
      ▼
 CircularQueue  ──process()──►  ClimateController (controller.py)
                                   ├─ HashTable      room id → Room
                                   ├─ SlidingWindow  per room: rolling max/min/avg, trend
                                   ├─ SegmentTree ×3 temperature / humidity / CO2 by room order
                                   ├─ IndexedHeap    open alerts, most urgent on top
                                   ├─ AVLTree + Trie patient profiles, name search
                                   ├─ Graph          ducts: BFS / DFS / Dijkstra
                                   ├─ UnionFind      climate zones
                                   ├─ merge_sort     maintenance schedule
                                   └─ LinkedList + Stack  event log, undo
      ▲
 API (api.py: handle_api)  ◄── local web server (web.py) over HTTP
                          ◄── or, on the live site, Pyodide in a Web Worker (web/js/py-worker.js)
 Browser dashboard (web/): asks for /api/state every second
 Scenarios (scenarios.py), text console (cli.py)
```

* **Web layer.** `web.py` uses only `http.server`. One lock serialises every
  request and the background clock thread (which advances the simulation 1,
  5, 15 or 60 minutes per real second while running), so the controller is
  never used by two threads at once. The server binds to 127.0.0.1, refuses
  requests whose `Host` header is not this computer (protection against DNS
  rebinding), accepts changes only as JSON POSTs up to 16 KB (a page on
  another site cannot send those without the browser's permission check),
  serves files only from `web/` and `docs/benchmarks/`, and sends a strict
  Content-Security-Policy. The page builds every element with `textContent`,
  never HTML from the server.

* **One API, two hosts.** All request handling lives in `api.py`
  (`handle_api`), which imports nothing that needs a full computer. The local
  server calls it over HTTP. The live site on GitHub Pages cannot run a
  server, so `web/js/py-worker.js` loads Pyodide (CPython compiled to
  WebAssembly) in a Web Worker, copies the package's Python files into it
  (listed in `py/manifest.json` by `build_site.py`) and calls the same
  `handle_api` for every request; a one-second timer in the worker plays the
  role of the server's clock thread. The page decides which host it has by
  asking `/api/health`. A test checks that no module shipped to the browser
  imports server-only modules (`http`, `socket`, `webbrowser`, ...).

* **Simulated time.** The controller never reads the wall clock; the caller
  passes the simulation minute. Every run with the same seed gives the same
  output, so scenarios can be tested exactly.
* **One reading per room per minute.** The simulator enqueues 80 readings a
  minute for the demo hospital; the queue (capacity 4,096) is drained after
  each minute. A full queue refuses the reading and counts it as dropped
  instead of blocking the sensor.
* **From scratch.** Everything in `hospital_climate/ds/` is written for this
  project. `tests/test_guard.py` reads the syntax tree of every module there
  and fails if one imports `heapq`, `bisect`, `collections`, `queue`, `array`
  or `functools`, or uses a built-in `dict`, `set`, `sorted()` or
  `list.sort()`. Python lists are used only as plain arrays. The tests use the
  built-in tools as reference answers (oracles).

## 2. Module-by-module complexity

n = rooms, m = patients, a = open alerts, k = results returned, L = name length,
W = window size, V/E = graph nodes/ducts, t = maintenance tasks.

| Module | Structure | Operation | Time | Space |
|---|---|---|---|---|
| Sensor intake | Circular array queue | enqueue / dequeue | O(1) | O(capacity) |
| Room registry | Hash table, separate chaining, FNV-1a / SplitMix64 hashing, resize at load 0.75 | get / put / remove | O(1) average, O(n) worst | O(n) |
| Alerts | Indexed binary max-heap + hash table of positions | push / pop / update-key / remove | O(log a) | O(a) |
| | | peek / contains | O(1) | |
| Patient profiles | AVL tree | search / insert / delete | O(log m) | O(m) |
| | | IDs in a range | O(log m + k) | |
| Name search | Trie (children in the project's hash table) | insert / remove / exact | O(L) | O(total characters) |
| | | prefix search | O(L + visited subtree) | |
| Rolling statistics | Monotonic deques (max and min) + window deque + running sum | add reading | O(1) amortised | O(W) per room |
| | | max / min / average / trend | O(1) | |
| Layout | Graph, adjacency list | storage | — | O(V + E) |
| Fault spread | BFS (circular queue) | rooms within k ducts | O(V + E) | O(V) |
| Isolated wings | DFS (stack), iterative | connected components | O(V + E) | O(V) |
| Duct routing | Dijkstra with the indexed min-heap (decrease-key) | one or many sources | O((V + E) log V) | O(V) |
| Zones | Union-Find, path compression + union by rank | union / find / connected | O(α(n)) amortised | O(n) |
| Maintenance | Merge sort (stable) | schedule | O(t log t) | O(t) |
| | Quick sort (random pivot, 3-way) | for comparison | O(t log t) expected | O(log t) stack |
| Range queries | Segment tree (sum, count, min, max) | point update / range query | O(log n) | O(n) |
| Room-number → position | Binary search on the ordered rooms | lower bound | O(log n) | — |
| History | Singly linked list with tail pointer | append | O(1) | O(entries) |
| Undo | Array stack (latest 50 actions) | push / pop | O(1) amortised | O(50) |

### Per reading

Processing one reading costs: dequeue O(1) + registry lookup O(1) + window
O(1) + three segment-tree updates O(log n) + alert push/update/remove
O(log a). In total **O(log n + log a)** per reading.

## 3. Design decisions

**Alert priority without re-sorting.** An alert's score is

    priority(now) = weight(room type) × (1 + severity) + 2 × (now − created)

where severity is measured in "deviation units": 1 °C outside the
temperature range, 5 % outside the humidity range or 200 ppm over the CO₂
limit, plus 1 if the temperature rose by 1.5 °C or more within the sliding
window. Weights: ICU 100, neonatal ICU 95, operating theatre 90, isolation
80, ward 40, waiting area 10.

The aging term keeps a long-ignored waiting-room alert from starving behind a
stream of new ICU alerts. Because every open alert ages at the same rate,
comparing `base + 2(now − created)` for two alerts gives the same order as
comparing `base − 2·created`; the heap stores the second form, so aging never
requires touching the heap. A new reading for a room with an open alert
changes its severity through **update-key** (O(log a)); a reading back in
range removes the alert from the middle of the heap (O(log a)), which is why
the heap keeps a position index.

**Re-routing after faults.** Each room's supply is found by one multi-source
Dijkstra from every working AHU (all sources start at distance 0). When an
AHU or duct fails, the search is repeated with failed parts skipped. In the
simulation, a room's HVAC capacity is scaled by `normal route cost / current
route cost`, so air arriving the long way round cools less, and a room no
working AHU can reach gets no HVAC or ventilation at all.

**Zones and undo.** A setpoint change can target a whole Union-Find zone. It
is checked against every room's safe range first and either applied to all
rooms or refused, and it is undone as one action. Union-Find cannot split
sets, so "zone reset" builds a fresh structure.

**Comfort profiles.** A room's setpoint follows the average preferred
temperature of its patients, clamped half a degree inside the room type's
safe range. These automatic changes are logged but not put on the operator's
undo stack.

**Append-only log.** Undo never deletes history: the undo is appended as a
new log entry, so the linked list is a full audit trail.

## 4. Simulation model and assumptions

The physical model is deliberately simple (see `simulation.py`). Each minute:
the room's temperature leaks toward the outside air (2 % of the difference)
and gains heat from occupants and equipment; the HVAC corrects 25 % of the
setpoint error, limited to 0.35 °C per minute at full supply, doubled for 15
minutes after a technician is dispatched. Humidity and CO₂ are pulled toward
outdoor values by ventilation. Sensor noise is Gaussian with a fixed seed.

Safe ranges are **simulation defaults, not clinical guidance**:

| Room type | Temperature °C | Relative humidity % | CO₂ ppm | Weight |
|---|---|---|---|---|
| Intensive care (ICU) | 21–24 | 30–60 | ≤ 1000 | 100 |
| Neonatal ICU | 22–26 | 30–60 | ≤ 1000 | 95 |
| Operating theatre | 20–24 | 20–60 | ≤ 1000 | 90 |
| Isolation | 21–24 | 30–60 | ≤ 1000 | 80 |
| General ward | 21–24 | 30–60 | ≤ 1000 | 40 |
| Waiting area | 21–26 | 30–65 | ≤ 1000 | 10 |

* The operating-theatre row follows ANSI/ASHRAE/ASHE Standard 170 as
  reported by the ASHRAE Journal (October 2019): 20–24 °C and 20–60 % RH
  for operating rooms. Older editions (170-2008) used 21–24 °C and 30–60 %.
* The other rows are set in the same spirit for the simulation and were not
  checked line by line against the standard's table.
* 1000 ppm CO₂ is a common indoor-air-quality rule of thumb, not a
  regulatory limit.
* Room-type weights, deviation units, the aging rate and the physics
  constants are design choices for the simulation.

Before applying any of this to a real building, use the edition of Standard
170 (or the local code) that applies there.

### Sources

* ASHRAE Journal, October 2019, operating-room conditions under Standard 170:
  <https://nxtbook.com/nxtbooks/ashrae/ashraejournal_201910/index.php?startid=18>
* ASHRAE, Addendum d to Standard 170-2008 (lowered humidity limits):
  <https://www.ashrae.org/File%20Library/Technical%20Resources/Standards%20and%20Guidelines/Standards%20Addenda/170-2008/ad170_2008_d.pdf>

## 5. Testing

`python -m unittest discover -s tests -t .` runs:

* **Structure tests** (`tests/test_structures.py`): each structure against a
  reference built from Python's own tools (dict, sorted, heapq, a
  Bellman-Ford pass, a label array), with thousands of random operations and
  internal invariant checks (`is_valid()` for the heap and the AVL tree).
* **Guard** (`tests/test_guard.py`): the from-scratch rule above, plus a check
  that the guard itself catches violations.
* **Controller and scenario tests** (`tests/test_controller.py`): alert order,
  update-key, aging, rapid-rise warnings, patients, zones, undo, faults,
  range queries, and the four scenarios.
* **Web API** (`tests/test_web.py`): pages and headers, no files outside the
  web folder, every action, validation errors, scenarios, and the host,
  JSON-only and size checks.
* **Live site** (`tests/test_site.py`): `handle_api` without a server, the
  clock tick, the site build (every file the browser needs, nothing
  server-only) and that the build refuses to overwrite the project.
* **Benchmark harness** (`tests/test_benchmarks.py`): quick sizes run, both
  methods agree, and the charts are written.

## 6. Known limits

* The physics is a teaching model; the numbers show behaviour, not real
  HVAC performance.
* Sensors report once a minute, to 0.1 °C, in a fixed order; there is no network delay
  or sensor failure model (an unknown room ID is logged and ignored).
* Union-Find zones can only be merged or reset, not split.
* State lives in memory; nothing is saved between runs, and restarting the
  server starts a fresh hospital.
* The web server has no login: it is meant for one operator on their own
  computer. On the live site each visitor runs a private copy in their own
  browser, so there is nothing shared to protect.
* The live site needs an internet connection on first load (Pyodide comes
  from the jsDelivr CDN) and a browser with WebAssembly and Web Workers (any
  current desktop or mobile browser).
