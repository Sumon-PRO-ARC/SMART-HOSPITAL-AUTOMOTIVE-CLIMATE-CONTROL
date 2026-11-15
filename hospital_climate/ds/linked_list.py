"""Singly linked list used as the append-only event history log (proposal 5.8).

A tail pointer makes append O(1). Entries are never removed: an undo is
itself appended as a new entry, so the log is a complete audit trail.
"""


class _Node:
    __slots__ = ("value", "next")

    def __init__(self, value):
        self.value = value
        self.next = None


class LinkedList:
    def __init__(self):
        self._head = None
        self._tail = None
        self._size = 0

    def __len__(self):
        return self._size

    def append(self, value):
        """O(1) thanks to the tail pointer."""
        node = _Node(value)
        if self._tail is None:
            self._head = node
        else:
            self._tail.next = node
        self._tail = node
        self._size += 1

    def first(self):
        return None if self._head is None else self._head.value

    def last(self):
        return None if self._tail is None else self._tail.value

    def __iter__(self):
        """Oldest to newest. O(n)."""
        node = self._head
        while node is not None:
            yield node.value
            node = node.next

    def last_n(self, n):
        """The newest n entries, oldest of them first. One pass, O(size)."""
        skip = self._size - n
        out = []
        for i, value in enumerate(self):
            if i >= skip:
                out.append(value)
        return out
