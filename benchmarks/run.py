"""Naive vs efficient benchmarks (proposal sections 6 and 7).

Each benchmark runs the same workload two ways, checks that both give the
same answer, and records the time. Results go to docs/benchmarks/:
results.md (tables) and one SVG chart per benchmark (log-log axes).

    python -m hospital_climate bench            # full sizes, a few minutes
    python -m hospital_climate bench --quick    # small sizes, a few seconds

Timings depend on the machine; the shape of the curves (how time grows with
n) is the point. The naive versions are pure Python too, except the
"re-sort the list" baseline for alerts, which uses Python's built-in sort
(written in C) because that is exactly the naive approach the proposal
names; it makes the comparison harder for the heap, not easier.
"""

import math
import pathlib
import platform
import random
import time

from hospital_climate.ds import (
    AVLTree, Graph, HashTable, IndexedHeap, SegmentTree, SlidingWindow, Trie, UnionFind,
    insertion_sort, merge_sort, quick_sort,
)

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "benchmarks"


def same(a, b):
    """Equal, allowing float rounding differences (the methods add numbers in different orders)."""
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


def timed(fn):
    t0 = time.perf_counter()
    result = fn()
    return time.perf_counter() - t0, result


# ---- workloads ----------------------------------------------------------------

def bench_lookup(n, rng):
    """1,000 room lookups among n rooms: hash table vs scanning a list."""
    ids = ["R%06d" % i for i in range(n)]
    table = HashTable()
    rows = []
    for i, rid in enumerate(ids):
        table.put(rid, i)
        rows.append((rid, i))
    queries = [rng.choice(ids) for _ in range(1000)]

    def fast():
        return [table.get(q) for q in queries]

    def naive():
        out = []
        for q in queries:
            for rid, v in rows:
                if rid == q:
                    out.append(v)
                    break
        return out

    return fast, naive


def bench_alerts(n, rng):
    """n alerts arrive; one is served after every two arrivals; the rest are drained."""
    prios = [rng.random() * 1000 for _ in range(n)]

    def fast():
        h = IndexedHeap(max_heap=True)
        served = []
        for i, p in enumerate(prios):
            h.push(i, p)
            if i % 2:
                served.append(h.pop()[0])
        while not h.is_empty():
            served.append(h.pop()[0])
        return served

    def naive():  # keep a list and re-sort it before every serve
        pending = []
        served = []
        for i, p in enumerate(prios):
            pending.append((p, -i, i))
            if i % 2:
                pending = sorted(pending)
                served.append(pending.pop()[2])
        for item in sorted(pending, reverse=True):
            served.append(item[2])
        return served

    return fast, naive


def bench_patient_range(n, rng):
    """200 'patients with IDs between a and b' queries: AVL range vs scanning all patients."""
    pids = rng.sample(range(10 * n), n)
    tree = AVLTree()
    for pid in pids:
        tree.insert(pid, pid)
    queries = []
    for _ in range(200):
        a = rng.randrange(10 * n)
        queries.append((a, a + 50))  # narrow ranges: a few results each

    def fast():
        return [[k for k, _ in tree.range(a, b)] for a, b in queries]

    def naive():
        out = []
        for a, b in queries:
            hits = [p for p in pids if a <= p <= b]
            out.append(insertion_sort(hits))  # results must come back ordered, like the tree's
        return out

    return fast, naive


