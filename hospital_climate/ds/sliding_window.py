"""Deque and monotonic-deque sliding window (proposal 5.4).

``Deque`` is a growable circular buffer with O(1) operations at both ends.

``SlidingWindow`` keeps the latest N readings of one room and answers
rolling max, min and average in O(1):

* a plain deque holds the window itself, plus a running sum for the average;
* a *decreasing* deque holds candidates for the maximum: when a new reading
  arrives, every older value that is not larger can never be the maximum
  again, so it is dropped from the back. The front is always the maximum.
* an *increasing* deque does the same for the minimum.

Each reading is pushed and popped at most once per deque, so the cost per
reading is O(1) amortised, against O(N) for re-scanning the window.
"""


class Deque:
    def __init__(self, capacity=8):
        self._slots = [None] * max(1, capacity)
        self._front = 0
        self._count = 0

    def __len__(self):
        return self._count

    def is_empty(self):
        return self._count == 0

    def _grow(self):
        old = self._slots
        self._slots = [None] * (2 * len(old))
        for i in range(self._count):
            self._slots[i] = old[(self._front + i) % len(old)]
        self._front = 0

    def push_back(self, item):
        if self._count == len(self._slots):
            self._grow()
        self._slots[(self._front + self._count) % len(self._slots)] = item
        self._count += 1

    def push_front(self, item):
        if self._count == len(self._slots):
            self._grow()
        self._front = (self._front - 1) % len(self._slots)
        self._slots[self._front] = item
        self._count += 1

    def pop_front(self):
        if self._count == 0:
            raise IndexError("pop from an empty deque")
        item = self._slots[self._front]
        self._slots[self._front] = None
        self._front = (self._front + 1) % len(self._slots)
        self._count -= 1
        return item

    def pop_back(self):
        if self._count == 0:
            raise IndexError("pop from an empty deque")
        i = (self._front + self._count - 1) % len(self._slots)
        item = self._slots[i]
        self._slots[i] = None
        self._count -= 1
        return item

    def front(self):
        if self._count == 0:
            raise IndexError("empty deque")
        return self._slots[self._front]

    def back(self):
        if self._count == 0:
            raise IndexError("empty deque")
        return self._slots[(self._front + self._count - 1) % len(self._slots)]

    def __iter__(self):
        for i in range(self._count):
            yield self._slots[(self._front + i) % len(self._slots)]


class SlidingWindow:
    def __init__(self, size):
        if size < 1:
            raise ValueError("window size must be at least 1")
        self.size = size
        self._values = Deque(size)  # (index, value), oldest first
        self._maxq = Deque()        # (index, value), values decreasing
        self._minq = Deque()        # (index, value), values increasing
        self._sum = 0.0
        self._next_index = 0

    def __len__(self):
        return len(self._values)

    def is_full(self):
        return len(self._values) == self.size

    def add(self, value):
        """Adds one reading, dropping the oldest when the window is full. O(1) amortised."""
        i = self._next_index
        self._next_index += 1

        self._values.push_back((i, value))
        self._sum += value
        if len(self._values) > self.size:
            _, old = self._values.pop_front()
            self._sum -= old

        while not self._maxq.is_empty() and self._maxq.back()[1] <= value:
            self._maxq.pop_back()
        self._maxq.push_back((i, value))
        while not self._minq.is_empty() and self._minq.back()[1] >= value:
            self._minq.pop_back()
        self._minq.push_back((i, value))

        oldest = i - self.size + 1  # first index still inside the window
        if self._maxq.front()[0] < oldest:
            self._maxq.pop_front()
        if self._minq.front()[0] < oldest:
            self._minq.pop_front()

    def maximum(self):
        return self._maxq.front()[1]

    def minimum(self):
        return self._minq.front()[1]

    def average(self):
        return self._sum / len(self._values)

    def oldest(self):
        return self._values.front()[1]

    def newest(self):
        return self._values.back()[1]

    def change(self):
        """Newest minus oldest reading in the window: the trend used for "rapid rise"."""
        return self.newest() - self.oldest()

    def values(self):
        return [v for _, v in self._values]
