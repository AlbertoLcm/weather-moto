"""Cliente mínimo para enviar mensajes y recibir actualizaciones de Telegram."""

from __future__ import annotations

from html import escape
from typing import Any

import requests


class TelegramError(RuntimeError):
    """Telegram no aceptó el mensaje solicitado."""


def _request(
    bot_token: str,
    method: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
    session: requests.Session | None,
) -> Any:
    """Ejecuta una llamada a Bot API y devuelve su campo ``result``."""
    endpoint = f"https://api.telegram.org/bot{bot_token}/{method}"
    client = session or requests.Session()
    try:
        response = client.post(endpoint, json=payload, timeout=timeout_seconds)
        response.raise_for_status()
        response_payload = response.json()
    except requests.RequestException as exc:
        raise TelegramError(f"No fue posible llamar a Telegram: {exc}") from exc
    except ValueError as exc:
        raise TelegramError("Telegram devolvió JSON inválido.") from exc

    if not isinstance(response_payload, dict) or not response_payload.get("ok"):
        description = "error desconocido"
        if isinstance(response_payload, dict):
            description = str(response_payload.get("description", description))
        raise TelegramError(f"Telegram rechazó la solicitud: {escape(description)}")
    return response_payload.get("result")


def send_message(
    bot_token: str,
    chat_id: str,
    text: str,
    timeout_seconds: float = 15.0,
    reply_markup: dict[str, Any] | None = None,
    session: requests.Session | None = None,
) -> None:
    """Envía un mensaje HTML, respetando el límite de 4096 caracteres de Telegram."""
    if len(text) > 4096:
        raise TelegramError("El mensaje excede el límite de 4096 caracteres de Telegram.")
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    _request(
        bot_token,
        "sendMessage",
        payload,
        timeout_seconds=timeout_seconds,
        session=session,
    )


def get_updates(
    bot_token: str,
    *,
    offset: int | None = None,
    timeout_seconds: int = 30,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Recibe mensajes nuevos mediante long polling.

    ``offset`` debe ser el siguiente ``update_id`` no procesado, tal como lo
    define Telegram. Sólo se solicitan mensajes porque son los únicos eventos
    que necesita este bot para recibir una ubicación.
    """
    if not 1 <= timeout_seconds <= 50:
        raise ValueError("timeout_seconds debe estar entre 1 y 50.")
    if offset is not None and offset < 0:
        raise ValueError("offset no puede ser negativo.")

    payload: dict[str, Any] = {
        "timeout": timeout_seconds,
        "allowed_updates": ["message"],
    }
    if offset is not None:
        payload["offset"] = offset
    result = _request(
        bot_token,
        "getUpdates",
        payload,
        # El servidor puede mantener la petición abierta durante todo el long
        # poll; se reserva margen para la conexión y la respuesta HTTP.
        timeout_seconds=timeout_seconds + 5,
        session=session,
    )
    if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
        raise TelegramError("Telegram devolvió actualizaciones inválidas.")
    return result