def bench_prefix(n, rng):
    """200 three-letter prefix searches over n names: trie vs checking every name."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    names = ["".join(rng.choice(letters) for _ in range(rng.randint(5, 12))) for _ in range(n)]
    trie = Trie()
    for i, name in enumerate(names):
        trie.insert(name, i)
    prefixes = ["".join(rng.choice(letters) for _ in range(3)) for _ in range(200)]

    def fast():
        return [trie.count_prefix(p) for p in prefixes]

    def naive():
        return [sum(1 for name in names if name.startswith(p)) for p in prefixes]

    return fast, naive


def bench_window(w, rng):
    """20,000 readings, rolling max/min/average over the last w: monotonic deque vs re-scanning."""
    readings = [round(rng.uniform(18, 30), 2) for _ in range(20000)]

    def fast():
        win = SlidingWindow(w)
        out = 0.0
        for x in readings:
            win.add(x)
            out += win.maximum() - win.minimum() + win.average()
        return out

    def naive():
        buf = []
        out = 0.0
        for x in readings:
            buf.append(x)
            if len(buf) > w:
                buf.pop(0)
            hi = lo = buf[0]
            total = 0.0
            for v in buf:
                if v > hi:
                    hi = v
                if v < lo:
                    lo = v
                total += v
            out += hi - lo + total / len(buf)
        return out

    return fast, naive


def bench_segment(n, rng):
    """2,000 mixed operations (half sensor updates, half range averages) over n rooms."""
    values = [round(rng.uniform(18, 30), 1) for _ in range(n)]
    ops = []
    for _ in range(2000):
        if rng.random() < 0.5:
            ops.append((0, rng.randrange(n), round(rng.uniform(18, 30), 1)))
        else:
            a = rng.randrange(n)
            ops.append((1, a, rng.randrange(a, n)))

    def fast():
        t = SegmentTree(n, values)
        out = []
        for kind, a, b in ops:
            if kind == 0:
                t.update(a, b)
            else:
                out.append(t.query(a, b).average)
        return out

    def naive():
        arr = list(values)
        out = []
        for kind, a, b in ops:
            if kind == 0:
                arr[a] = b
            else:
                total = 0.0
                for i in range(a, b + 1):
                    total += arr[i]
                out.append(total / (b - a + 1))
        return out

    return fast, naive


def _grid(n_side, rng):
    """A square grid of ducts with random resistances (n_side^2 nodes)."""
    g = Graph()
    edges = []
    for i in range(n_side * n_side):
        g.add_node(i, "room")
    for r in range(n_side):
        for c in range(n_side):
            i = r * n_side + c
            for j in ((i + 1) if c + 1 < n_side else None, (i + n_side) if r + 1 < n_side else None):
                if j is not None:
                    w = rng.randint(1, 9)
                    g.add_edge(i, j, w)
                    edges.append((i, j, w))
    return g, edges


def bench_dijkstra(v, rng):
    """Shortest routes from one AHU to every node: heap Dijkstra vs the O(V^2) array version."""
    side = int(math.isqrt(v))
    g, edges = _grid(side, rng)
    n = side * side
    adj = [[] for _ in range(n)]
    for a, b, w in edges:
        adj[a].append((b, w))
        adj[b].append((a, w))

    def fast():
        sp = g.dijkstra(0)
        return [sp.distance(i) for i in range(n)]

    def naive():
        dist = [float("inf")] * n
        done = [False] * n
        dist[0] = 0
        for _ in range(n):
            u, best = -1, float("inf")
            for i in range(n):  # linear scan for the closest unsettled node
                if not done[i] and dist[i] < best:
                    u, best = i, dist[i]
            if u == -1:
                break
            done[u] = True
            for b, w in adj[u]:
                if dist[u] + w < dist[b]:
                    dist[b] = dist[u] + w
        return dist

    return fast, naive


def bench_union(n, rng):
    """n random zone merges plus n 'same zone?' checks: union-find vs relabelling every room."""
    pairs = [(rng.randrange(n), rng.randrange(n)) for _ in range(n)]
    checks = [(rng.randrange(n), rng.randrange(n)) for _ in range(n)]

    def fast():
        uf = UnionFind()
        for i in range(n):
            uf.add(i)
        for a, b in pairs:
            uf.union(a, b)
        return [uf.connected(a, b) for a, b in checks]

    def naive():
        label = list(range(n))
        for a, b in pairs:
            la, lb = label[a], label[b]
            if la != lb:
                for i in range(n):  # relabel the whole zone: O(n) per merge
                    if label[i] == lb:
                        label[i] = la
        return [label[a] == label[b] for a, b in checks]

    return fast, naive


def bench_sort(n, rng):
    """Sorting n maintenance tasks by (deadline, -priority): merge sort vs insertion sort."""
    tasks = [(rng.randrange(10000), rng.randint(1, 5), i) for i in range(n)]
    key = lambda t: (t[0], -t[1], t[2])

    def fast():
        return merge_sort(tasks, key=key)

    def naive():
        return insertion_sort(tasks, key=key)

    return fast, naive


def bench_quick(n, rng):
    """Quick sort vs merge sort on the same tasks (both O(n log n))."""
    tasks = [(rng.randrange(10000), rng.randint(1, 5), i) for i in range(n)]
    key = lambda t: (t[0], -t[1], t[2])
    return (lambda: quick_sort(tasks, key=key)), (lambda: merge_sort(tasks, key=key))


# name, title, x label, function, sizes, naive cap, (fast label, naive label)
BENCHMARKS = [
    ("lookup", "Room lookup (1,000 queries)", "rooms", bench_lookup,
     [100, 1000, 10000, 100000], 100000, ("hash table", "linear search")),
    ("alerts", "Alert handling: serve the most urgent", "alerts", bench_alerts,
     [100, 1000, 5000, 20000], 20000, ("max-heap", "re-sort list each time")),
    ("patients", "Patients with IDs in a range (200 queries)", "patients", bench_patient_range,
     [100, 1000, 10000, 100000], 100000, ("AVL range query", "scan all + sort")),
    ("prefix", "Name prefix search (200 queries)", "names", bench_prefix,
     [100, 1000, 10000, 100000], 100000, ("trie", "check every name")),
    ("window", "Rolling max/min/avg over 20,000 readings", "window size", bench_window,
     [10, 60, 300, 1000], 1000, ("monotonic deque", "re-scan window")),
    ("segment", "Range averages with updates (2,000 ops)", "rooms", bench_segment,
     [100, 1000, 10000, 100000], 100000, ("segment tree", "loop over range")),
    ("dijkstra", "Duct routing from one AHU", "nodes", bench_dijkstra,
     [100, 900, 2500, 10000], 2500, ("Dijkstra + heap", "Dijkstra O(V^2)")),
    ("zones", "Zone merges and checks", "rooms", bench_union,
     [100, 1000, 5000, 20000], 5000, ("union-find", "relabel all rooms")),
    ("sorting", "Sorting maintenance tasks", "tasks", bench_sort,
     [100, 1000, 5000, 100000], 5000, ("merge sort", "insertion sort")),
    ("quicksort", "Quick sort vs merge sort", "tasks", bench_quick,
     [100, 1000, 10000, 100000], 100000, ("quick sort", "merge sort")),
]
QUICK_SIZES = 2  # --quick: only the first two sizes of each benchmark


def run_all(quick=False, log=print):
    results = []
    for name, title, xlabel, fn, sizes, naive_cap, labels in BENCHMARKS:
        rows = []
        for n in sizes[:QUICK_SIZES] if quick else sizes:
            rng = random.Random(n)
            fast, naive = fn(n, rng)
            t_fast, r_fast = timed(fast)
            t_naive = None
            if n <= naive_cap:
                t_naive, r_naive = timed(naive)
                if not same(r_fast, r_naive):
                    raise AssertionError("%s n=%d: the two methods disagree" % (name, n))
            rows.append((n, t_fast, t_naive))
            log("  %-10s n=%-7d %s %.4fs   %s %s" % (
                name, n, labels[0], t_fast, labels[1], "-" if t_naive is None else "%.4fs" % t_naive))
        results.append((name, title, xlabel, labels, rows))
    return results


# ---- output -------------------------------------------------------------------

def _fmt(t):
    if t is None:
        return "skipped (too slow)"
    return "%.2f ms" % (t * 1000) if t < 1 else "%.2f s" % t


def write_markdown(results, path):
    lines = [
        "# Benchmark results",
        "",
        "Generated by `python -m hospital_climate bench` on %s, Python %s." % (
            platform.platform(terse=True), platform.python_version()),
        "Each row is one run; both methods were checked to return the same answer.",
        "Times depend on the machine: compare the growth, not the absolute numbers.",
        "",
    ]
    for name, title, xlabel, labels, rows in results:
        lines += ["## %s" % title, "", "![%s](%s.svg)" % (title, name), "",
                  "| %s | %s | %s | speed-up |" % (xlabel, labels[0], labels[1]), "|---:|---:|---:|---:|"]
        for n, tf, tn in rows:
            speed = "%.1fx" % (tn / tf) if tn is not None and tf > 0 else ""
            lines.append("| %s | %s | %s | %s |" % ("{:,}".format(n), _fmt(tf), _fmt(tn), speed))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_svg(title, xlabel, labels, rows, path):
    """A small log-log line chart, written by hand (no plotting library)."""
    W, H, L, R, T, B = 640, 400, 72, 24, 48, 64
    pts = [(n, t) for n, tf, tn in rows for t in (tf, tn) if t is not None and t > 0]
    xs = [n for n, _ in pts]
    ys = [t for _, t in pts]
    x0, x1 = math.floor(math.log10(min(xs))), math.ceil(math.log10(max(xs)))
    y0, y1 = math.floor(math.log10(min(ys))), math.ceil(math.log10(max(ys)))
    x1, y1 = max(x1, x0 + 1), max(y1, y0 + 1)

    def px(n):
        return L + (math.log10(n) - x0) / (x1 - x0) * (W - L - R)

    def py(t):
        return H - B - (math.log10(t) - y0) / (y1 - y0) * (H - T - B)

    def ylabel(e):
        s = 10.0 ** e
        return ("%g s" % s) if s >= 1 else ("%g ms" % (s * 1000))

    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" font-family="Arial, Helvetica, sans-serif" '
           'font-size="12" role="img" aria-label="%s">' % (W, H, title),
           '<rect width="100%" height="100%" fill="#ffffff"/>',
           '<text x="%d" y="26" font-size="15" font-weight="bold" fill="#2e2a4f">%s</text>' % (L, title)]
    for e in range(x0, x1 + 1):
        x = px(10 ** e)
        out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#e4e1ef"/>' % (x, T, x, H - B))
        out.append('<text x="%.1f" y="%d" text-anchor="middle" fill="#5e5a78">%s</text>' % (x, H - B + 18, "{:,}".format(10 ** e)))
    for e in range(y0, y1 + 1):
        y = py(10 ** e)
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#e4e1ef"/>' % (L, y, W - R, y))
        out.append('<text x="%d" y="%.1f" text-anchor="end" fill="#5e5a78">%s</text>' % (L - 8, y + 4, ylabel(e)))
    out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#5e5a78"/>' % (L, H - B, W - R, H - B))
    out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#5e5a78"/>' % (L, T, L, H - B))
    out.append('<text x="%.1f" y="%d" text-anchor="middle" fill="#2e2a4f">%s (log scale)</text>' % ((L + W - R) / 2, H - 22, xlabel))
    out.append('<text transform="translate(18 %.1f) rotate(-90)" text-anchor="middle" fill="#2e2a4f">time (log scale)</text>' % ((T + H - B) / 2))
    series = [(labels[0], [(n, tf) for n, tf, _ in rows], "#5b3fa8", ""),
              (labels[1], [(n, tn) for n, _, tn in rows if tn is not None], "#b8233e", ' stroke-dasharray="6 4"')]
    for i, (label, data, colour, dash) in enumerate(series):
        data = [(n, t) for n, t in data if t and t > 0]
        if data:
            out.append('<polyline fill="none" stroke="%s" stroke-width="2.5"%s points="%s"/>' % (
                colour, dash, " ".join("%.1f,%.1f" % (px(n), py(t)) for n, t in data)))
            for n, t in data:
                out.append('<circle cx="%.1f" cy="%.1f" r="3.5" fill="%s"/>' % (px(n), py(t), colour))
        lx = L + 12 + i * 220
        out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="2.5"%s/>' % (lx, T + 8, lx + 24, T + 8, colour, dash))
        out.append('<text x="%d" y="%d" fill="#2e2a4f">%s</text>' % (lx + 30, T + 12, label))
    out.append("</svg>")
    path.write_text("\n".join(out), encoding="utf-8")


def main(quick=False):
    OUT.mkdir(parents=True, exist_ok=True)
    print("Running benchmarks (%s)..." % ("quick" if quick else "full sizes"))
    results = run_all(quick)
    write_markdown(results, OUT / "results.md")
    for name, title, xlabel, labels, rows in results:
        write_svg(title, xlabel, labels, rows, OUT / (name + ".svg"))
    print("Wrote %s and %d charts." % (OUT / "results.md", len(results)))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(quick="--quick" in sys.argv))
