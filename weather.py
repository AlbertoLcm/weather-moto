"""Consulta el pronóstico de Open-Meteo para una zona alrededor de un punto."""

from __future__ import annotations

from dataclasses import dataclass
from math import asin, atan2, cos, degrees, radians, sin
from typing import Any

import requests

from config import Settings


FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARIABLES = (
    "precipitation_probability,precipitation,rain,showers,weather_code,"
    "wind_speed_10m,wind_gusts_10m"
)


class WeatherServiceError(RuntimeError):
    """Open-Meteo no pudo devolver un pronóstico utilizable."""


@dataclass(frozen=True)
class SamplePoint:
    name: str
    latitude: float
    longitude: float
    distance_km: float


@dataclass(frozen=True)
class HourlyForecast:
    point: SamplePoint
    timezone: str
    times: tuple[str, ...]
    precipitation_probability: tuple[float, ...]
    precipitation: tuple[float, ...]
    rain: tuple[float, ...]
    showers: tuple[float, ...]
    weather_code: tuple[int, ...]
    wind_speed: tuple[float, ...]
    wind_gusts: tuple[float, ...]


def destination_point(
    latitude: float, longitude: float, distance_km: float, bearing_degrees: float
) -> tuple[float, float]:
    """Devuelve la coordenada a ``distance_km`` usando la esfera terrestre."""
    earth_radius_km = 6_371.0088
    angular_distance = distance_km / earth_radius_km
    bearing = radians(bearing_degrees)
    lat1, lon1 = radians(latitude), radians(longitude)

    lat2 = asin(
        sin(lat1) * cos(angular_distance)
        + cos(lat1) * sin(angular_distance) * cos(bearing)
    )
    lon2 = lon1 + atan2(
        sin(bearing) * sin(angular_distance) * cos(lat1),
        cos(angular_distance) - sin(lat1) * sin(lat2),
    )
    return degrees(lat2), ((degrees(lon2) + 540) % 360) - 180


def build_sample_points(latitude: float, longitude: float, radius_km: float) -> list[SamplePoint]:
    """Crea el centro y anillos a 3 km y al radio solicitado.

    Los ocho rumbos de cada anillo detectan lluvia próxima sin asumir una ruta concreta.
    Si el radio solicitado es menor a 3 km, sólo se usa ese anillo para no duplicar puntos.
    """
    points = [SamplePoint("Centro", latitude, longitude, 0.0)]
    radii = [radius_km] if radius_km <= 3 else [3.0, radius_km]
    directions = (
        (0, "N"),
        (45, "NE"),
        (90, "E"),
        (135, "SE"),
        (180, "S"),
        (225, "SO"),
        (270, "O"),
        (315, "NO"),
    )
    for radius in radii:
        radius_label = f"{radius:g} km"
        for bearing, direction in directions:
            point_lat, point_lon = destination_point(latitude, longitude, radius, bearing)
            points.append(
                SamplePoint(f"{direction} ({radius_label})", point_lat, point_lon, radius)
            )
    return points


def _number_series(hourly: dict[str, Any], field: str, length: int, integer: bool = False) -> tuple:
    values = hourly.get(field)
    if not isinstance(values, list) or len(values) < length:
        raise WeatherServiceError(f"La respuesta no incluye una serie válida para {field}.")
    try:
        converter = int if integer else float
        return tuple(converter(value) for value in values[:length])
    except (TypeError, ValueError) as exc:
        raise WeatherServiceError(f"La respuesta contiene valores inválidos para {field}.") from exc


def _parse_location(payload: dict[str, Any], point: SamplePoint, expected_hours: int) -> HourlyForecast:
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise WeatherServiceError("Open-Meteo no devolvió datos horarios.")
    times = hourly.get("time")
    if not isinstance(times, list) or len(times) < expected_hours:
        raise WeatherServiceError("Open-Meteo devolvió menos horas de las solicitadas.")

    return HourlyForecast(
        point=point,
        timezone=str(payload.get("timezone") or "UTC"),
        times=tuple(str(value) for value in times[:expected_hours]),
        precipitation_probability=_number_series(hourly, "precipitation_probability", expected_hours),
        precipitation=_number_series(hourly, "precipitation", expected_hours),
        rain=_number_series(hourly, "rain", expected_hours),
        showers=_number_series(hourly, "showers", expected_hours),
        weather_code=_number_series(hourly, "weather_code", expected_hours, integer=True),
        wind_speed=_number_series(hourly, "wind_speed_10m", expected_hours),
        wind_gusts=_number_series(hourly, "wind_gusts_10m", expected_hours),
    )


def fetch_zone_forecast(settings: Settings, session: requests.Session | None = None) -> list[HourlyForecast]:
    """Obtiene en una sola petición los pronósticos de todos los puntos de la zona."""
    points = build_sample_points(
        settings.latitude, settings.longitude, settings.weather_radius_km
    )
    params = {
        # ``str(float)`` conserva la precisión recibida de Telegram para el
        # punto central, sin imponer el redondeo fijo que usaba el script.
        "latitude": ",".join(str(point.latitude) for point in points),
        "longitude": ",".join(str(point.longitude) for point in points),
        "hourly": HOURLY_VARIABLES,
        "forecast_hours": settings.forecast_hours,
        "timezone": "auto",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }
    client = session or requests.Session()
    try:
        response = client.get(FORECAST_URL, params=params, timeout=settings.request_timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise WeatherServiceError(f"No fue posible consultar Open-Meteo: {exc}") from exc
    except ValueError as exc:
        raise WeatherServiceError("Open-Meteo devolvió JSON inválido.") from exc

    locations = payload if isinstance(payload, list) else [payload]
    if len(locations) != len(points) or not all(isinstance(item, dict) for item in locations):
        raise WeatherServiceError("Open-Meteo devolvió un número inesperado de ubicaciones.")
    return [
        _parse_location(location, point, settings.forecast_hours)
        for location, point in zip(locations, points, strict=True)
    ]
