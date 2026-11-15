"""Domain objects: room types and their safe ranges, rooms, readings, alerts.

Safe ranges are SIMULATION DEFAULTS, not clinical guidance. The operating
theatre range (20-24 C, 20-60 % RH) follows ANSI/ASHRAE/ASHE Standard 170 as
described in the ASHRAE Journal, October 2019; the other rows are set in the
same spirit for the simulation. The CO2 limit of 1000 ppm is a common
indoor-air-quality rule of thumb, not a regulatory limit. Check the edition
of Standard 170 (or local code) that applies before using any of these for
a real building. See docs/design.md.
"""

from .ds import SlidingWindow


class RoomType:
    def __init__(self, code, label, weight, temp, humidity, co2_max):
        self.code = code
        self.label = label
        self.weight = weight          # urgency multiplier for alerts
        self.temp = temp              # (min, max) degrees C
        self.humidity = humidity      # (min, max) % relative humidity
        self.co2_max = co2_max        # ppm

    def comfort_setpoint(self):
        return round((self.temp[0] + self.temp[1]) / 2, 1)

    def __repr__(self):
        return "RoomType(%s)" % self.code


ICU = RoomType("ICU", "Intensive care unit", 100, (21.0, 24.0), (30.0, 60.0), 1000)
NEONATAL = RoomType("NICU", "Neonatal intensive care", 95, (22.0, 26.0), (30.0, 60.0), 1000)
OT = RoomType("OT", "Operating theatre", 90, (20.0, 24.0), (20.0, 60.0), 1000)
ISOLATION = RoomType("ISO", "Isolation room", 80, (21.0, 24.0), (30.0, 60.0), 1000)
WARD = RoomType("WARD", "General ward", 40, (21.0, 24.0), (30.0, 60.0), 1000)
WAITING = RoomType("WAIT", "Waiting area", 10, (21.0, 26.0), (30.0, 65.0), 1000)

ROOM_TYPES = [ICU, NEONATAL, OT, ISOLATION, WARD, WAITING]


def room_type(code):
    for t in ROOM_TYPES:
        if t.code == code.upper():
            return t
    raise ValueError("unknown room type: " + code)


class Reading:
    __slots__ = ("room_id", "minute", "temperature", "humidity", "co2")

    def __init__(self, room_id, minute, temperature, humidity, co2):
        self.room_id = room_id
        self.minute = minute
        self.temperature = temperature
        self.humidity = humidity
        self.co2 = co2

    def __repr__(self):
        return "Reading(%s @%d: %.1fC %.0f%% %dppm)" % (
            self.room_id, self.minute, self.temperature, self.humidity, self.co2)


class Room:
    def __init__(self, room_id, number, floor, wing, rtype, index, window_size):
        self.id = room_id
        self.number = number
        self.floor = floor
        self.wing = wing
        self.type = rtype
        self.index = index            # position in the segment trees
        self.setpoint = rtype.comfort_setpoint()
        self.ventilation = 3          # 1 (low) .. 5 (high)
        self.window = SlidingWindow(window_size)
        self.latest = None            # last Reading processed
        self.patients = []            # patient IDs in this room
        self.supply = None            # AHU that feeds it (set by the controller)
        self.supply_cost = None       # duct resistance of that route

    def __repr__(self):
        return "Room(%s %s floor %d)" % (self.id, self.type.code, self.floor)


class Patient:
    __slots__ = ("id", "name", "room_id", "temp", "humidity", "lighting", "noise")

    def __init__(self, pid, name, room_id, temp, humidity, lighting, noise):
        self.id = pid
        self.name = name
        self.room_id = room_id
        self.temp = temp          # preferred degrees C
        self.humidity = humidity  # preferred % RH
        self.lighting = lighting  # 1 (dim) .. 5 (bright)
        self.noise = noise        # maximum preferred dB(A)

    def __repr__(self):
        return "Patient(%d %s room %s)" % (self.id, self.name, self.room_id)


# ---- alert scoring -----------------------------------------------------------

RAPID_RISE_C = 1.5    # rise inside one sliding window that counts as "rapid"
AGE_PER_MINUTE = 2.0  # priority points an unresolved alert gains per minute


class Alert:
    __slots__ = ("room_id", "reasons", "severity", "base", "created", "minute")

    def __init__(self, room_id, reasons, severity, base, created, minute):
        self.room_id = room_id
        self.reasons = reasons    # list of short texts
        self.severity = severity  # deviation units, see deviation()
        self.base = base          # weight * (1 + severity)
        self.created = created    # minute the alert was first raised
        self.minute = minute      # minute of the latest reading

    def priority_at(self, now):
        return self.base + AGE_PER_MINUTE * (now - self.created)

    def heap_key(self):
        """Priority stored in the heap.

        Every open alert gains AGE_PER_MINUTE per minute, so comparing
        base + AGE * (now - created) for two alerts gives the same order as
        comparing base - AGE * created: the 'now' cancels out. Storing the
        second form means aging never requires touching the heap.
        """
        return self.base - AGE_PER_MINUTE * self.created


def deviation(rtype, reading, window):
    """Deviation units and reasons for one reading (0 units = all within range).

    1 unit = 1 C outside the temperature range, 5 % outside the humidity
    range, or 200 ppm over the CO2 limit. A rapid rise adds one unit.
    The worst metric decides; the others are listed as reasons too.
    """
    reasons = []
    worst = 0.0
    lo, hi = rtype.temp
    t = reading.temperature
    if t > hi or t < lo:
        d = t - hi if t > hi else lo - t
        reasons.append("temperature %.1f C (safe %.0f-%.0f)" % (t, lo, hi))
        worst = max(worst, d)
    lo, hi = rtype.humidity
    h = reading.humidity
    if h > hi or h < lo:
        d = (h - hi if h > hi else lo - h) / 5.0
        reasons.append("humidity %.0f %% (safe %.0f-%.0f)" % (h, lo, hi))
        worst = max(worst, d)
    if reading.co2 > rtype.co2_max:
        reasons.append("CO2 %d ppm (limit %d)" % (reading.co2, rtype.co2_max))
        worst = max(worst, (reading.co2 - rtype.co2_max) / 200.0)
    if len(window) >= 2 and window.change() >= RAPID_RISE_C:
        reasons.append("rising fast: +%.1f C over the last %d readings" % (window.change(), len(window)))
        worst += 1.0
    return worst, reasons
