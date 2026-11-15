"""AVL tree: a self-balancing binary search tree (proposal 5.3, patient profiles).

Every node stores the height of its subtree. After an insert or delete the
path back to the root is re-balanced with single or double rotations so the
two subtrees of any node differ in height by at most 1. The height stays
O(log n), so search, insert, delete and the start of a range query are all
O(log n); a range query costs O(log n + k) for k results.
"""


class _Node:
    __slots__ = ("key", "value", "left", "right", "height")

    def __init__(self, key, value):
        self.key = key
        self.value = value
        self.left = None
        self.right = None
        self.height = 1


def _h(node):
    return node.height if node is not None else 0


def _fix_height(node):
    node.height = 1 + max(_h(node.left), _h(node.right))


def _balance_factor(node):
    return _h(node.left) - _h(node.right)


def _rotate_right(y):
    x = y.left
    y.left = x.right
    x.right = y
    _fix_height(y)
    _fix_height(x)
    return x


def _rotate_left(x):
    y = x.right
    x.right = y.left
    y.left = x
    _fix_height(x)
    _fix_height(y)
    return y


def _rebalance(node):
    _fix_height(node)
    bf = _balance_factor(node)
    if bf > 1:  # left-heavy
        if _balance_factor(node.left) < 0:  # left-right case
            node.left = _rotate_left(node.left)
        return _rotate_right(node)
    if bf < -1:  # right-heavy
        if _balance_factor(node.right) > 0:  # right-left case
            node.right = _rotate_right(node.right)
        return _rotate_left(node)
    return node


class AVLTree:
    def __init__(self):
        self._root = None
        self._size = 0
        self.rotations = 0  # for the report: how much re-balancing happened

    def __len__(self):
        return self._size

    def height(self):
        return _h(self._root)

    def insert(self, key, value):
        """Inserts key, or replaces its value if present. Returns True if the key was new."""
        self._added = False
        self._root = self._insert(self._root, key, value)
        if self._added:
            self._size += 1
        return self._added

    def _insert(self, node, key, value):
        if node is None:
            self._added = True
            return _Node(key, value)
        if key < node.key:
            node.left = self._insert(node.left, key, value)
        elif key > node.key:
            node.right = self._insert(node.right, key, value)
        else:
            node.value = value
            return node
        return self._counted_rebalance(node)

    def _counted_rebalance(self, node):
        before = node
        after = _rebalance(node)
        if after is not before:
            self.rotations += 1
        return after

    def search(self, key, default=None):
        node = self._root
        while node is not None:
            if key < node.key:
                node = node.left
            elif key > node.key:
                node = node.right
            else:
                return node.value
        return default

    def __contains__(self, key):
        node = self._root
        while node is not None:
            if key == node.key:
                return True
            node = node.left if key < node.key else node.right
        return False

    def delete(self, key):
        """Removes key. Returns True if it was present."""
        self._removed = False
        self._root = self._delete(self._root, key)
        if self._removed:
            self._size -= 1
        return self._removed

    def _delete(self, node, key):
        if node is None:
            return None
        if key < node.key:
            node.left = self._delete(node.left, key)
        elif key > node.key:
            node.right = self._delete(node.right, key)
        else:
            self._removed = True
            if node.left is None:
                return node.right
            if node.right is None:
                return node.left
            # Two children: copy the in-order successor here, then delete it below.
            succ = node.right
            while succ.left is not None:
                succ = succ.left
            node.key, node.value = succ.key, succ.value
            node.right = self._delete_min(node.right)
        return self._counted_rebalance(node)

    def _delete_min(self, node):
        if node.left is None:
            return node.right
        node.left = self._delete_min(node.left)
        return self._counted_rebalance(node)

    def items(self):
        """(key, value) in ascending key order. Iterative in-order traversal, O(n)."""
        stack = []
        node = self._root
        while stack or node is not None:
            while node is not None:
                stack.append(node)
                node = node.left
            node = stack.pop()
            yield node.key, node.value
            node = node.right

    def range(self, lo, hi):
        """(key, value) with lo <= key <= hi, ascending. O(log n + k)."""
        out = []
        self._range(self._root, lo, hi, out)
        return out

    def _range(self, node, lo, hi, out):
        if node is None:
            return
        if lo < node.key:
            self._range(node.left, lo, hi, out)
        if lo <= node.key <= hi:
            out.append((node.key, node.value))
        if node.key < hi:
            self._range(node.right, lo, hi, out)

    def min_key(self):
        node = self._root
        if node is None:
            return None
        while node.left is not None:
            node = node.left
        return node.key

    def max_key(self):
        node = self._root
        if node is None:
            return None
        while node.right is not None:
            node = node.right
        return node.key

    def is_valid(self):
        """Checks ordering, stored heights and the AVL balance rule (used by the tests)."""
        def check(node, lo, hi):
            if node is None:
                return 0
            if (lo is not None and node.key <= lo) or (hi is not None and node.key >= hi):
                raise AssertionError("order broken at " + repr(node.key))
            lh = check(node.left, lo, node.key)
            rh = check(node.right, node.key, hi)
            if abs(lh - rh) > 1 or node.height != 1 + max(lh, rh):
                raise AssertionError("balance/height broken at " + repr(node.key))
            return node.height

        try:
            check(self._root, None, None)
            return True
        except AssertionError:
            return False
