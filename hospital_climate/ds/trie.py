"""Trie for patient-name autocomplete and prefix search (proposal 4).

Names are stored lower-case, one character per edge. Each node's children
are kept in this project's own hash table (character -> child node). A node
that ends a name holds the IDs of every patient with that exact name, since
two patients can share a name.

insert / remove / exact lookup: O(L) for a name of length L.
Prefix search: O(L) to reach the prefix node, plus the size of the subtree
visited to collect up to ``limit`` matches (children are visited in
alphabetical order, so results come out sorted).
"""

from .hash_table import HashTable
from .sorting import merge_sort


def normalise(name):
    return " ".join(name.lower().split())


class _Node:
    __slots__ = ("children", "ids", "passing")

    def __init__(self):
        self.children = HashTable(4)
        self.ids = []      # patient IDs whose full name ends here
        self.passing = 0   # how many stored names pass through this node


class Trie:
    def __init__(self):
        self._root = _Node()
        self._names = 0

    def __len__(self):
        """Number of (name, id) pairs stored."""
        return self._names

    def insert(self, name, patient_id):
        name = normalise(name)
        if not name:
            raise ValueError("empty name")
        node = self._root
        node.passing += 1
        for ch in name:
            child = node.children.get(ch)
            if child is None:
                child = _Node()
                node.children.put(ch, child)
            node = child
            node.passing += 1
        node.ids.append(patient_id)
        self._names += 1

    def _walk(self, text):
        node = self._root
        for ch in text:
            node = node.children.get(ch)
            if node is None:
                return None
        return node

    def find_exact(self, name):
        node = self._walk(normalise(name))
        return list(node.ids) if node is not None else []

    def remove(self, name, patient_id):
        """Removes one (name, id) pair and prunes nodes no other name uses. O(L)."""
        name = normalise(name)
        node = self._walk(name)
        if node is None or patient_id not in node.ids:
            return False
        node.ids.remove(patient_id)
        node = self._root
        node.passing -= 1
        for ch in name:
            child = node.children.get(ch)
            child.passing -= 1
            if child.passing == 0:
                node.children.remove(ch)  # the rest of this branch goes with it
                break
            node = child
        self._names -= 1
        return True

    def count_prefix(self, prefix):
        """How many stored names start with prefix. O(L)."""
        node = self._walk(normalise(prefix))
        return node.passing if node is not None else 0

    def starts_with(self, prefix, limit=10):
        """Up to ``limit`` (name, [ids]) pairs whose name starts with prefix, alphabetical."""
        prefix = normalise(prefix)
        node = self._walk(prefix)
        out = []
        if node is not None:
            self._collect(node, prefix, out, limit)
        return out

    def _collect(self, node, text, out, limit):
        if len(out) >= limit:
            return
        if node.ids:
            out.append((text, list(node.ids)))
        for ch in merge_sort(list(node.children.keys())):
            if len(out) >= limit:
                return
            self._collect(node.children.get(ch), text + ch, out, limit)
