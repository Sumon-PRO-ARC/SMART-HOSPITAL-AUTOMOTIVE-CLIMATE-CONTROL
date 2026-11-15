"""Unit tests for every hand-built structure.

Most tests run random operations against a simple, obviously-correct
reference built from Python's own tools (dict, sorted, heapq). The
references live only here; the structures themselves never use them.
"""

import heapq
import random
import unittest

from hospital_climate.ds import (
    AVLTree, CircularQueue, Deque, Graph, HashTable, IndexedHeap, LinkedList,
    SegmentTree, SlidingWindow, Stack, Trie, UnionFind, insertion_sort, merge_sort, quick_sort,
)


class CircularQueueTest(unittest.TestCase):
    def test_fifo_and_wraparound(self):
        q = CircularQueue(3)
        self.assertTrue(q.enqueue(1))
        self.assertTrue(q.enqueue(2))
        self.assertTrue(q.enqueue(3))
        self.assertFalse(q.enqueue(4))  # full: refused, nothing lost
        self.assertEqual(q.dequeue(), 1)
        self.assertTrue(q.enqueue(4))   # wraps around to slot 0
        self.assertEqual(list(q), [2, 3, 4])
        self.assertEqual([q.dequeue() for _ in range(3)], [2, 3, 4])
        self.assertTrue(q.is_empty())
        with self.assertRaises(IndexError):
            q.dequeue()

    def test_random_against_list(self):
        rng = random.Random(1)
        q, ref = CircularQueue(50), []
        for _ in range(5000):
            if rng.random() < 0.55:
                x = rng.random()
                self.assertEqual(q.enqueue(x), len(ref) < 50)
                if len(ref) < 50:
                    ref.append(x)
            elif ref:
                self.assertEqual(q.dequeue(), ref.pop(0))
            self.assertEqual(len(q), len(ref))


class StackAndListTest(unittest.TestCase):
    def test_stack_lifo_and_capacity(self):
        s = Stack(capacity=2)
        self.assertTrue(s.push("a"))
        self.assertTrue(s.push("b"))
        self.assertFalse(s.push("c"))
        self.assertEqual(list(s), ["b", "a"])
        self.assertEqual(s.pop(), "b")
        self.assertEqual(s.peek(), "a")
        s.pop()
        with self.assertRaises(IndexError):
            s.pop()

    def test_linked_list_append_and_tail(self):
        log = LinkedList()
        self.assertIsNone(log.last())
        for i in range(10):
            log.append(i)
        self.assertEqual(len(log), 10)
        self.assertEqual(list(log), list(range(10)))
        self.assertEqual(log.first(), 0)
        self.assertEqual(log.last(), 9)
        self.assertEqual(log.last_n(3), [7, 8, 9])
        self.assertEqual(log.last_n(50), list(range(10)))


class HashTableTest(unittest.TestCase):
    def test_random_against_dict(self):
        rng = random.Random(2)
        t, ref = HashTable(), {}
        keys = ["room-%d" % i for i in range(300)] + list(range(300)) + [("A", 3), ("B", 3)]
        for _ in range(20000):
            k = rng.choice(keys)
            op = rng.random()
            if op < 0.5:
                v = rng.random()
                t.put(k, v)
                ref[k] = v
            elif op < 0.75:
                self.assertEqual(t.get(k), ref.get(k))
                self.assertEqual(k in t, k in ref)
            elif k in ref:
                self.assertEqual(t.remove(k), ref.pop(k))
            else:
                with self.assertRaises(KeyError):
                    t.remove(k)
        self.assertEqual(len(t), len(ref))
        self.assertEqual(sorted(map(repr, t.items())), sorted(map(repr, ref.items())))
        self.assertLessEqual(t.load_factor(), HashTable.MAX_LOAD)

    def test_collisions_are_chained(self):
        t = HashTable(buckets=2)  # tiny table: collisions before the first resize
        t.put("a", 1)
        t.put("b", 2)
        t.put("c", 3)  # triggers a resize; all keys must survive
        self.assertEqual((t["a"], t["b"], t["c"]), (1, 2, 3))
        self.assertGreaterEqual(t.stats()["buckets"], 4)

    def test_long_chain_still_correct(self):
        t = HashTable()
        t._index = lambda key, n: 0  # force every key into one bucket
        for i in range(100):
            t.put(i, i * i)
        self.assertEqual(t.stats()["longest_chain"], 100)
        self.assertEqual(t.get(57), 57 * 57)
        t.remove(0)
        t.remove(99)
        self.assertEqual(len(t), 98)
        self.assertIsNone(t.get(0))


