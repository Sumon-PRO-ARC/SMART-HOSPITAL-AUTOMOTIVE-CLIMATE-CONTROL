"""Weighted undirected graph with BFS, DFS and Dijkstra (proposal 5.5).

Nodes are rooms, corridors and air handling units (AHUs); an edge is an
air duct, weighted by its airflow resistance. Storage is an adjacency list:
node i owns an array of its edges, so the whole graph takes O(V + E) space.

Nodes and edges can be marked failed (a broken AHU, a blocked duct). Every
search skips failed nodes and edges, which is how the simulation asks
"what is still connected / what is the best route now?".

* ``bfs_within(start, k)``      rooms within k duct hops of a unit   O(V + E)
* ``components()``              connected parts of the network (DFS) O(V + E)
* ``dijkstra(sources)``         lowest-resistance routes             O((V + E) log V)
"""

from .hash_table import HashTable
from .heap import IndexedHeap
from .stack import Stack
from .circular_queue import CircularQueue


class _Edge:
    __slots__ = ("to", "weight", "failed")

    def __init__(self, to, weight):
        self.to = to
        self.weight = weight
        self.failed = False


class Graph:
    def __init__(self):
        self._index = HashTable()  # node id -> index
        self._ids = []             # index -> node id
        self._kind = []            # index -> "room" / "corridor" / "ahu"
        self._adj = []             # index -> array of _Edge
        self._failed = []          # index -> bool
        self._edges = 0

    # ---- building ---------------------------------------------------------

    def add_node(self, node_id, kind):
        if self._index.contains(node_id):
            raise ValueError("duplicate node: " + repr(node_id))
        self._index.put(node_id, len(self._ids))
        self._ids.append(node_id)
        self._kind.append(kind)
        self._adj.append([])
        self._failed.append(False)

    def add_edge(self, a, b, weight):
        """Undirected duct between a and b with a non-negative resistance."""
        if weight < 0:
            raise ValueError("Dijkstra needs non-negative weights")
        i, j = self._index[a], self._index[b]
        self._adj[i].append(_Edge(j, weight))
        self._adj[j].append(_Edge(i, weight))
        self._edges += 1

    def node_count(self):
        return len(self._ids)

    def edge_count(self):
        return self._edges

    def has_node(self, node_id):
        return self._index.contains(node_id)

    def kind(self, node_id):
        return self._kind[self._index[node_id]]

    def nodes(self, kind=None):
        for i, node_id in enumerate(self._ids):
            if kind is None or self._kind[i] == kind:
                yield node_id

    def neighbours(self, node_id):
        """(neighbour id, weight) over working edges and nodes."""
        i = self._index[node_id]
        for e in self._adj[i]:
            if not e.failed and not self._failed[e.to]:
                yield self._ids[e.to], e.weight

    # ---- faults -----------------------------------------------------------

    def set_node_failed(self, node_id, failed=True):
        self._failed[self._index[node_id]] = failed

    def is_failed(self, node_id):
        return self._failed[self._index[node_id]]

    def set_edge_failed(self, a, b, failed=True):
        """Marks the duct a-b (both directions) failed or repaired."""
        i, j = self._index[a], self._index[b]
        found = False
        for x, y in ((i, j), (j, i)):
            for e in self._adj[x]:
                if e.to == y:
                    e.failed = failed
                    found = True
        if not found:
            raise KeyError((a, b))

    # ---- BFS --------------------------------------------------------------

    def bfs_within(self, start, max_hops, through_failed_start=True):
        """Every node within max_hops edges of start, as (id, hops) in BFS order.

        The start node may itself be failed (it is the faulty unit we are
        tracing from); other failed nodes block the search.
        """
        s = self._index[start]
        if self._failed[s] and not through_failed_start:
            return []
        hops = [-1] * len(self._ids)
        hops[s] = 0
        queue = CircularQueue(max(1, len(self._ids)))
        queue.enqueue(s)
        out = []
        while not queue.is_empty():
            i = queue.dequeue()
            out.append((self._ids[i], hops[i]))
            if hops[i] == max_hops:
                continue
            for e in self._adj[i]:
                if e.failed or self._failed[e.to] or hops[e.to] != -1:
                    continue
                hops[e.to] = hops[i] + 1
                queue.enqueue(e.to)
        return out

    # ---- DFS --------------------------------------------------------------

    def components(self):
        """Connected components of the working network, each a list of ids (iterative DFS)."""
        seen = [False] * len(self._ids)
        out = []
        for s in range(len(self._ids)):
            if seen[s] or self._failed[s]:
                continue
            comp = []
            stack = Stack()
            stack.push(s)
            seen[s] = True
            while not stack.is_empty():
                i = stack.pop()
                comp.append(self._ids[i])
                for e in self._adj[i]:
                    if not e.failed and not self._failed[e.to] and not seen[e.to]:
                        seen[e.to] = True
                        stack.push(e.to)
            out.append(comp)
        return out

    # ---- Dijkstra ---------------------------------------------------------

    def dijkstra(self, sources, target=None):
        """Lowest-resistance distance from the nearest of ``sources`` to every node.

        ``sources`` is one id or a list of ids (multi-source: "which working AHU
        can supply each room most cheaply"). Stops early once ``target`` is
        settled. Returns a ShortestPaths result.
        """
        if not isinstance(sources, list):
            sources = [sources]
        n = len(self._ids)
        dist = [float("inf")] * n
        prev = [-1] * n
        origin = [-1] * n
        heap = IndexedHeap(max_heap=False)
        for src in sources:
            s = self._index[src]
            if self._failed[s]:
                continue
            dist[s] = 0.0
            origin[s] = s
            heap.push_or_update(s, 0.0)
        t = self._index[target] if target is not None else -1
        settled = 0
        while not heap.is_empty():
            i, d, _ = heap.pop()
            settled += 1
            if i == t:
                break
            for e in self._adj[i]:
                if e.failed or self._failed[e.to]:
                    continue
                nd = d + e.weight
                if nd < dist[e.to]:
                    dist[e.to] = nd
                    prev[e.to] = i
                    origin[e.to] = origin[i]
                    heap.push_or_update(e.to, nd)  # decrease-key
        return ShortestPaths(self, dist, prev, origin, settled)


class ShortestPaths:
    def __init__(self, graph, dist, prev, origin, settled):
        self._g = graph
        self._dist = dist
        self._prev = prev
        self._origin = origin
        self.settled = settled  # nodes taken off the heap (work done)

    def distance(self, node_id):
        return self._dist[self._g._index[node_id]]

    def reachable(self, node_id):
        return self.distance(node_id) != float("inf")

    def source_of(self, node_id):
        """Which source the best route starts from (None if unreachable)."""
        o = self._origin[self._g._index[node_id]]
        return self._g._ids[o] if o >= 0 else None

    def path(self, node_id):
        """Node ids from the source to node_id, or [] if unreachable."""
        i = self._g._index[node_id]
        if self._dist[i] == float("inf"):
            return []
        rev = []
        while i != -1:
            rev.append(self._g._ids[i])
            i = self._prev[i]
        return rev[::-1]
