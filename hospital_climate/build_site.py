"""Builds the static live site for GitHub Pages.

    python -m hospital_climate build-site --out _site

The output folder holds the dashboard (web/), the benchmark charts and a copy
of the Python package under py/, with py/manifest.json listing its files. In
the browser, js/py-worker.js loads Pyodide and runs that Python code, so the
live site is the same program as the local server, not a re-implementation.
The GitHub Actions workflow (.github/workflows/pages.yml) runs this on every
push to main and publishes the folder.
"""

import json
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "hospital_climate"
# Server and command-line modules are not needed (and partly not available) in the browser.
SERVER_ONLY = {"web.py", "cli.py", "__main__.py", "build_site.py"}


def python_files():
    """Package files the browser needs, as paths relative to the project root, sorted."""
    files = []
    for path in PACKAGE.rglob("*.py"):
        if path.name in SERVER_ONLY or "__pycache__" in path.parts:
            continue
        files.append(path.relative_to(ROOT).as_posix())
    files.sort()
    return files


def build(out):
    out = pathlib.Path(out).resolve()
    if out == ROOT or ROOT in out.parents and out.name in ("web", "hospital_climate", "docs"):
        raise ValueError("refusing to build into the project's own folders: " + str(out))
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "web", out, ignore=shutil.ignore_patterns("__pycache__"))
    bench = out / "benchmarks"
    bench.mkdir()
    for svg in (ROOT / "docs" / "benchmarks").glob("*.svg"):
        shutil.copy2(svg, bench / svg.name)
    files = python_files()
    for rel in files:
        target = out / "py" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    (out / "py" / "manifest.json").write_text(json.dumps({"files": files}, indent=1), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # serve files as they are
    return out, len(files)


def main(out="_site"):
    folder, n = build(out)
    print("Built the live site in %s (%d Python files)." % (folder, n))
    print("Try it locally:  python -m http.server 8080 --directory %s" % folder)
    return 0
