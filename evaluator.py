"""Reglas de seguridad para convertir un pronóstico de zona en una recomendación."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from weather import HourlyForecast


class Recommendation(IntEnum):
    APTO = 0
    PRECAUCION = 1
    ESPERAR = 2
    TRANSPORTE_ALTERNATIVO = 3


RECOMMENDATION_LABELS = {
    Recommendation.APTO: "🟢 APTO",
    Recommendation.PRECAUCION: "🟡 PRECAUCIÓN",
    Recommendation.ESPERAR: "🟠 ESPERAR",
    Recommendation.TRANSPORTE_ALTERNATIVO: "🔴 TRANSPORTE ALTERNATIVO",
}
THUNDERSTORM_CODES = frozenset({95, 96, 99})


@dataclass(frozen=True)
class ZoneHour:
    time: str
    precipitation_probability: float
    precipitation: float
    rain: float
    showers: float
    weather_codes: frozenset[int]
    wind_speed: float
    wind_gusts: float
    wet_points: tuple[str, ...]


@dataclass(frozen=True)
class DryWindow:
    start: ZoneHour
    end: ZoneHour
    hours: int


@dataclass(frozen=True)
class Assessment:
    timezone: str
    current: ZoneHour
    recommendation: Recommendation
    reasons: tuple[str, ...]
    dry_window: DryWindow | None
    forecast_hours: int


def aggregate_zone(forecasts: Iterable[HourlyForecast]) -> tuple[str, list[ZoneHour]]:
    """Usa el peor valor de cada hora para que un chubasco cercano no se oculte."""
    forecast_list = list(forecasts)
    if not forecast_list:
        raise ValueError("Se requiere al menos un pronóstico para evaluar la zona.")
    hours = len(forecast_list[0].times)
    if not hours or any(len(item.times) != hours for item in forecast_list):
        raise ValueError("Las series horarias tienen longitudes incompatibles.")

    aggregated: list[ZoneHour] = []
    for index in range(hours):
        times = {forecast.times[index] for forecast in forecast_list}
        if len(times) != 1:
            raise ValueError("Los puntos no tienen las mismas marcas de tiempo.")
        wet_points = tuple(
            forecast.point.name
            for forecast in forecast_list
            if forecast.precipitation[index] > 0.1
            or forecast.precipitation_probability[index] >= 30
        )
        aggregated.append(
            ZoneHour(
                time=next(iter(times)),
                precipitation_probability=max(
                    forecast.precipitation_probability[index] for forecast in forecast_list
                ),
                precipitation=max(forecast.precipitation[index] for forecast in forecast_list),
                rain=max(forecast.rain[index] for forecast in forecast_list),
                showers=max(forecast.showers[index] for forecast in forecast_list),
                weather_codes=frozenset(
                    forecast.weather_code[index] for forecast in forecast_list
                ),
                wind_speed=max(forecast.wind_speed[index] for forecast in forecast_list),
                wind_gusts=max(forecast.wind_gusts[index] for forecast in forecast_list),
                wet_points=wet_points,
            )
        )
    return forecast_list[0].timezone, aggregated


def classify(hour: ZoneHour) -> tuple[Recommendation, tuple[str, ...]]:
    """Aplica las reglas del plan en orden de mayor riesgo."""
    reasons: list[str] = []
    if hour.weather_codes & THUNDERSTORM_CODES:
        reasons.append("se pronostica tormenta eléctrica")
    if hour.wind_speed > 45:
        reasons.append(f"viento sostenido de hasta {hour.wind_speed:.0f} km/h")
    if hour.wind_gusts > 60:
        reasons.append(f"ráfagas de hasta {hour.wind_gusts:.0f} km/h")
    if hour.precipitation > 3:
        reasons.append(f"lluvia intensa de hasta {hour.precipitation:.1f} mm/h")
    if reasons:
        return Recommendation.TRANSPORTE_ALTERNATIVO, tuple(reasons)

    if hour.precipitation > 1:
        return Recommendation.ESPERAR, (
            f"lluvia de hasta {hour.precipitation:.1f} mm/h en la zona",
        )
    if hour.precipitation_probability > 60:
        return Recommendation.ESPERAR, (
            f"probabilidad de lluvia de hasta {hour.precipitation_probability:.0f}%",
        )
    if hour.precipitation > 0.1:
        return Recommendation.PRECAUCION, (
            f"lluvia ligera de hasta {hour.precipitation:.1f} mm/h",
        )
    if hour.precipitation_probability >= 30:
        return Recommendation.PRECAUCION, (
            f"probabilidad de lluvia de hasta {hour.precipitation_probability:.0f}%",
        )
    if hour.wind_speed >= 35:
        return Recommendation.PRECAUCION, (
            f"viento de hasta {hour.wind_speed:.0f} km/h",
        )
    return Recommendation.APTO, ("sin lluvia relevante ni viento fuerte",)


def is_dry_and_rideable(hour: ZoneHour) -> bool:
    """Criterio de ventana favorable: seco, baja probabilidad y sin riesgos mayores."""
    recommendation, _ = classify(hour)
    return (
        hour.precipitation <= 0.1
        and hour.precipitation_probability < 30
        and recommendation == Recommendation.APTO
    )


def find_dry_window(hours: list[ZoneHour], required_hours: int) -> DryWindow | None:
    """Busca el primer tramo consecutivo que cumple las condiciones para circular."""
    for start_index in range(0, len(hours) - required_hours + 1):
        candidate = hours[start_index : start_index + required_hours]
        if all(is_dry_and_rideable(hour) for hour in candidate):
            return DryWindow(start=candidate[0], end=candidate[-1], hours=required_hours)
    return None


def evaluate_forecast(
    forecasts: Iterable[HourlyForecast], dry_window_hours: int
) -> Assessment:
    timezone, zone_hours = aggregate_zone(forecasts)
    recommendation, reasons = classify(zone_hours[0])
    return Assessment(
        timezone=timezone,
        current=zone_hours[0],
        recommendation=recommendation,
        reasons=reasons,
        dry_window=find_dry_window(zone_hours, dry_window_hours),
        forecast_hours=len(zone_hours),
    )


def parse_local_time(value: str, timezone: str) -> datetime:
    """Interpreta una marca ISO horaria de Open-Meteo en su zona local."""
    parsed = datetime.fromisoformat(value)
    try:
        return parsed.replace(tzinfo=ZoneInfo(timezone))
    except ZoneInfoNotFoundError:
        return parsed.replace(tzinfo=ZoneInfo("UTC"))
