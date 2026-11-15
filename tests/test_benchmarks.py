"""The benchmark harness itself: quick sizes agree, and the charts are written."""

import pathlib
import tempfile
import unittest

from benchmarks.run import run_all, write_markdown, write_svg


class BenchmarkHarnessTest(unittest.TestCase):
    def test_quick_run_and_outputs(self):
        results = run_all(quick=True, log=lambda *a: None)  # raises if any pair of methods disagrees
        self.assertEqual(len(results), 10)
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d)
            write_markdown(results, out / "results.md")
            for name, title, xlabel, labels, rows in results:
                write_svg(title, xlabel, labels, rows, out / (name + ".svg"))
            self.assertIn("## Room lookup", (out / "results.md").read_text(encoding="utf-8"))
            svg = (out / "lookup.svg").read_text(encoding="utf-8")
            self.assertTrue(svg.startswith("<svg") and svg.rstrip().endswith("</svg>"))
            self.assertIn("hash table", svg)


if __name__ == "__main__":
    unittest.main()
