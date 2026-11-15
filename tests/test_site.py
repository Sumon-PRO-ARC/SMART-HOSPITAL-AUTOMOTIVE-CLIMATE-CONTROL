"""The live-site build (GitHub Pages) and the shared API it runs in the browser."""

import ast
import json
import pathlib
import tempfile
import unittest

from hospital_climate.api import App, handle_api
from hospital_climate.build_site import SERVER_ONLY, build


class SharedApiTest(unittest.TestCase):
    """handle_api is what the browser calls through Pyodide; no server involved."""

    def test_calls_without_a_server(self):
        app = App()
        self.assertEqual(handle_api(app, "GET", "/api/health"), (200, {"ok": True}))
        status, state = handle_api(app, "GET", "/api/state", {})
        self.assertEqual((status, len(state["rooms"])), (200, 80))
        status, out = handle_api(app, "POST", "/api/tick", {}, {"minutes": 10})
        self.assertEqual(status, 200)
        self.assertEqual(handle_api(app, "GET", "/api/state")[1]["clock"], "D1 08:15")
        status, out = handle_api(app, "POST", "/api/setpoint", {}, {"room": "211", "value": 30})
        self.assertEqual(status, 400)
        self.assertIn("safe range", out["error"])
        self.assertEqual(handle_api(app, "GET", "/api/range", {"first": "x", "last": "2"})[0], 400)
        self.assertEqual(handle_api(app, "GET", "/api/nope")[0], 404)
        self.assertEqual(handle_api(app, "POST", "/api/tick", {}, None)[0], 400)
        self.assertEqual(handle_api(app, "DELETE", "/api/state")[0], 405)

    def test_clock_ticks_only_while_running(self):
        app = App()
        start = app.ctl.minute
        app.tick_clock()
        self.assertEqual(app.ctl.minute, start)
        handle_api(app, "POST", "/api/clock", {}, {"running": True, "speed": 15})
        app.tick_clock()
        self.assertEqual(app.ctl.minute, start + 15)


class SiteBuildTest(unittest.TestCase):
    def test_build_contains_everything_the_browser_needs(self):
        with tempfile.TemporaryDirectory() as d:
            out, n = build(pathlib.Path(d) / "site")
            for rel in ("index.html", "css/app.css", "js/app.js", "js/py-worker.js", "favicon.svg",
                        "fonts/AtkinsonHyperlegible-Regular.ttf", "benchmarks/lookup.svg", ".nojekyll"):
                self.assertTrue((out / rel).is_file(), rel)
            manifest = json.loads((out / "py" / "manifest.json").read_text(encoding="utf-8"))
            files = manifest["files"]
            self.assertEqual(len(files), n)
            self.assertIn("hospital_climate/api.py", files)
            self.assertIn("hospital_climate/ds/heap.py", files)
            for f in files:
                self.assertTrue((out / "py" / f).is_file(), f)
                self.assertNotIn(pathlib.PurePosixPath(f).name, SERVER_ONLY)

    def test_browser_code_imports_nothing_server_only(self):
        """Pyodide has no sockets or browser launching; the shipped modules must not need them."""
        root = pathlib.Path(__file__).resolve().parent.parent
        banned = {"http", "socketserver", "socket", "webbrowser", "subprocess"}
        with tempfile.TemporaryDirectory() as d:
            out, _ = build(pathlib.Path(d) / "site")
            for f in json.loads((out / "py" / "manifest.json").read_text(encoding="utf-8"))["files"]:
                tree = ast.parse((root / f).read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                        names = [node.module]
                    for name in names:
                        self.assertNotIn(name.split(".")[0], banned, "%s imports %s" % (f, name))
                        self.assertNotIn(name, ("hospital_climate.web", "hospital_climate.cli"))

    def test_refuses_to_overwrite_the_project(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        with self.assertRaises(ValueError):
            build(root)
        with self.assertRaises(ValueError):
            build(root / "web")


if __name__ == "__main__":
    unittest.main()
