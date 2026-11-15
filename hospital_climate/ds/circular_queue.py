"""Circular-array queue for the sensor event pipeline (proposal 5.1).

A fixed block of slots is reused in a ring: ``front`` points at the oldest
item, ``count`` says how many are stored. Nothing is ever shifted, so both
enqueue and dequeue are O(1). Space is O(capacity).
"""


class CircularQueue:
    def __init__(self, capacity):
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._slots = [None] * capacity  # used as a fixed-size array
        self._capacity = capacity
        self._front = 0
        self._count = 0

    @property
    def capacity(self):
        return self._capacity

    def __len__(self):
        return self._count

    def is_empty(self):
        return self._count == 0

    def is_full(self):
        return self._count == self._capacity

    def enqueue(self, item):
        """Adds item at the rear. O(1). Returns False (and stores nothing) when full."""
        if self._count == self._capacity:
            return False
        rear = (self._front + self._count) % self._capacity
        self._slots[rear] = item
        self._count += 1
        return True

    def dequeue(self):
        """Removes and returns the oldest item. O(1)."""
        if self._count == 0:
            raise IndexError("dequeue from an empty queue")
        item = self._slots[self._front]
        self._slots[self._front] = None  # let the reading be garbage-collected
        self._front = (self._front + 1) % self._capacity
        self._count -= 1
        return item

    def peek(self):
        if self._count == 0:
            raise IndexError("peek at an empty queue")
        return self._slots[self._front]

    def __iter__(self):
        """Front to rear, without removing anything."""
        for i in range(self._count):
            yield self._slots[(self._front + i) % self._capacity]
