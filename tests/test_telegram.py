"""Pruebas del cliente HTTP de Telegram sin llamadas de red."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from telegram import TelegramError, get_updates, send_message


class TelegramClientTests(unittest.TestCase):
    def _session_with_payload(self, payload: object) -> Mock:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        session = Mock()
        session.post.return_value = response
        return session

    def test_get_updates_uses_long_polling_and_offset(self) -> None:
        session = self._session_with_payload(
            {"ok": True, "result": [{"update_id": 42, "message": {}}]}
        )

        updates = get_updates(
            "token",
            offset=42,
            timeout_seconds=30,
            session=session,
        )

        self.assertEqual(updates, [{"update_id": 42, "message": {}}])
        _, kwargs = session.post.call_args
        self.assertEqual(kwargs["json"], {
            "timeout": 30,
            "allowed_updates": ["message"],
            "offset": 42,
        })
        self.assertEqual(kwargs["timeout"], 35)

    def test_send_message_includes_location_keyboard(self) -> None:
        session = self._session_with_payload({"ok": True, "result": {}})
        keyboard = {"keyboard": [[{"request_location": True}]]}

        send_message(
            "token",
            "123",
            "Comparte tu ubicación",
            reply_markup=keyboard,
            session=session,
        )

        _, kwargs = session.post.call_args
        self.assertEqual(kwargs["json"]["chat_id"], "123")
        self.assertEqual(kwargs["json"]["reply_markup"], keyboard)

    def test_get_updates_rejects_invalid_results(self) -> None:
        session = self._session_with_payload({"ok": True, "result": {}})

        with self.assertRaises(TelegramError):
            get_updates("token", session=session)


if __name__ == "__main__":
    unittest.main()
