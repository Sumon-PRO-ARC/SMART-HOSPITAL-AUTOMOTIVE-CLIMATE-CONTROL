"""Indexed binary heap: priority queue with update-key (proposal 5.2).

The heap is an array where the children of slot i are 2i+1 and 2i+2.
Every item has a key (for example a room ID); a hash table maps each key
to its current slot, so an item's priority can be changed or the item
removed in O(log n) without searching the array - the "decrease-key"
operation the proposal asks for (here it works in both directions).

``IndexedHeap(max_heap=True)`` serves the largest priority first (alerts);
``IndexedHeap(max_heap=False)`` serves the smallest first (Dijkstra).
Ties are broken by insertion order: the earlier item comes out first.

push / pop / update / remove: O(log n). peek / contains: O(1).
"""

from .hash_table import HashTable


class _Item:
    __slots__ = ("key", "priority", "seq", "value")

    def __init__(self, key, priority, seq, value):
        self.key = key
        self.priority = priority
        self.seq = seq
        self.value = value


class IndexedHeap:
    def __init__(self, max_heap=True):
        self._a = []  # the heap array
        self._pos = HashTable()  # key -> slot in self._a
        self._max = max_heap
        self._seq = 0

    def __len__(self):
        return len(self._a)

    def is_empty(self):
        return not self._a

    def __contains__(self, key):
        return self._pos.contains(key)

    def _before(self, x, y):
        """True if item x must come out before item y."""
        if x.priority != y.priority:
            return x.priority > y.priority if self._max else x.priority < y.priority
        return x.seq < y.seq

    def _place(self, i, item):
        self._a[i] = item
        self._pos.put(item.key, i)

    def _sift_up(self, i):
        item = self._a[i]
        while i > 0:
            parent = (i - 1) // 2
            if not self._before(item, self._a[parent]):
                break
            self._place(i, self._a[parent])
            i = parent
        self._place(i, item)

    def _sift_down(self, i):
        n = len(self._a)
        item = self._a[i]
        while True:
            child = 2 * i + 1
            if child >= n:
                break
            right = child + 1
            if right < n and self._before(self._a[right], self._a[child]):
                child = right
            if not self._before(self._a[child], item):
                break
            self._place(i, self._a[child])
            i = child
        self._place(i, item)

    def push(self, key, priority, value=None):
        """Adds a new key. O(log n). ValueError if the key is already in the heap."""
        if self._pos.contains(key):
            raise ValueError("key already in heap: " + repr(key))
        self._a.append(None)
        self._place(len(self._a) - 1, _Item(key, priority, self._seq, value))
        self._seq += 1
        self._sift_up(len(self._a) - 1)

    def peek(self):
        """(key, priority, value) of the next item, without removing it."""
        if not self._a:
            raise IndexError("peek at an empty heap")
        top = self._a[0]
        return top.key, top.priority, top.value

    def pop(self):
        """Removes and returns (key, priority, value) of the next item. O(log n)."""
        if not self._a:
            raise IndexError("pop from an empty heap")
        return self._remove_at(0)

    def _remove_at(self, i):
        item = self._a[i]
        self._pos.remove(item.key)
        last = self._a.pop()
        if i < len(self._a):
            self._place(i, last)
            # The moved item may belong higher or lower than slot i.
            if i > 0 and self._before(last, self._a[(i - 1) // 2]):
                self._sift_up(i)
            else:
                self._sift_down(i)
        return item.key, item.priority, item.value

    def priority_of(self, key):
        return self._a[self._pos[key]].priority

    def value_of(self, key):
        return self._a[self._pos[key]].value

    def update(self, key, priority, value=None):
        """Changes the priority (and optionally the value) of an existing key. O(log n).

        The item keeps its original insertion order for tie-breaking.
        """
        i = self._pos[key]
        item = self._a[i]
        item.priority = priority
        if value is not None:
            item.value = value
        self._sift_up(i)
        self._sift_down(self._pos[key])

    def push_or_update(self, key, priority, value=None):
        if self._pos.contains(key):
            self.update(key, priority, value)
        else:
            self.push(key, priority, value)

    def remove(self, key):
        """Removes any key, not just the top. O(log n)."""
        return self._remove_at(self._pos[key])

    def items(self):
        """Every (key, priority, value) in heap-array order (not sorted)."""
        for item in self._a:
            yield item.key, item.priority, item.value

    def is_valid(self):
        """Checks the heap property and the position index (used by the tests)."""
        n = len(self._a)
        for i in range(n):
            if self._pos.get(self._a[i].key) != i:
                return False
            for c in (2 * i + 1, 2 * i + 2):
                if c < n and self._before(self._a[c], self._a[i]):
                    return False
        return len(self._pos) == n
