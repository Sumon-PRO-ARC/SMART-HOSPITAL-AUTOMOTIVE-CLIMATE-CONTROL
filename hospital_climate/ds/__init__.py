"""Data structures and algorithms, all written from scratch for this project.

No module in this package imports heapq, bisect, collections or queue, and
none uses a built-in dict or set as a data structure, or sorted() /
list.sort(); Python lists are used only as plain arrays. tests/test_guard.py
checks this on every test run.
"""

from .avl import AVLTree
from .circular_queue import CircularQueue
from .graph import Graph, ShortestPaths
from .hash_table import HashTable, hash_key
from .heap import IndexedHeap
from .linked_list import LinkedList
from .segment_tree import RangeSummary, SegmentTree
from .sliding_window import Deque, SlidingWindow
from .sorting import insertion_sort, merge_sort, quick_sort
from .stack import Stack
from .trie import Trie
from .union_find import UnionFind

__all__ = [
    "AVLTree", "CircularQueue", "Deque", "Graph", "HashTable", "IndexedHeap",
    "LinkedList", "RangeSummary", "SegmentTree", "ShortestPaths", "SlidingWindow",
    "Stack", "Trie", "UnionFind", "hash_key", "insertion_sort", "merge_sort", "quick_sort",
]