class HeapTest(unittest.TestCase):
    def test_max_heap_order_and_ties(self):
        h = IndexedHeap(max_heap=True)
        h.push("ward", 10)
        h.push("icu", 90)
        h.push("ot", 90)  # same priority as icu, pushed later
        h.push("wait", 1)
        self.assertEqual([h.pop()[0] for _ in range(4)], ["icu", "ot", "ward", "wait"])

    def test_update_and_remove(self):
        h = IndexedHeap(max_heap=True)
        for k, p in [("a", 5), ("b", 3), ("c", 8)]:
            h.push(k, p)
        h.update("b", 10)   # increase
        self.assertEqual(h.peek()[0], "b")
        h.update("b", 1)    # decrease
        self.assertEqual(h.peek()[0], "c")
        h.remove("c")
        self.assertNotIn("c", h)
        self.assertEqual(h.pop()[0], "a")
        with self.assertRaises(ValueError):
            h.push("b", 3)  # still present

    def test_random_against_heapq(self):
        rng = random.Random(3)
        h = IndexedHeap(max_heap=False)
        ref = {}
        for step in range(6000):
            op = rng.random()
            k = rng.randrange(200)
            if op < 0.4 and k not in ref:
                p = rng.randrange(1000)
                h.push(k, p)
                ref[k] = (p, step)
            elif op < 0.6 and k in ref:
                p = rng.randrange(1000)
                h.update(k, p)
                ref[k] = (p, ref[k][1])
            elif op < 0.7 and k in ref:
                h.remove(k)
                del ref[k]
            elif op < 1.0 and ref:
                best = heapq.nsmallest(1, ref.items(), key=lambda kv: kv[1])[0]
                key, prio, _ = h.pop()
                self.assertEqual((key, prio), (best[0], best[1][0]))
                del ref[key]
            if step % 500 == 0:
                self.assertTrue(h.is_valid())
        self.assertEqual(len(h), len(ref))


class AVLTest(unittest.TestCase):
    def test_sorted_inserts_stay_balanced(self):
        t = AVLTree()
        for i in range(1, 1024):  # the worst case for a plain BST
            t.insert(i, str(i))
        self.assertTrue(t.is_valid())
        self.assertEqual(t.height(), 10)  # perfectly balanced for 1023 keys
        self.assertEqual(t.range(100, 105), [(i, str(i)) for i in range(100, 106)])

    def test_random_against_dict(self):
        rng = random.Random(4)
        t, ref = AVLTree(), {}
        for step in range(8000):
            k = rng.randrange(1500)
            if rng.random() < 0.6:
                self.assertEqual(t.insert(k, step), k not in ref)
                ref[k] = step
            else:
                self.assertEqual(t.delete(k), k in ref)
                ref.pop(k, None)
            if step % 400 == 0:
                self.assertTrue(t.is_valid())
        self.assertEqual(list(t.items()), sorted(ref.items()))
        self.assertEqual(len(t), len(ref))
        lo, hi = 300, 700
        self.assertEqual(t.range(lo, hi), sorted((k, v) for k, v in ref.items() if lo <= k <= hi))
        self.assertEqual((t.min_key(), t.max_key()), (min(ref), max(ref)))
        for k in range(1500):
            self.assertEqual(t.search(k), ref.get(k))


