"""A simple, repeatable physical model that feeds the controller with readings.

This is a teaching model, not building physics. Each simulated minute, for
every room:

* temperature drifts toward the outside temperature (envelope leak) and
  gains heat from people and equipment;
* the HVAC pushes it toward the room's setpoint, limited by a capacity that
  depends on how well the room is supplied: full capacity on its normal
  route, less when air must come the long way round after a fault
  (capacity * normal route cost / current route cost), none if no working
  AHU can reach it;
* humidity drifts toward the outside humidity; ventilation pulls it toward 45 %;
* CO2 rises with occupancy; ventilation pulls it toward the outdoor level.

Each room's sensor then reports one noisy reading, which goes through the
controller's circular queue. A fixed random seed makes every run identical.
"""

import random

from .controller import ClimateController, clock_text
from .ds import HashTable
from .layout import build_hospital
from .model import Reading

OUTDOOR_CO2 = 420.0


class RoomState:
    __slots__ = ("temp", "humidity", "co2", "occupants", "extra_heat", "normal_cost", "boost_until")

    def __init__(self, temp, humidity, co2, occupants, normal_cost):
        self.temp = temp
        self.humidity = humidity
        self.co2 = co2
        self.occupants = occupants
        self.extra_heat = 0.0      # C per minute from equipment (scenario-controlled)
        self.normal_cost = normal_cost
        self.boost_until = -1      # a technician dispatched to an alert doubles HVAC until then


class Simulator:
    LEAK = 0.02           # share of the indoor/outdoor difference that leaks in per minute
    HVAC_CAPACITY = 0.35  # max C per minute the HVAC can move a room at full supply
    HVAC_GAIN = 0.25      # share of the setpoint error corrected per minute
    PERSON_HEAT = 0.01    # C per minute per occupant
    PERSON_CO2 = 12.0     # ppm per minute per occupant

    def __init__(self, floors=4, rooms_per_wing=10, seed=7, window_size=12):
        specs, graph = build_hospital(floors, rooms_per_wing)
        self.ctl = ClimateController(specs, graph, window_size=window_size)
        self.rng = random.Random(seed)
        self.outside_temp = 30.0
        self.outside_humidity = 70.0
        self.hvac_factor = 1.0  # scenario knob: 0.5 = plant running at half power
        self.state = HashTable()
        for r in self.ctl.all_rooms():
            occupants = {"WAIT": 12, "WARD": 4, "OT": 6}.get(r.type.code, 1)
            self.state.put(r.id, RoomState(r.setpoint, 50.0, 600.0, occupants, r.supply_cost))

    @property
    def minute(self):
        return self.ctl.minute

    def _capacity(self, room, st):
        if room.supply is None:
            return 0.0
        cap = self.HVAC_CAPACITY * self.hvac_factor * min(1.0, st.normal_cost / room.supply_cost)
        if self.minute < st.boost_until:
            cap *= 2
        return cap

    def step(self):
        """One simulated minute: physics, one reading per room, controller processes the queue."""
        self.ctl.advance_to(self.minute + 1)
        rng = self.rng
        for room in self.ctl.all_rooms():
            st = self.state[room.id]
            st.temp += self.LEAK * (self.outside_temp - st.temp)
            st.temp += self.PERSON_HEAT * st.occupants + st.extra_heat
            cap = self._capacity(room, st)
            push = self.HVAC_GAIN * (room.setpoint - st.temp)
            st.temp += max(-cap, min(cap, push))

            vent = room.ventilation / 5.0 if room.supply is not None else 0.0
            st.humidity += 0.01 * (self.outside_humidity - st.humidity) + 0.08 * vent * (45.0 - st.humidity)
            st.co2 += self.PERSON_CO2 * st.occupants * 0.1
            st.co2 += 0.15 * vent * (OUTDOOR_CO2 - st.co2)

            self.ctl.submit(Reading(
                room.id, self.minute,
                round(st.temp + rng.gauss(0, 0.05), 1),  # sensors read to 0.1 C
                round(st.humidity + rng.gauss(0, 0.3), 1),
                int(st.co2 + rng.gauss(0, 5)),
            ))
        self.ctl.process()

    def run(self, minutes, every=None, on_tick=None):
        for _ in range(minutes):
            self.step()
            if on_tick is not None and every and self.minute % every == 0:
                on_tick(self)

    def dispatch(self, n=1, actor="operator"):
        """The facilities team handles the n most urgent alerts: HVAC boost for 15 minutes."""
        served = []
        for _ in range(n):
            alert = self.ctl.serve_alert(actor)
            if alert is None:
                break
            self.state[alert.room_id].boost_until = self.minute + 15
            served.append(alert)
        return served

    def now(self):
        return clock_text(self.minute)
