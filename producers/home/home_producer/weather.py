"""The weather pane: now, the next day by the hour, and the coming days.

Everything comes from one Home Assistant ``weather`` entity: its state and
attributes for now, and ``weather.get_forecasts`` for the hourly and daily
forecasts. Units are the entity's own (``temperature_unit``,
``wind_speed_unit``, ``pressure_unit``, ``precipitation_unit``).

Layout at 1280×720: the "Now" card on the left (392 px); on the right, "Next
24 hours" (an inline-SVG temperature line through the next 22 hours, with
eight labelled columns three hours apart, and blue bars where rain or snow is
expected) above "Coming days" (up to seven columns).
"""

import html
from datetime import datetime, timezone

from .style import AMBER, BLUE, MUTED, clock, degrees, page, whole

TITLE = "Weather"
BAND, BAND_TEXT = "#1d3a4a", "#c6e3ee"
HOURS = 22          # the line runs through hours 0..21, so columns 0, 3, ... 21 sit on it
COLUMN_EVERY = 3
DAYS = 7
CHART_W, CHART_H = 796, 96

CONDITIONS = {
    "clear-night": ("Clear", "#9fa8da"), "cloudy": ("Cloudy", "#90a4ae"),
    "exceptional": ("Unusual", "#ef5350"), "fog": ("Fog", "#90a4ae"), "hail": ("Hail", "#b3e5fc"),
    "lightning": ("Lightning", "#b39ddb"), "lightning-rainy": ("Thunderstorms", "#b39ddb"),
    "partlycloudy": ("Partly cloudy", "#cfd8dc"), "pouring": ("Pouring rain", BLUE),
    "rainy": ("Rain", BLUE), "snowy": ("Snow", "#e3f2fd"), "snowy-rainy": ("Sleet", "#b3e5fc"),
    "sunny": ("Sunny", "#f6c344"), "windy": ("Windy", "#80cbc4"),
    "windy-variant": ("Windy, cloudy", "#80cbc4"),
}
COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

CSS = """
.cols { display: flex; gap: 12px; margin-top: 12px; height: 550px; }
.card { flex: 0 0 auto; }
.card.now { flex: 0 0 392px; height: 550px; }
.right { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 12px; }
.hours { height: 262px; }
.days { height: 276px; }
.dot { display: inline-block; width: 16px; height: 16px; border-radius: 50%%; margin-right: 10px;
  vertical-align: -1px; }
.cond { height: 36px; font-size: 26px; line-height: 36px; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.big { height: 120px; font-size: 112px; line-height: 120px; font-weight: bold; }
.hilo { height: 30px; font-size: 22px; line-height: 30px; color: %(muted)s; }
.fact { height: 34px; display: flex; justify-content: space-between; gap: 12px;
  border-bottom: 1px solid #2a373e; box-sizing: border-box; line-height: 33px; }
.fact span:first-child { color: %(muted)s; }
svg { display: block; }
.strip { display: flex; }
.strip > div { flex: 1 1 0; min-width: 0; text-align: center; }
.t { height: 26px; color: %(muted)s; white-space: nowrap; }
.v { height: 26px; font-weight: bold; }
.c { height: 26px; font-size: 20px; color: %(muted)s; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; padding: 0 4px; }
.p { height: 26px; font-size: 20px; color: %(blue)s; white-space: nowrap; }
.day { height: 30px; font-size: 24px; line-height: 30px; font-weight: bold; margin-top: 4px; }
.dc { height: 52px; font-size: 20px; line-height: 26px; color: %(muted)s; padding: 0 4px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.hi { height: 36px; font-size: 30px; line-height: 36px; font-weight: bold; }
.lo { height: 28px; font-size: 22px; line-height: 28px; color: %(muted)s; }
""" % {"muted": MUTED, "blue": BLUE}


def pick(states, entity_id=None):
    """The weather entity to show: ``entity_id`` when given, else the first ``weather.*`` by id."""
    found = sorted((s for s in states if s["entity_id"].startswith("weather.")),
                   key=lambda s: s["entity_id"])
    if entity_id is not None:
        found = [s for s in found if s["entity_id"] == entity_id]
    return found[0] if found else None


