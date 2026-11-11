"""weather - today's weather, two days ahead and the moon (Documentation/InkServices.md, idea 2).

The forecast comes from Open-Meteo (https://open-meteo.com), free and without an API
key. Each tag is given a place, a latitude and a longitude on the Apps tab; nothing is
fetched until it has them. The forecast is fetched every 30 minutes and shared by all
tags at the same place. The moon is worked out here, with no web call.

Only the place's coordinates are sent to Open-Meteo. Temperatures are rounded to
whole degrees and the screen shows no clock, so the tag is sent a picture only when
something on it changes.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from shelfkit.inkservices import InkApp

app = InkApp("weather", title="Weather and moon",
             description="The weather here today and the next two days, and the moon.",
             layout="layout.xml")
app.config_field("place", label="Place name, as shown on the tag", default="")
app.config_field("latitude", label="Latitude (e.g. 52.09)", default="")
app.config_field("longitude", label="Longitude (e.g. 5.12)", default="")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_MINUTES = 25              # a little under the timer, so each run fetches once
STALE_HOURS = 3                 # older than this, the screen says so

# WMO weather codes, as Open-Meteo reports them: (words, icon)
SKY = [
    ((0,), "Clear", "sun"),
    ((1,), "Mostly clear", "sun"),
    ((2,), "Partly cloudy", "cloud"),
    ((3,), "Overcast", "cloud"),
    ((45, 48), "Fog", "cloud"),
    ((51, 53, 55, 56, 57), "Drizzle", "rain"),
    ((61, 63, 65, 66, 67), "Rain", "rain"),
    ((71, 73, 75, 77), "Snow", "cloud"),
    ((80, 81, 82), "Showers", "rain"),
    ((85, 86), "Snow showers", "cloud"),
    ((95, 96, 99), "Thunderstorm", "rain"),
]

MOON = ["New moon", "Waxing crescent", "First quarter", "Waxing gibbous",
        "Full moon", "Waning gibbous", "Last quarter", "Waning crescent"]
NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)   # a known new moon
SYNODIC_DAYS = 29.530588853


def _sky(code) -> tuple[str, str]:
    for codes, words, icon in SKY:
        if code in codes:
            return words, icon
    return "Unknown", "cloud"


def _place(tag):
    """(latitude, longitude) or the reason there is none."""
    lat, lon = tag.config.get("latitude", ""), tag.config.get("longitude", "")
    if not str(lat).strip() or not str(lon).strip():
        return None, "Set the place, latitude and longitude for this tag on the Apps tab."
    try:
        lat, lon = round(float(lat), 2), round(float(lon), 2)
    except ValueError:
        return None, "Latitude and longitude must be numbers, such as 52.09 and 5.12."
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, "That latitude or longitude is off the globe."
    return (lat, lon), ""


def moon(when: datetime) -> dict:
    """The moon's phase at a time: name and how much of it is lit, in percent."""
    when = when if when.tzinfo else when.astimezone()
    age = ((when - NEW_MOON).total_seconds() / 86400) % SYNODIC_DAYS
    lit = (1 - math.cos(2 * math.pi * age / SYNODIC_DAYS)) / 2
    return {"name": MOON[int(age / SYNODIC_DAYS * 8 + 0.5) % 8], "lit": round(lit * 100)}


@app.every(minutes=30)
def update(tag):
    place, _ = _place(tag)
    if place is None:
        return
    now = tag.now.timestamp()
    key = f"{place[0]},{place[1]}"
    forecasts = tag.shared.setdefault("forecasts", {})
    cached = forecasts.get(key)
    if not (cached and now - cached["at"] < CACHE_MINUTES * 60):
        try:
            forecast = tag.fetch_json(FORECAST_URL, {
                "latitude": place[0], "longitude": place[1],
                "current": "temperature_2m,weather_code,wind_speed_10m,is_day",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "timezone": "auto", "forecast_days": 3,
            })
        except Exception:
            if cached:                       # offline: show the newest forecast there is
                _show(tag, cached)
            raise                            # and let the host log why
        cached = forecasts[key] = {"at": now, "data": forecast}
        for old in [k for k, v in forecasts.items() if now - v["at"] > 86400]:
            del forecasts[old]                           # places no tag shows any more
    _show(tag, cached)


def _show(tag, cached: dict) -> None:
    tag.data["forecast"] = cached["data"]
    tag.data["fetched_at"] = datetime.fromtimestamp(cached["at"]).isoformat(timespec="minutes")


@app.data
def data(tag):
    place, why = _place(tag)
    out = {"moon": moon(tag.now), "place": tag.config.get("place") or "Weather"}
    forecast = tag.data.get("forecast")
    if place is None or not forecast:
        out.update(setup=True, why=why or "Waiting for the first forecast.")
        return out

    current, daily = forecast.get("current", {}), forecast.get("daily", {})
    words, icon = _sky(current.get("weather_code"))
    if icon == "sun" and current.get("is_day") == 0:
        icon = "moon"
    days = []
    for i, day in enumerate(daily.get("time", [])[:3]):
        label = "Today" if i == 0 else datetime.fromisoformat(day).strftime("%a")
        days.append({"day": label, "icon": _sky(daily["weather_code"][i])[1],
                     "hi": round(daily["temperature_2m_max"][i]),
                     "lo": round(daily["temperature_2m_min"][i])})
    out.update(setup=False, temp=round(current.get("temperature_2m", 0)), sky=words, icon=icon,
               wind=round(current.get("wind_speed_10m", 0)), days=days)

    fetched = tag.data.get("fetched_at")
    if fetched:
        age = tag.now.replace(tzinfo=None) - datetime.fromisoformat(fetched).replace(tzinfo=None)
        if age.total_seconds() > STALE_HOURS * 3600:
            out["stale"] = f"No update since {fetched[11:16]}"
    return out
