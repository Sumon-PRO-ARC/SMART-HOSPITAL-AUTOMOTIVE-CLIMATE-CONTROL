"""Fails if a data-structure module leans on Python's ready-made structures.

The proposal asks for the structures to be built from scratch. Inside
hospital_climate/ds/ this test reads every module's syntax tree and forbids
the library modules that already implement them, built-in dict and set
(calls, literals, comprehensions) and sorted() / list.sort(). Python lists
are allowed: they are used as plain arrays.
"""

import ast
import pathlib
import unittest

DS_DIR = pathlib.Path(__file__).resolve().parent.parent / "hospital_climate" / "ds"
FORBIDDEN_MODULES = {"heapq", "bisect", "collections", "queue", "array", "functools"}
FORBIDDEN_CALLS = {"dict", "set", "frozenset", "sorted"}
# Display-only dictionaries returned to callers (not used to store the data).
ALLOWED_DICT_LITERALS = {("hash_table.py", "stats")}


def problems_in(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    functions = {}
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef):
            for node in ast.walk(fn):
                functions.setdefault(id(node), fn.name)

    def report(node, what):
        found.append("%s:%d uses %s" % (path.name, node.lineno, what))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_MODULES:
                    report(node, "module " + alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in FORBIDDEN_MODULES:
                report(node, "module " + node.module)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                report(node, node.func.id + "()")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "sort":
                report(node, "list.sort()")
        elif isinstance(node, (ast.Set, ast.SetComp, ast.DictComp)):
            report(node, "a built-in set/dict comprehension or literal")
        elif isinstance(node, ast.Dict):
            if (path.name, functions.get(id(node))) not in ALLOWED_DICT_LITERALS:
                report(node, "a built-in dict literal")
    return found


class NoReadyMadeStructuresTest(unittest.TestCase):
    def test_ds_package_builds_its_own(self):
        problems = []
        for path in sorted(DS_DIR.glob("*.py")):
            problems += problems_in(path)
        self.assertEqual(problems, [], "\n".join(problems))

    def test_guard_catches_violations(self):
        tmp = pathlib.Path(__file__).with_name("_guard_probe.py")
        tmp.write_text("import heapq\nx = {}\ny = sorted([2, 1])\nz = set()\nw = [1]\nw.sort()\n", encoding="utf-8")
        try:
            self.assertEqual(len(problems_in(tmp)), 5)
        finally:
            tmp.unlink()


if __name__ == "__main__":
    unittest.main()