def render_weather(entity, hourly, daily, now, tz):
    """pane.html: the weather at 1280×720. ``hourly``/``daily`` may be None (no forecast)."""
    attrs = entity.get("attributes") if isinstance(entity.get("attributes"), dict) else {}
    today = now.astimezone(tz).date()
    days = _days(daily, today, tz)
    hours = _hours(hourly, now)
    body = '<div class="cols">%s<div class="right">%s%s</div></div>' % (
        _now(entity.get("state"), attrs, days[0] if days and days[0][0] == today else None),
        _hours_card(hours, attrs, tz), _days_card(days, today, attrs.get("precipitation_unit")))
    # "Weather forecast from met.no, delivered by ..." → "Weather forecast from met.no"
    source = attrs.get("attribution") if isinstance(attrs.get("attribution"), str) else ""
    source = source.split(",")[0].strip().rstrip(".") or "Home Assistant"
    return page(TITLE, BAND, BAND_TEXT, CSS, TITLE, html.escape(now.astimezone(tz).strftime("%A, %B %-d")),
                body, "%s · as of %s" % (source, clock(now, tz)))


def _now(state, attrs, today):
    e = html.escape
    label, colour = _condition(state)
    facts = []
    if attrs.get("apparent_temperature") is not None:
        facts.append(("Feels like", degrees(attrs["apparent_temperature"])))
    if _number(attrs.get("humidity")) is not None:
        facts.append(("Humidity", "%d%%" % whole(attrs["humidity"])))
    if _number(attrs.get("wind_speed")) is not None:
        facts.append(("Wind", _wind(attrs)))
    if attrs.get("dew_point") is not None:
        facts.append(("Dew point", degrees(attrs["dew_point"])))
    if _number(attrs.get("pressure")) is not None:
        facts.append(("Pressure", _pressure(attrs["pressure"], attrs.get("pressure_unit"))))
    if _number(attrs.get("uv_index")) is not None:
        facts.append(("UV index", "%g" % round(attrs["uv_index"], 1)))
    if _number(attrs.get("cloud_coverage")) is not None:
        facts.append(("Cloud cover", "%d%%" % whole(attrs["cloud_coverage"])))
    hilo = ""
    if today is not None:
        hilo = "High %s · Low %s" % (degrees(today[2]), degrees(today[3]))
    return ('<div class="card now"><h2>Now</h2><div class="cond"><span class="dot" style="background:%s"></span>'
            '%s</div><div class="big">%s</div><div class="hilo">%s</div>%s</div>'
            % (colour, e(label), degrees(attrs.get("temperature")), e(hilo),
               "".join('<div class="fact"><span>%s</span><span>%s</span></div>' % (e(k), e(v))
                       for k, v in facts[:9])))


def _hours_card(hours, attrs, tz):
    e = html.escape
    if not hours:
        return '<div class="card hours"><h2>Next 24 hours</h2><div class="none">No hourly forecast.</div></div>'
    unit = attrs.get("precipitation_unit")
    columns = []
    for i in range(0, len(hours), COLUMN_EVERY):
        when, temp, condition, rain = hours[i]
        columns.append('<div><div class="t">%s</div><div class="v">%s</div><div class="c">%s</div>'
                       '<div class="p">%s</div></div>'
                       % (e(when.astimezone(tz).strftime("%-I %p")), degrees(temp),
                          e(_condition(condition)[0]), e(_rain(rain, unit))))
    # a column per COLUMN_EVERY hours; a part-filled last stretch still gets its column
    return '<div class="card hours"><h2>Next 24 hours</h2>%s<div class="strip">%s</div></div>' % (
        _chart(hours, len(columns)), "".join(columns))