class TrieTest(unittest.TestCase):
    def test_prefix_search_is_alphabetical(self):
        t = Trie()
        for pid, name in enumerate(["Rahim Uddin", "Rahima Khatun", "Rafiq Islam", "Nusrat Jahan", "rahim uddin"]):
            t.insert(name, pid)
        self.assertEqual(t.starts_with("rah"), [("rahim uddin", [0, 4]), ("rahima khatun", [1])])
        self.assertEqual(t.count_prefix("ra"), 4)
        self.assertEqual(t.starts_with("ra", limit=2), [("rafiq islam", [2]), ("rahim uddin", [0, 4])])
        self.assertEqual(t.starts_with("zz"), [])
        self.assertEqual(t.find_exact("  RAHIM   uddin "), [0, 4])

    def test_remove_prunes(self):
        t = Trie()
        t.insert("ana", 1)
        t.insert("anabel", 2)
        self.assertTrue(t.remove("anabel", 2))
        self.assertFalse(t.remove("anabel", 2))
        self.assertEqual(t.starts_with("ana"), [("ana", [1])])
        self.assertEqual(t.count_prefix("anab"), 0)
        self.assertEqual(len(t), 1)

    def test_random_against_scan(self):
        rng = random.Random(5)
        letters = "abc d"
        names = ["".join(rng.choice(letters) for _ in range(rng.randint(1, 6))).strip() or "a" for _ in range(400)]
        t = Trie()
        for i, n in enumerate(names):
            t.insert(n, i)
        for prefix in ["a", "ab", "c", "b d", "dd", "abc"]:
            expected = sorted({" ".join(n.split()) for n in names if " ".join(n.split()).startswith(prefix)})
            got = [name for name, _ in t.starts_with(prefix, limit=10_000)]
            self.assertEqual(got, expected)


class SlidingWindowTest(unittest.TestCase):
    def test_deque_both_ends(self):
        d = Deque(2)
        d.push_back(1)
        d.push_back(2)
        d.push_front(0)  # grows
        d.push_back(3)
        self.assertEqual(list(d), [0, 1, 2, 3])
        self.assertEqual((d.pop_front(), d.pop_back()), (0, 3))
        self.assertEqual((d.front(), d.back(), len(d)), (1, 2, 2))

    def test_random_against_rescan(self):
        rng = random.Random(6)
        for size in (1, 3, 10, 60):
            w = SlidingWindow(size)
            seen = []
            for _ in range(2000):
                x = round(rng.uniform(18, 30), 1)
                w.add(x)
                seen.append(x)
                win = seen[-size:]
                self.assertEqual(w.maximum(), max(win))
                self.assertEqual(w.minimum(), min(win))
                self.assertAlmostEqual(w.average(), sum(win) / len(win))
                self.assertEqual(w.values(), win)
                self.assertAlmostEqual(w.change(), win[-1] - win[0])


class GraphTest(unittest.TestCase):
    def make(self):
        #  AHU1 -1- C1 -2- R1
        #            |3
        #  AHU2 -1- C2 -1- R2
        g = Graph()
        for n, k in [("AHU1", "ahu"), ("AHU2", "ahu"), ("C1", "corridor"), ("C2", "corridor"),
                     ("R1", "room"), ("R2", "room")]:
            g.add_node(n, k)
        g.add_edge("AHU1", "C1", 1)
        g.add_edge("C1", "R1", 2)
        g.add_edge("C1", "C2", 3)
        g.add_edge("AHU2", "C2", 1)
        g.add_edge("C2", "R2", 1)
        return g

    def test_bfs_hops(self):
        g = self.make()
        got = dict(g.bfs_within("AHU1", 2))
        self.assertEqual(got, {"AHU1": 0, "C1": 1, "R1": 2, "C2": 2})

    def test_bfs_from_failed_unit(self):
        g = self.make()
        g.set_node_failed("AHU1")
        self.assertEqual(dict(g.bfs_within("AHU1", 1)), {"AHU1": 0, "C1": 1})

    def test_components_after_duct_failure(self):
        g = self.make()
        self.assertEqual(len(g.components()), 1)
        g.set_edge_failed("C1", "C2")
        comps = sorted(sorted(c) for c in g.components())
        self.assertEqual(comps, [["AHU1", "C1", "R1"], ["AHU2", "C2", "R2"]])
        g.set_edge_failed("C1", "C2", False)
        self.assertEqual(len(g.components()), 1)

    def test_dijkstra_multi_source_and_rerouting(self):
        g = self.make()
        sp = g.dijkstra(["AHU1", "AHU2"])
        self.assertEqual(sp.source_of("R1"), "AHU1")
        self.assertEqual(sp.distance("R1"), 3)
        self.assertEqual(sp.source_of("R2"), "AHU2")
        g.set_node_failed("AHU1")
        sp = g.dijkstra(["AHU1", "AHU2"])
        self.assertEqual(sp.path("R1"), ["AHU2", "C2", "C1", "R1"])
        self.assertEqual(sp.distance("R1"), 6)

    def test_dijkstra_random_against_bellman_ford(self):
        rng = random.Random(7)
        g = Graph()
        n = 60
        for i in range(n):
            g.add_node(i, "room")
        edges = []
        for _ in range(180):
            a, b = rng.randrange(n), rng.randrange(n)
            w = rng.randint(1, 20)
            g.add_edge(a, b, w)
            edges.append((a, b, w))
        dist = [float("inf")] * n
        dist[0] = 0
        for _ in range(n):
            for a, b, w in edges:
                dist[b] = min(dist[b], dist[a] + w)
                dist[a] = min(dist[a], dist[b] + w)
        sp = g.dijkstra(0)
        for i in range(n):
            self.assertEqual(sp.distance(i), dist[i])
            path = sp.path(i)
            if path:
                self.assertEqual((path[0], path[-1]), (0, i))


