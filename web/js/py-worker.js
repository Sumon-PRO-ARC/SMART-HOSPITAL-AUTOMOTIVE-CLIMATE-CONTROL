"use strict";
/* Live-site engine. GitHub Pages can only serve files, so on the live site the
   simulation runs here, in the visitor's browser: Pyodide (Python compiled to
   WebAssembly) runs the project's own Python code, unchanged, and answers the
   same API calls the local server would. Runs in a Web Worker so the page stays
   responsive while Python works. */

const PYODIDE_VERSION = "0.26.4";
const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v" + PYODIDE_VERSION + "/full/";

importScripts(PYODIDE_URL + "pyodide.js");

let call = null;  // Python: call(method, path, query_json, body_json) -> json text
let tick = null;  // Python: advances the clock while it is running

async function boot() {
  const pyodide = await loadPyodide({ indexURL: PYODIDE_URL });
  const base = new URL("../py/", self.location.href);
  const manifest = await (await fetch(new URL("manifest.json", base))).json();
  for (const file of manifest.files) {
    const res = await fetch(new URL(file, base));
    if (!res.ok) throw new Error("Could not load " + file + " (" + res.status + ")");
    const target = "/home/pyodide/" + file;
    pyodide.FS.mkdirTree(target.slice(0, target.lastIndexOf("/")));
    pyodide.FS.writeFile(target, await res.text());
  }
  pyodide.runPython(`
import json, sys
sys.path.insert(0, "/home/pyodide")
from hospital_climate.api import App, handle_api

app = App()

def call(method, path, query_json, body_json):
    query = json.loads(query_json)
    body = json.loads(body_json) if body_json else None
    status, out = handle_api(app, method, path, query, body)
    return json.dumps({"status": status, "data": out})

def tick():
    with app.lock:
        app.tick_clock()
`);
  call = pyodide.globals.get("call");
  tick = pyodide.globals.get("tick");
}

const ready = boot().then(
  () => { self.postMessage({ type: "ready" }); },
  (e) => { self.postMessage({ type: "failed", message: String(e && e.message || e) }); throw e; },
);

// The clock: once a real second, like the local server's background thread.
setInterval(() => { if (tick) tick(); }, 1000);

self.onmessage = async (event) => {
  const { id, method, path, query, body } = event.data;
  try {
    await ready;
    const out = JSON.parse(call(method, path, JSON.stringify(query || {}), body === undefined ? "" : JSON.stringify(body)));
    self.postMessage({ id, status: out.status, data: out.data });
  } catch (e) {
    self.postMessage({ id, status: 500, data: { error: "The in-browser simulation failed: " + (e && e.message || e) } });
  }
};