def _chart(hours, columns):
    """An inline-SVG temperature line whose labelled points sit over the column centres."""
    temps = [t for _, t, _, _ in hours]
    known = [t for t in temps if t is not None]
    if not known:
        return ""
    lo, hi = min(known), max(known)
    step = CHART_W / columns / COLUMN_EVERY            # px per hour
    x = lambda i: CHART_W / columns / 2 + i * step
    y = lambda t: CHART_H / 2 if hi == lo else 80 - (t - lo) / (hi - lo) * 64
    line = " ".join("%.1f,%.1f" % (x(i), y(t)) for i, t in enumerate(temps) if t is not None)
    bars = []
    for i, (_, _, _, rain) in enumerate(hours):
        if rain:   # a bar per wet hour, full height (30 px) at a quarter inch or more
            h = max(min(rain, 0.25) / 0.25 * 30, 3)
            bars.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" opacity="0.7"/>'
                        % (x(i) - step * 0.35, CHART_H - h, step * 0.7, h, BLUE))
    dots = "".join('<circle cx="%.1f" cy="%.1f" r="5" fill="%s"/>' % (x(i), y(temps[i]), AMBER)
                   for i in range(0, len(temps), COLUMN_EVERY) if temps[i] is not None)
    return ('<svg width="%d" height="%d" viewBox="0 0 %d %d">%s<polyline points="%s" fill="none" '
            'stroke="%s" stroke-width="3" stroke-linejoin="round"/>%s</svg>'
            % (CHART_W, CHART_H, CHART_W, CHART_H, "".join(bars), line, AMBER, dots))


def _days_card(days, today, unit):
    e = html.escape
    if not days:
        return '<div class="card days"><h2>Coming days</h2><div class="none">No daily forecast.</div></div>'
    columns = []
    for day, condition, high, low, rain in days[:DAYS]:
        label, colour = _condition(condition)
        columns.append('<div><div class="day">%s</div><div class="dc"><span class="dot" style="background:%s">'
                       '</span>%s</div><div class="hi">%s</div><div class="lo">%s</div><div class="p">%s</div></div>'
                       % (e("Today" if day == today else day.strftime("%a")), colour, e(label),
                          degrees(high), degrees(low), e(_rain(rain, unit))))
    return '<div class="card days"><h2>Coming days</h2><div class="strip">%s</div></div>' % "".join(columns)


def _hours(hourly, now):
    """``[(when, temperature, condition, precipitation)]`` from the coming hour on."""
    out = []
    for f in hourly or ():
        when = _when(f.get("datetime"))
        if when is None or (now - when).total_seconds() >= 3600:
            continue
        out.append((when, _number(f.get("temperature")), f.get("condition"), _number(f.get("precipitation"))))
    out.sort(key=lambda h: h[0])
    return out[:HOURS]


def _days(daily, today, tz):
    """``[(date, condition, high, low, precipitation)]`` from today on, one per date."""
    out, seen = [], set()
    for f in sorted((f for f in daily or () if _when(f.get("datetime"))), key=lambda f: _when(f["datetime"])):
        day = _when(f["datetime"]).astimezone(tz).date()
        if day < today or day in seen:
            continue
        seen.add(day)
        out.append((day, f.get("condition"), f.get("temperature"), f.get("templow"),
                    _number(f.get("precipitation"))))
    return out


def _condition(state):
    if isinstance(state, str) and state in CONDITIONS:
        return CONDITIONS[state]
    if isinstance(state, str) and state not in ("", "unknown", "unavailable"):
        return state.replace("-", " ").capitalize(), MUTED
    return "Unknown", MUTED


def _wind(attrs):
    speed = "%d %s" % (whole(attrs["wind_speed"]), attrs.get("wind_speed_unit") or "")
    bearing = _number(attrs.get("wind_bearing"))
    if bearing is None:
        return speed.strip()
    return "%s from %s" % (speed.strip(), COMPASS[int((bearing % 360 + 22.5) // 45) % 8])


def _pressure(value, unit):
    unit = unit if isinstance(unit, str) else ""
    text = "%.2f" % value if unit == "inHg" else "%d" % whole(value)
    return ("%s %s" % (text, unit)).strip()


def _rain(amount, unit):
    if not amount:
        return ""
    unit = unit if isinstance(unit, str) else "in"
    return ("%.2f %s" % (amount, unit)) if unit == "in" else ("%.1f %s" % (amount, unit))


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _when(value):
    """An RFC 3339 forecast time → aware datetime (UTC when it carries no offset), or None."""
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)