class UnionFindTest(unittest.TestCase):
    def test_zones(self):
        uf = UnionFind()
        for r in ["N1", "N2", "N3", "W1", "W2"]:
            uf.add(r)
        self.assertTrue(uf.union("N1", "N2"))
        self.assertTrue(uf.union("N3", "N2"))
        self.assertFalse(uf.union("N1", "N3"))
        self.assertTrue(uf.connected("N1", "N3"))
        self.assertFalse(uf.connected("N1", "W1"))
        self.assertEqual(uf.set_size("N2"), 3)
        self.assertEqual(uf.set_count(), 3)
        groups = sorted(sorted(g) for g in uf.groups().values())
        self.assertEqual(groups, [["N1", "N2", "N3"], ["W1"], ["W2"]])

    def test_random_against_labels(self):
        rng = random.Random(8)
        n = 300
        uf = UnionFind()
        label = list(range(n))
        for i in range(n):
            uf.add(i)
        for _ in range(400):
            a, b = rng.randrange(n), rng.randrange(n)
            uf.union(a, b)
            la, lb = label[a], label[b]
            label = [la if x == lb else x for x in label]
        for _ in range(2000):
            a, b = rng.randrange(n), rng.randrange(n)
            self.assertEqual(uf.connected(a, b), label[a] == label[b])
        self.assertEqual(uf.set_count(), len(set(label)))


class SortingTest(unittest.TestCase):
    def test_all_sorts_match_sorted(self):
        rng = random.Random(9)
        for n in (0, 1, 2, 10, 500):
            data = [rng.randint(0, 50) for _ in range(n)]
            for sort in (merge_sort, quick_sort, insertion_sort):
                self.assertEqual(sort(data), sorted(data), sort.__name__)
        same = [7] * 2000  # many equal keys: three-way quick sort must not recurse deeply
        self.assertEqual(quick_sort(same), same)
        self.assertEqual(quick_sort(list(range(3000))), list(range(3000)))

    def test_merge_sort_is_stable(self):
        tasks = [("b", 1), ("a", 2), ("b", 0), ("a", 1)]
        self.assertEqual(merge_sort(tasks, key=lambda t: t[0]), [("a", 2), ("a", 1), ("b", 1), ("b", 0)])

    def test_input_not_changed(self):
        data = [3, 1, 2]
        merge_sort(data)
        quick_sort(data)
        self.assertEqual(data, [3, 1, 2])


class SegmentTreeTest(unittest.TestCase):
    def test_random_against_slices(self):
        rng = random.Random(10)
        n = 37
        ref = [None] * n
        t = SegmentTree(n)
        for _ in range(3000):
            if rng.random() < 0.5:
                i = rng.randrange(n)
                v = None if rng.random() < 0.1 else round(rng.uniform(15, 35), 1)
                t.update(i, v)
                ref[i] = v
            else:
                lo = rng.randrange(n)
                hi = rng.randrange(lo, n)
                vals = [v for v in ref[lo:hi + 1] if v is not None]
                s = t.query(lo, hi)
                self.assertEqual(s.count, len(vals))
                if vals:
                    self.assertAlmostEqual(s.average, sum(vals) / len(vals))
                    self.assertEqual((s.minimum, s.maximum), (min(vals), max(vals)))
                else:
                    self.assertIsNone(s.average)

    def test_build_from_values(self):
        t = SegmentTree(4, [20.0, None, 24.0, 22.0])
        s = t.query(0, 3)
        self.assertEqual((s.count, s.minimum, s.maximum), (3, 20.0, 24.0))
        self.assertAlmostEqual(s.average, 22.0)
        self.assertIsNone(t.get(1))


if __name__ == "__main__":
    unittest.main()
