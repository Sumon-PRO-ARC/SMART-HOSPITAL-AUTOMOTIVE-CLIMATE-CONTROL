"""Merge sort and quick sort (proposal: maintenance scheduling).

Both take an optional ``key`` function and return a new sorted list; the
input is not changed.

* ``merge_sort`` - O(n log n) always, stable (equal keys keep their order),
  O(n) extra space. Used for the maintenance schedule, where tasks with the
  same deadline and priority must stay in the order they were reported.
* ``quick_sort`` - O(n log n) expected, O(n^2) worst case; randomised pivot
  and three-way partitioning (keys equal to the pivot are not recursed
  into), so sorted input or many equal keys do not trigger the worst case.
  Not stable.
* ``insertion_sort`` - O(n^2); the naive baseline for the benchmarks.
"""

import random


def _identity(x):
    return x


def merge_sort(items, key=None):
    key = key or _identity
    keyed = [(key(x), x) for x in items]
    _merge_sort(keyed, [None] * len(keyed), 0, len(keyed))
    return [x for _, x in keyed]


def _merge_sort(a, tmp, lo, hi):
    """Sorts a[lo:hi] in place, comparing only the key (index 0)."""
    if hi - lo <= 1:
        return
    mid = (lo + hi) // 2
    _merge_sort(a, tmp, lo, mid)
    _merge_sort(a, tmp, mid, hi)
    if not a[mid][0] < a[mid - 1][0]:
        return  # halves already in order
    i, j, k = lo, mid, lo
    while i < mid and j < hi:
        if a[j][0] < a[i][0]:  # strictly less: on ties take the left one (stable)
            tmp[k] = a[j]
            j += 1
        else:
            tmp[k] = a[i]
            i += 1
        k += 1
    while i < mid:
        tmp[k] = a[i]
        i += 1
        k += 1
    while j < hi:
        tmp[k] = a[j]
        j += 1
        k += 1
    for t in range(lo, hi):
        a[t] = tmp[t]


def quick_sort(items, key=None, rng=None):
    key = key or _identity
    rng = rng or random.Random(12345)
    keyed = [(key(x), x) for x in items]
    _quick_sort(keyed, 0, len(keyed) - 1, rng)
    return [x for _, x in keyed]


def _quick_sort(a, lo, hi, rng):
    while lo < hi:
        p = a[rng.randint(lo, hi)][0]
        # Dutch national flag: a[lo:lt] < p, a[lt:i] == p, a[gt+1:hi+1] > p
        lt, i, gt = lo, lo, hi
        while i <= gt:
            k = a[i][0]
            if k < p:
                a[lt], a[i] = a[i], a[lt]
                lt += 1
                i += 1
            elif p < k:
                a[i], a[gt] = a[gt], a[i]
                gt -= 1
            else:
                i += 1
        # Recurse into the smaller side, loop on the larger: O(log n) stack depth.
        if lt - lo < hi - gt:
            _quick_sort(a, lo, lt - 1, rng)
            lo = gt + 1
        else:
            _quick_sort(a, gt + 1, hi, rng)
            hi = lt - 1


def insertion_sort(items, key=None):
    key = key or _identity
    a = [(key(x), x) for x in items]
    for i in range(1, len(a)):
        cur = a[i]
        j = i - 1
        while j >= 0 and cur[0] < a[j][0]:
            a[j + 1] = a[j]
            j -= 1
        a[j + 1] = cur
    return [x for _, x in a]
