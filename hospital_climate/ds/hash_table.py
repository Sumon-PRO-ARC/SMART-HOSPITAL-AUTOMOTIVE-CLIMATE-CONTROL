"""Hash table with separate chaining (proposal 5.3, room registry).

* Strings are hashed with 64-bit FNV-1a, integers with a 64-bit mixer
  (SplitMix64 finaliser), so the hash function is part of this code, not
  Python's built-in ``hash``. Tuples of strings/ints are combined field by field.
* Each bucket is a singly linked chain of entries; a collision just
  lengthens the chain.
* When the load factor (entries / buckets) passes 0.75 the bucket array
  doubles and every entry is re-inserted, keeping chains short.

Average cost of get/put/remove: O(1). Worst case (every key in one bucket):
O(n). ``stats()`` reports the longest chain so this can be checked.
"""

_FNV_OFFSET = 0xCBF29CE484222325
_FNV_PRIME = 0x100000001B3
_MASK64 = 0xFFFFFFFFFFFFFFFF


def _mix64(x):
    x &= _MASK64
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & _MASK64
    return x ^ (x >> 31)


def hash_key(key):
    """64-bit hash for str, int, bool and tuples of those."""
    if isinstance(key, str):
        h = _FNV_OFFSET
        for byte in key.encode("utf-8"):
            h ^= byte
            h = (h * _FNV_PRIME) & _MASK64
        return h
    if isinstance(key, int):  # bool is an int too
        return _mix64(key)
    if isinstance(key, tuple):
        h = _FNV_OFFSET
        for part in key:
            h = _mix64(h ^ hash_key(part))
        return h
    raise TypeError("unsupported key type: " + type(key).__name__)


class _Entry:
    __slots__ = ("key", "value", "next")

    def __init__(self, key, value, nxt):
        self.key = key
        self.value = value
        self.next = nxt


class HashTable:
    MAX_LOAD = 0.75

    def __init__(self, buckets=16):
        n = 1
        while n < buckets:
            n *= 2
        self._buckets = [None] * n  # power of two, so index = hash & (n - 1)
        self._size = 0

    def __len__(self):
        return self._size

    def _index(self, key, nbuckets):
        return hash_key(key) & (nbuckets - 1)

    def _find(self, key):
        entry = self._buckets[self._index(key, len(self._buckets))]
        while entry is not None:
            if entry.key == key:
                return entry
            entry = entry.next
        return None

    def put(self, key, value):
        """Inserts or replaces. O(1) average."""
        entry = self._find(key)
        if entry is not None:
            entry.value = value
            return
        i = self._index(key, len(self._buckets))
        self._buckets[i] = _Entry(key, value, self._buckets[i])
        self._size += 1
        if self._size > self.MAX_LOAD * len(self._buckets):
            self._resize(2 * len(self._buckets))

    def get(self, key, default=None):
        entry = self._find(key)
        return default if entry is None else entry.value

    def contains(self, key):
        return self._find(key) is not None

    def __contains__(self, key):
        return self._find(key) is not None

    def __getitem__(self, key):
        entry = self._find(key)
        if entry is None:
            raise KeyError(key)
        return entry.value

    def __setitem__(self, key, value):
        self.put(key, value)

    def remove(self, key):
        """Removes key and returns its value; KeyError if absent. O(1) average."""
        i = self._index(key, len(self._buckets))
        prev = None
        entry = self._buckets[i]
        while entry is not None:
            if entry.key == key:
                if prev is None:
                    self._buckets[i] = entry.next
                else:
                    prev.next = entry.next
                self._size -= 1
                return entry.value
            prev = entry
            entry = entry.next
        raise KeyError(key)

    def _resize(self, nbuckets):
        old = self._buckets
        self._buckets = [None] * nbuckets
        for head in old:
            entry = head
            while entry is not None:
                nxt = entry.next
                i = self._index(entry.key, nbuckets)
                entry.next = self._buckets[i]
                self._buckets[i] = entry
                entry = nxt

    def items(self):
        """Every (key, value) pair, in bucket order (not sorted)."""
        for head in self._buckets:
            entry = head
            while entry is not None:
                yield entry.key, entry.value
                entry = entry.next

    def keys(self):
        for key, _ in self.items():
            yield key

    def values(self):
        for _, value in self.items():
            yield value

    def __iter__(self):
        return self.keys()

    def load_factor(self):
        return self._size / len(self._buckets)

    def stats(self):
        """Buckets, entries, load factor and longest chain, to show collisions are handled."""
        longest = 0
        used = 0
        for head in self._buckets:
            length = 0
            entry = head
            while entry is not None:
                length += 1
                entry = entry.next
            if length:
                used += 1
            if length > longest:
                longest = length
        return {
            "buckets": len(self._buckets),
            "entries": self._size,
            "load_factor": round(self.load_factor(), 3),
            "used_buckets": used,
            "longest_chain": longest,
        }
