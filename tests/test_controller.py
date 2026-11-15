"""Controller and scenario tests: the modules working together."""

import unittest

from hospital_climate.controller import ClimateController, ControlError
from hospital_climate.layout import build_hospital
from hospital_climate.model import Reading
from hospital_climate.scenarios import heatwave, hvac_failure, icu_flood, make_demo, normal_day


def fresh(window=12):
    specs, graph = build_hospital(4, 10)
    return ClimateController(specs, graph, window_size=window)


def feed(ctl, room, temp, hum=45.0, co2=500, minute=None):
    ctl.submit(Reading(room, ctl.minute if minute is None else minute, temp, hum, co2))
    ctl.process()


class PipelineTest(unittest.TestCase):
    def test_readings_processed_in_arrival_order(self):
        ctl = fresh()
        for t in (22.0, 22.4, 22.9):
            ctl.submit(Reading("211", 0, t, 45, 500))
        self.assertEqual(ctl.process(limit=2), 2)
        self.assertEqual(ctl.room("211").latest.temperature, 22.4)
        ctl.process()
        self.assertEqual(ctl.room("211").window.values(), [22.0, 22.4, 22.9])

    def test_full_buffer_counts_drops(self):
        specs, graph = build_hospital(1, 1)
        ctl = ClimateController(specs, graph, queue_capacity=2)
        self.assertTrue(ctl.submit(Reading("101", 0, 22, 45, 500)))
        self.assertTrue(ctl.submit(Reading("101", 0, 22, 45, 500)))
        self.assertFalse(ctl.submit(Reading("101", 0, 22, 45, 500)))
        self.assertEqual(ctl.dropped, 1)

    def test_unknown_room_reading_is_logged_not_fatal(self):
        ctl = fresh()
        feed(ctl, "999", 22.0)
        self.assertIn("unknown room 999", ctl.log.last().text)


class AlertTest(unittest.TestCase):
    def test_icu_beats_waiting_room(self):
        ctl = fresh()
        feed(ctl, "101", 27.0)  # waiting area, 1 C over its 26 C limit
        feed(ctl, "211", 29.0)  # ICU, 5 C over its 24 C limit
        feed(ctl, "105", 27.5)
        self.assertEqual(ctl.serve_alert().room_id, "211")
        self.assertEqual(ctl.serve_alert().room_id, "105")
        self.assertEqual(ctl.serve_alert().room_id, "101")
        self.assertIsNone(ctl.serve_alert())

    def test_alert_updates_and_clears(self):
        ctl = fresh()
        feed(ctl, "411", 25.0)               # ward, 1 C over
        feed(ctl, "211", 24.6)               # ICU, 0.6 C over: 100*1.6 = 160 vs 40*2 = 80
        self.assertEqual(ctl.peek_alert().room_id, "211")
        feed(ctl, "411", 30.0)               # ward much worse: 40*7 = 280 -> update-key moves it up
        self.assertEqual(ctl.peek_alert().room_id, "411")
        self.assertEqual(len(ctl.alerts), 2)
        feed(ctl, "411", 22.0)               # back in range: alert removed from the middle of the heap
        self.assertEqual(len(ctl.alerts), 1)
        self.assertTrue(ctl.alerts.is_valid())

    def test_old_alerts_age_upwards(self):
        ctl = fresh()
        feed(ctl, "101", 27.0, minute=0)     # waiting room: base 20
        ctl.advance_to(100)
        feed(ctl, "411", 25.0)               # ward: base 80, but 100 minutes younger
        a = ctl.peek_alert()
        self.assertEqual(a.room_id, "101")   # 20 + 2*100 = 220 > 80
        self.assertAlmostEqual(a.priority_at(100), 220.0)

    def test_rapid_rise_inside_safe_range_still_warns(self):
        ctl = fresh(window=5)
        for t in (21.2, 21.6, 22.0, 22.4, 22.9):  # +1.7 C, still under 24 C
            feed(ctl, "211", t)
        a = ctl.peek_alert()
        self.assertEqual(a.room_id, "211")
        self.assertIn("rising fast", a.reasons[0])

    def test_humidity_and_co2(self):
        ctl = fresh()
        feed(ctl, "411", 22.0, hum=70.0, co2=500)
        feed(ctl, "412", 22.0, hum=45.0, co2=1500)
        reasons = " ".join(" ".join(a.reasons) for a in ctl.open_alerts())
        self.assertIn("humidity 70", reasons)
        self.assertIn("CO2 1500", reasons)


class PatientTest(unittest.TestCase):
    def test_add_find_range_search_discharge(self):
        ctl = fresh()
        ctl.add_patient(30, "Mina Das", "411", 22.0)
        ctl.add_patient(10, "Mithu Roy", "412", 23.0)
        ctl.add_patient(20, "Karim Sheikh", "413", 21.5)
        self.assertEqual([p.id for p in ctl.patients_in_range(0, 25)], [10, 20])
        self.assertEqual([p.name for p in ctl.search_names("mi")], ["Mina Das", "Mithu Roy"])
        self.assertEqual(ctl.room("413").setpoint, 21.5)
        ctl.discharge_patient(20)
        self.assertIsNone(ctl.find_patient(20))
        self.assertEqual(ctl.search_names("kar"), [])
        self.assertEqual(ctl.room("413").setpoint, 22.5)  # back to the ward default
        with self.assertRaises(ControlError):
            ctl.add_patient(10, "Again", "411", 22.0)

    def test_comfort_setpoint_is_clamped_to_safe_range(self):
        ctl = fresh()
        ctl.add_patient(1, "Warm Person", "211", 28.0)  # ICU max is 24 C
        self.assertEqual(ctl.room("211").setpoint, 23.5)


