"""Array-based stack for "undo the last control action" (proposal 5.8).

The top of the stack is the end of the backing array, so push and pop are
O(1) amortised. An optional capacity keeps only the most recent actions:
when full, a push is refused, which the caller reports to the operator.
"""


class Stack:
    def __init__(self, capacity=None):
        self._items = []  # backing array; the top is the last element
        self._capacity = capacity

    def __len__(self):
        return len(self._items)

    def is_empty(self):
        return not self._items

    def is_full(self):
        return self._capacity is not None and len(self._items) >= self._capacity

    def push(self, item):
        """O(1) amortised. Returns False when a capacity is set and reached."""
        if self.is_full():
            return False
        self._items.append(item)
        return True

    def pop(self):
        if not self._items:
            raise IndexError("pop from an empty stack")
        return self._items.pop()

    def peek(self):
        if not self._items:
            raise IndexError("peek at an empty stack")
        return self._items[-1]

    def __iter__(self):
        """Top first."""
        for i in range(len(self._items) - 1, -1, -1):
            yield self._items[i]
