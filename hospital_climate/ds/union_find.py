"""Union-Find (disjoint set union) for dynamic climate zones (proposal 5.6).

Each element points to a parent; the root of a tree names the set.
* Union by rank: the shorter tree is hung under the taller one.
* Path compression: ``find`` makes every node on the path point straight at
  the root.
Together they make find/union cost O(alpha(n)) amortised, where alpha is the
inverse Ackermann function (at most 4 for any realistic n): "near O(1)".

Elements can be any hashable key (room IDs); a hash table maps them to
array indices. Sets can only be merged, never split - for that, build a new
UnionFind (which is what the controller does when an operator resets zones).
"""

from .hash_table import HashTable


class UnionFind:
    def __init__(self):
        self._index = HashTable()  # element -> index
        self._elements = []        # index -> element
        self._parent = []
        self._rank = []
        self._size = []            # valid at roots: elements in the set
        self._sets = 0

    def __len__(self):
        return len(self._elements)

    def set_count(self):
        return self._sets

    def __contains__(self, element):
        return self._index.contains(element)

    def add(self, element):
        """Adds element as its own one-element set (ignored if already present)."""
        if self._index.contains(element):
            return
        i = len(self._elements)
        self._index.put(element, i)
        self._elements.append(element)
        self._parent.append(i)
        self._rank.append(0)
        self._size.append(1)
        self._sets += 1

    def _find(self, i):
        root = i
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[i] != root:  # path compression
            nxt = self._parent[i]
            self._parent[i] = root
            i = nxt
        return root

    def find(self, element):
        """The representative element of element's set."""
        return self._elements[self._find(self._index[element])]

    def union(self, a, b):
        """Merges the sets of a and b. Returns False if they were already one set."""
        ra = self._find(self._index[a])
        rb = self._find(self._index[b])
        if ra == rb:
            return False
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        self._size[ra] += self._size[rb]
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1
        self._sets -= 1
        return True

    def connected(self, a, b):
        return self._find(self._index[a]) == self._find(self._index[b])

    def set_size(self, element):
        return self._size[self._find(self._index[element])]

    def groups(self):
        """Every set as a list of elements, as a hash table root-element -> list. O(n alpha(n))."""
        out = HashTable()
        for i, element in enumerate(self._elements):
            root = self._elements[self._find(i)]
            members = out.get(root)
            if members is None:
                members = []
                out.put(root, members)
            members.append(element)
        return out