class ControlAndUndoTest(unittest.TestCase):
    def test_setpoint_undo_and_log(self):
        ctl = fresh()
        ctl.set_setpoint("411", 21.5)
        ctl.set_ventilation("411", 5)
        ctl.undo()
        self.assertEqual(ctl.room("411").ventilation, 3)
        ctl.undo()
        self.assertEqual(ctl.room("411").setpoint, 22.5)
        with self.assertRaises(ControlError):
            ctl.undo()
        texts = [e.text for e in ctl.log]
        self.assertEqual(sum(t.startswith("UNDO") for t in texts), 2)  # undo is logged, nothing erased

    def test_unsafe_setpoint_refused(self):
        ctl = fresh()
        with self.assertRaises(ControlError):
            ctl.set_setpoint("211", 26.0)
        self.assertEqual(len(ctl.undo_stack), 0)

    def test_zone_setpoint_is_one_undo(self):
        ctl = fresh()
        self.assertEqual(ctl.zone_by_type("NICU"), 10)
        ctl.set_setpoint("305", 25.0, whole_zone=True)
        self.assertTrue(all(ctl.room(str(n)).setpoint == 25.0 for n in range(301, 311)))
        ctl.undo()
        self.assertTrue(all(ctl.room(str(n)).setpoint == 24.0 for n in range(301, 311)))

    def test_zone_refused_if_any_room_unsafe(self):
        ctl = fresh()
        ctl.merge_zone("211", "301")  # ICU 21-24 with NICU 22-26
        with self.assertRaises(ControlError):
            ctl.set_setpoint("301", 25.0, whole_zone=True)
        self.assertEqual(ctl.room("301").setpoint, 24.0)  # nothing half-applied

    def test_undo_keeps_latest_fifty(self):
        ctl = fresh()
        for i in range(60):
            ctl.set_ventilation("411", 1 + i % 5)
        self.assertEqual(len(ctl.undo_stack), ClimateController.UNDO_LIMIT)


class LayoutAndFaultTest(unittest.TestCase):
    def test_supply_and_failover(self):
        ctl = fresh()
        self.assertEqual(ctl.room("211").supply, "AHU-F2")
        hit = ctl.fail_unit("AHU-F2")
        self.assertEqual(len(hit), 20)
        self.assertIn(ctl.room("211").supply, ("AHU-F1", "AHU-F3"))
        self.assertGreater(ctl.room("211").supply_cost, 3.0)
        self.assertEqual(ctl.schedule()[0].title, "Repair AHU-F2")
        ctl.repair_unit("AHU-F2")
        self.assertEqual(ctl.room("211").supply, "AHU-F2")

    def test_isolated_wing_found_by_dfs(self):
        ctl = fresh()
        ctl.fail_unit("AHU-F2")
        for a, b in (("C1A", "C2A"), ("C2A", "C3A"), ("C2A", "C2B")):
            ctl.fail_duct(a, b)
        dead = [rooms for units, rooms in ctl.components() if rooms and not units]
        self.assertEqual(len(dead), 1)
        self.assertEqual(sorted(dead[0]), [str(n) for n in range(201, 211)])
        self.assertEqual(ctl.unsupplied_rooms(), [str(n) for n in range(201, 211)])

    def test_bad_names_refused(self):
        ctl = fresh()
        with self.assertRaises(ControlError):
            ctl.fail_unit("C2A")
        with self.assertRaises(ControlError):
            ctl.fail_duct("101", "999")


class RangeQueryTest(unittest.TestCase):
    def test_floor_and_room_ranges(self):
        ctl = fresh()
        for n, t in ((301, 22.0), (305, 24.0), (320, 26.0), (401, 30.0)):
            feed(ctl, str(n), t)
        f3 = ctl.floor_summary(3)
        self.assertEqual((f3.count, f3.minimum, f3.maximum), (3, 22.0, 26.0))
        self.assertAlmostEqual(ctl.range_summary(301, 320).average, 24.0)
        self.assertEqual(ctl.range_summary(305, 499).count, 3)
        self.assertEqual(ctl.range_summary(395, 405).maximum, 30.0)  # gap in numbering is fine
        with self.assertRaises(ControlError):
            ctl.range_summary(500, 600)


class ScenarioTest(unittest.TestCase):
    def test_normal_day_is_calm(self):
        r = normal_day()
        self.assertEqual(r.data["open_alerts"], 0)
        self.assertEqual(r.data["processed"], 120 * 80)

    def test_heatwave_serves_critical_rooms_first(self):
        types = heatwave().data["dispatch_types"]
        first = types[:10]
        self.assertGreaterEqual(sum(t in ("ICU", "OT", "NICU") for t in first), 8)
        self.assertNotIn("WAIT", first)

    def test_hvac_failure(self):
        d = hvac_failure().data
        self.assertEqual(d["affected"], 20)
        self.assertEqual(d["parts"], 2)
        self.assertEqual(len(d["unsupplied"]), 10)
        self.assertEqual(d["after_repair_unsupplied"], 0)

    def test_icu_flood_order(self):
        types = icu_flood().data["served_types"]
        last_critical = max(i for i, t in enumerate(types) if t in ("ICU", "OT"))
        first_wait = min(i for i, t in enumerate(types) if t == "WAIT")
        self.assertLess(last_critical, first_wait)

    def test_runs_are_repeatable(self):
        a, b = make_demo(seed=3), make_demo(seed=3)
        a.run(30)
        b.run(30)
        self.assertEqual(a.ctl.room("211").latest.temperature, b.ctl.room("211").latest.temperature)


if __name__ == "__main__":
    unittest.main()
