"""Punto de entrada de Weather Moto."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import datetime
from html import escape
from typing import Any

from config import ConfigurationError, Settings, load_settings
from evaluator import (
    Assessment,
    RECOMMENDATION_LABELS,
    Recommendation,
    evaluate_forecast,
    parse_local_time,
)
from telegram import TelegramError, get_updates, send_message
from weather import WeatherServiceError, fetch_zone_forecast


SAFETY_NOTICE = "Orientativo; verifica las condiciones reales antes de salir."
LOCATION_KEYBOARD = {
    "keyboard": [[{"text": "📍 Compartir mi ubicación", "request_location": True}]],
    "resize_keyboard": True,
    "one_time_keyboard": True,
}
REMOVE_KEYBOARD = {"remove_keyboard": True}


def _format_hour(value: str, timezone: str) -> str:
    return parse_local_time(value, timezone).strftime("%H:%M")


def _format_wait(assessment: Assessment) -> str:
    window = assessment.dry_window
    if window is None:
        return "No se identifica una ventana seca dentro del horizonte analizado."

    starts_at = parse_local_time(window.start.time, assessment.timezone)
    now = datetime.now(starts_at.tzinfo)
    minutes = max(0, round((starts_at - now).total_seconds() / 60))
    time_label = _format_hour(window.start.time, assessment.timezone)
    if minutes == 0:
        return f"Ventana favorable desde aproximadamente las {time_label}."
    hours, remaining_minutes = divmod(minutes, 60)
    delay = (
        f"{hours} h {remaining_minutes:02d} min"
        if hours
        else f"{remaining_minutes} min"
    )
    return f"Ventana favorable aproximadamente a las {time_label}; esperar ~{delay}."


def format_assessment(
    assessment: Assessment,
    *,
    html: bool = False,
    coordinates: tuple[float, float] | None = None,
) -> str:
    """Construye el informe breve que se imprime y, si aplica, se manda por Telegram."""
    current = assessment.current
    label = RECOMMENDATION_LABELS[assessment.recommendation]
    location = ""
    if coordinates is not None:
        latitude, longitude = coordinates
        location = f"Ubicación analizada: {latitude:.6f}, {longitude:.6f}\n"
    details = location + (
        f"Hora analizada: {_format_hour(current.time, assessment.timezone)} ({assessment.timezone})\n"
        f"Lluvia máxima en la zona: {current.precipitation:.1f} mm/h · "
        f"Probabilidad máxima: {current.precipitation_probability:.0f}%\n"
        f"Viento: {current.wind_speed:.0f} km/h · Ráfagas: {current.wind_gusts:.0f} km/h\n"
        f"Motivo: {'; '.join(assessment.reasons)}\n"
        f"{_format_wait(assessment)}\n\n"
        f"🏍️ Moto: {label}\n"
        f"🚗 Transporte alternativo: "
        f"{'RECOMENDADO si necesitas salir ahora' if assessment.recommendation >= Recommendation.ESPERAR else 'no necesario por el pronóstico actual'}\n\n"
        f"⚠️ {SAFETY_NOTICE}"
    )
    if html:
        # Sólo se insertan valores locales controlados; se escapa la cadena por defensa adicional.
        return "<b>Clima para moto</b>\n\n" + escape(details)
    return f"CLIMA PARA MOTO\n\n{details}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evalúa si es prudente salir en moto en una zona cercana."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--no-telegram",
        action="store_true",
        help="No envía Telegram incluso si las credenciales están configuradas.",
    )
    mode.add_argument(
        "--listen-telegram",
        action="store_true",
        help="Escucha ubicaciones enviadas al bot y responde con su análisis.",
    )
    return parser.parse_args()


def run(settings: Settings, *, send_to_telegram: bool) -> Assessment:
    forecasts = fetch_zone_forecast(settings)
    assessment = evaluate_forecast(forecasts, settings.dry_window_hours)
    message = format_assessment(assessment)
    print(message)

    if send_to_telegram:
        assert settings.telegram_bot_token is not None
        assert settings.telegram_chat_id is not None
        send_message(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            text=format_assessment(assessment, html=True),
            timeout_seconds=settings.request_timeout_seconds,
        )
        print("\nMensaje enviado a Telegram.")
    elif not settings.telegram_configured:
        print("\nTelegram no está configurado; sólo se mostró el informe en consola.")
    return assessment


def _coordinates_from_location(location: Any) -> tuple[float, float]:
    """Valida las coordenadas WGS84 recibidas dentro de un mensaje de Telegram."""
    if not isinstance(location, dict):
        raise ValueError("La ubicación recibida no tiene el formato esperado.")
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if (
        isinstance(latitude, bool)
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or not isinstance(longitude, (int, float))
    ):
        raise ValueError("La ubicación recibida no contiene coordenadas numéricas.")
    latitude, longitude = float(latitude), float(longitude)
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("La ubicación recibida está fuera de los límites WGS84.")
    return latitude, longitude


def _location_analysis_message(settings: Settings, latitude: float, longitude: float) -> str:
    """Ejecuta el análisis usando la ubicación enviada, sin alterar la configuración base."""
    location_settings = replace(settings, latitude=latitude, longitude=longitude)
    forecasts = fetch_zone_forecast(location_settings)
    assessment = evaluate_forecast(forecasts, location_settings.dry_window_hours)
    return format_assessment(
        assessment,
        html=True,
        coordinates=(latitude, longitude),
    )


def _message_chat_id(message: dict[str, Any]) -> str | None:
    chat = message.get("chat")
    if not isinstance(chat, dict) or "id" not in chat:
        return None
    chat_id = chat["id"]
    if isinstance(chat_id, bool) or not isinstance(chat_id, (int, str)):
        return None
    return str(chat_id)


def process_telegram_update(settings: Settings, update: dict[str, Any]) -> bool:
    """Procesa un mensaje de Telegram y devuelve si contenía una ubicación válida.

    El ``TELEGRAM_CHAT_ID`` funciona como lista de acceso: se descartan por
    completo los mensajes de otros chats para no exponer el bot a terceros.
    """
    message = update.get("message")
    if not isinstance(message, dict):
        return False
    chat_id = _message_chat_id(message)
    if chat_id != settings.telegram_chat_id:
        return False
    assert settings.telegram_bot_token is not None

    location = message.get("location")
    if location is not None:
        try:
            latitude, longitude = _coordinates_from_location(location)
        except ValueError as exc:
            send_message(
                bot_token=settings.telegram_bot_token,
                chat_id=chat_id,
                text=f"<b>No pude usar esa ubicación.</b>\n{escape(str(exc))}",
                reply_markup=REMOVE_KEYBOARD,
                timeout_seconds=settings.request_timeout_seconds,
            )
            return False

        send_message(
            bot_token=settings.telegram_bot_token,
            chat_id=chat_id,
            text="<b>Analizando tu ubicación…</b>",
            reply_markup=REMOVE_KEYBOARD,
            timeout_seconds=settings.request_timeout_seconds,
        )
        try:
            report = _location_analysis_message(settings, latitude, longitude)
        except (WeatherServiceError, ValueError) as exc:
            send_message(
                bot_token=settings.telegram_bot_token,
                chat_id=chat_id,
                text=f"<b>No pude completar el análisis.</b>\n{escape(str(exc))}",
                timeout_seconds=settings.request_timeout_seconds,
            )
            return False
        send_message(
            bot_token=settings.telegram_bot_token,
            chat_id=chat_id,
            text=report,
            timeout_seconds=settings.request_timeout_seconds,
        )
        return True

    text = message.get("text")
    if not isinstance(text, str):
        return False
    command = ""
    if text.strip():
        command = text.strip().split(maxsplit=1)[0].split("@", maxsplit=1)[0].lower()
    if command in {"/start", "/ubicacion", "/location"}:
        send_message(
            bot_token=settings.telegram_bot_token,
            chat_id=chat_id,
            text=(
                "Comparte tu ubicación para analizar el clima de la zona donde estás.\n\n"
                "Telegram enviará las coordenadas GPS que autorices; no se usa la ubicación "
                "configurada en <code>.env</code> para esta consulta."
            ),
            reply_markup=LOCATION_KEYBOARD,
            timeout_seconds=settings.request_timeout_seconds,
        )
    return False


def listen_for_locations(settings: Settings) -> None:
    """Mantiene un long poll y responde a ubicaciones del chat autorizado."""
    if not settings.telegram_configured:
        raise ConfigurationError(
            "--listen-telegram requiere TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID."
        )
    assert settings.telegram_bot_token is not None

    next_update_id: int | None = None
    print("Escuchando ubicaciones de Telegram. Detén el proceso con Ctrl+C.")
    while True:
        updates = get_updates(
            settings.telegram_bot_token,
            offset=next_update_id,
            timeout_seconds=settings.telegram_poll_timeout_seconds,
        )
        for update in updates:
            update_id = update.get("update_id")
            if not isinstance(update_id, int) or isinstance(update_id, bool):
                continue
            process_telegram_update(settings, update)
            next_update_id = update_id + 1


def main() -> int:
    args = parse_args()
    try:
        settings = load_settings()
        if args.listen_telegram:
            listen_for_locations(settings)
            return 0
        run(settings, send_to_telegram=settings.telegram_configured and not args.no_telegram)
    except (ConfigurationError, WeatherServiceError, TelegramError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
