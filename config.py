"""Carga y validación de la configuración de Weather Moto."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """La configuración local está ausente o contiene valores no válidos."""


@dataclass(frozen=True)
class Settings:
    latitude: float
    longitude: float
    weather_radius_km: float = 5.0
    forecast_hours: int = 8
    dry_window_hours: int = 2
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_poll_timeout_seconds: int = 30
    request_timeout_seconds: float = 15.0

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def _required_float(name: str) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ConfigurationError(f"Falta la variable obligatoria {name} en .env.")
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} debe ser un número válido.") from exc


def _positive_float(name: str, default: float) -> float:
    value = os.getenv(name, str(default))
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} debe ser un número válido.") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{name} debe ser mayor que cero.")
    return parsed


def _positive_int(name: str, default: int) -> int:
    value = os.getenv(name, str(default))
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} debe ser un entero válido.") from exc
    if parsed <= 0:
        raise ConfigurationError(f"{name} debe ser mayor que cero.")
    return parsed


def load_settings() -> Settings:
    """Lee ``.env`` y las variables del proceso, validándolas antes de usar la API."""
    load_dotenv(override=False)

    latitude = _required_float("LATITUDE")
    longitude = _required_float("LONGITUDE")
    if not -90 <= latitude <= 90:
        raise ConfigurationError("LATITUDE debe estar entre -90 y 90.")
    if not -180 <= longitude <= 180:
        raise ConfigurationError("LONGITUDE debe estar entre -180 y 180.")

    radius = _positive_float("WEATHER_RADIUS_KM", 5.0)
    if radius > 50:
        raise ConfigurationError("WEATHER_RADIUS_KM no puede superar 50 km.")

    forecast_hours = _positive_int("FORECAST_HOURS", 8)
    if forecast_hours > 168:
        raise ConfigurationError("FORECAST_HOURS no puede superar 168 horas.")

    dry_window_hours = _positive_int("DRY_WINDOW_HOURS", 2)
    if dry_window_hours > forecast_hours:
        raise ConfigurationError("DRY_WINDOW_HOURS no puede exceder FORECAST_HOURS.")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or None
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip() or None
    if bool(token) != bool(chat_id):
        raise ConfigurationError(
            "TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID deben configurarse juntos."
        )

    poll_timeout = _positive_int("TELEGRAM_POLL_TIMEOUT_SECONDS", 30)
    if poll_timeout > 50:
        raise ConfigurationError(
            "TELEGRAM_POLL_TIMEOUT_SECONDS no puede superar 50 segundos."
        )

    return Settings(
        latitude=latitude,
        longitude=longitude,
        weather_radius_km=radius,
        forecast_hours=forecast_hours,
        dry_window_hours=dry_window_hours,
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
        telegram_poll_timeout_seconds=poll_timeout,
        request_timeout_seconds=_positive_float("REQUEST_TIMEOUT_SECONDS", 15.0),
    )
