"""The web server: pages, the JSON API, and its safety checks."""

import http.client
import json
import unittest

from hospital_climate.web import start_in_thread


class WebTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.app = start_in_thread()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": "127.0.0.1:%d" % self.port}
        if body is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        conn.request(method, path, None if body is None else json.dumps(body), h)
        res = conn.getresponse()
        data = res.read()
        conn.close()
        return res.status, res, data

    def get(self, path):
        status, _, data = self.request("GET", path)
        return status, json.loads(data)

    def post(self, path, body):
        status, _, data = self.request("POST", path, body)
        return status, json.loads(data)

    def test_pages_are_served_with_security_headers(self):
        status, res, data = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Hospital Climate Control", data)
        self.assertIn("default-src 'self'", res.getheader("Content-Security-Policy"))
        self.assertEqual(res.getheader("X-Frame-Options"), "DENY")
        for path in ("/css/app.css", "/js/app.js", "/fonts/AtkinsonHyperlegible-Regular.ttf", "/benchmarks/lookup.svg"):
            self.assertEqual(self.request("GET", path)[0], 200, path)

    def test_no_files_outside_the_web_folder(self):
        for path in ("/../hospital_climate/web.py", "/..%2f..%2fLICENSE", "/benchmarks/../../README.md", "/nope.html"):
            self.assertEqual(self.request("GET", path)[0], 404, path)

    def test_state_describes_every_room(self):
        status, s = self.get("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(len(s["rooms"]), 80)
        self.assertEqual(len(s["floors"]), 4)
        self.assertIn("clock", s)

    def test_actions_change_the_simulation(self):
        self.post("/api/reset", {})
        self.assertEqual(self.post("/api/weather", {"temp": 42, "humidity": 70})[0], 200)
        self.assertEqual(self.post("/api/heat", {"room": "213", "value": 0.8})[0], 200)
        self.assertEqual(self.post("/api/tick", {"minutes": 30})[0], 200)
        _, s = self.get("/api/state")
        self.assertGreater(s["alert_count"], 0)
        self.assertEqual(s["alerts"][0]["room"], "213")
        status, out = self.post("/api/serve", {"n": 1})
        self.assertEqual((status, out["served"]), (200, ["213"]))
        _, room = self.get("/api/room?id=213")
        self.assertEqual(room["type"], "ICU")
        self.assertEqual(len(room["window"]), 12)

    def test_setpoint_undo_and_validation(self):
        self.post("/api/reset", {})
        self.assertEqual(self.post("/api/setpoint", {"room": "411", "value": 21.5})[0], 200)
        self.assertEqual(self.get("/api/room?id=411")[1]["setpoint"], 21.5)
        self.assertEqual(self.post("/api/undo", {})[0], 200)
        self.assertEqual(self.get("/api/room?id=411")[1]["setpoint"], 22.5)
        status, out = self.post("/api/setpoint", {"room": "211", "value": 30})
        self.assertEqual(status, 400)
        self.assertIn("safe range", out["error"])
        self.assertEqual(self.post("/api/ventilation", {"room": "411", "level": "high"})[0], 400)
        self.assertEqual(self.get("/api/room?id=999")[0], 400)

    def test_patients_faults_zones_tasks(self):
        self.post("/api/reset", {})
        self.assertEqual(self.post("/api/patients/add", {"id": 5000, "name": "Test Person", "room": "415", "temp": 22,
                                                         "humidity": 45, "lighting": 3, "noise": 40})[0], 200)
        _, found = self.get("/api/patients/search?q=test")
        self.assertEqual([p["id"] for p in found], [5000])
        self.assertEqual(self.post("/api/fail", {"a": "AHU-F2"})[0], 200)
        for a, b in (("C1A", "C2A"), ("C2A", "C3A"), ("C2A", "C2B")):
            self.assertEqual(self.post("/api/fail", {"a": a, "b": b})[0], 200)
        _, net = self.get("/api/network")
        self.assertEqual(len(net["unsupplied"]), 10)
        self.assertTrue(any(not p["units"] and p["rooms"] for p in net["parts"]))
        self.assertEqual(len(self.get("/api/tasks")[1]), 4)
        self.assertEqual(self.post("/api/zones/type", {"type": "NICU"})[0], 200)
        self.assertEqual(self.get("/api/zones")[1]["groups"][0]["rooms"][0], "301")
        _, rng = self.get("/api/range?first=301&last=320&metric=temperature")
        self.assertEqual(rng["count"], 20)

    def test_scenario_replaces_the_live_state(self):
        status, out = self.post("/api/scenario", {"name": "hvac_failure"})
        self.assertEqual(status, 200)
        self.assertIn("HVAC FAILURE", out["report"])
        _, s = self.get("/api/state")
        self.assertIn("hvac failure", s["label"])
        self.assertEqual(self.get("/api/report")[1]["name"], "hvac_failure")
        self.post("/api/reset", {})

    def test_refuses_foreign_hosts_and_non_json_posts(self):
        status, _, _ = self.request("GET", "/api/state", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/tick", "minutes=5",
                     {"Host": "127.0.0.1", "Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(conn.getresponse().status, 415)
        conn.close()
        status, _, _ = self.request("POST", "/api/tick", {"pad": "x" * 20000})
        self.assertEqual(status, 413)
        self.assertEqual(self.post("/api/nothing", {})[0], 404)


if __name__ == "__main__":
    unittest.main()
