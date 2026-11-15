"""Segment tree for range queries over room readings (proposal 5.7).

Rooms are laid out in a fixed order (floor by floor, then room number), so
"floor 3" or "rooms 301 to 320" is a contiguous index range. Each tree node
summarises its range with (sum, count, min, max); a range query combines
O(log n) nodes and a point update rewrites O(log n) nodes.

Positions with no reading yet hold an empty summary (count 0), so averages
and extremes are taken over the rooms that have reported.

This is the iterative, bottom-up form: leaves sit at [size, 2*size) of the
array and node i summarises children 2i and 2i+1.
"""

_INF = float("inf")
_EMPTY = (0.0, 0, _INF, -_INF)  # sum, count, min, max


def _combine(a, b):
    return (
        a[0] + b[0],
        a[1] + b[1],
        a[2] if a[2] < b[2] else b[2],
        a[3] if a[3] > b[3] else b[3],
    )


class RangeSummary:
    __slots__ = ("total", "count", "minimum", "maximum")

    def __init__(self, s):
        self.total, self.count, self.minimum, self.maximum = s

    @property
    def average(self):
        return self.total / self.count if self.count else None

    def __repr__(self):
        if not self.count:
            return "RangeSummary(empty)"
        return "RangeSummary(avg=%.2f, min=%.2f, max=%.2f, n=%d)" % (
            self.average, self.minimum, self.maximum, self.count)


class SegmentTree:
    def __init__(self, n, values=None):
        if n < 1:
            raise ValueError("n must be at least 1")
        self.n = n
        size = 1
        while size < n:
            size *= 2
        self._size = size
        self._t = [_EMPTY] * (2 * size)
        if values is not None:  # O(n) build
            for i, v in enumerate(values):
                if v is not None:
                    self._t[size + i] = (float(v), 1, v, v)
            for i in range(size - 1, 0, -1):
                self._t[i] = _combine(self._t[2 * i], self._t[2 * i + 1])

    def update(self, i, value):
        """Sets position i to value (None clears it). O(log n)."""
        if not 0 <= i < self.n:
            raise IndexError(i)
        j = i + self._size
        self._t[j] = _EMPTY if value is None else (float(value), 1, value, value)
        j //= 2
        while j >= 1:
            self._t[j] = _combine(self._t[2 * j], self._t[2 * j + 1])
            j //= 2

    def get(self, i):
        s = self._t[i + self._size]
        return s[2] if s[1] else None

    def query(self, lo, hi):
        """Summary of positions lo..hi inclusive. O(log n)."""
        if lo < 0 or hi >= self.n or lo > hi:
            raise IndexError((lo, hi))
        left = _EMPTY
        right = _EMPTY
        l = lo + self._size
        r = hi + self._size + 1
        while l < r:
            if l & 1:
                left = _combine(left, self._t[l])
                l += 1
            if r & 1:
                r -= 1
                right = _combine(self._t[r], right)
            l //= 2
            r //= 2
        return RangeSummary(_combine(left, right))
