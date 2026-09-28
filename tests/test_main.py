"""Pruebas del flujo de ubicación compartida desde Telegram."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from config import Settings
from evaluator import Assessment, Recommendation, ZoneHour
from main import LOCATION_KEYBOARD, _coordinates_from_location, process_telegram_update


def _settings() -> Settings:
    return Settings(
        latitude=19.4326,
        longitude=-99.1332,
        telegram_bot_token="token",
        telegram_chat_id="123",
    )


def _assessment() -> Assessment:
    current = ZoneHour(
        time="2026-09-27T12:00",
        precipitation_probability=10,
        precipitation=0,
        rain=0,
        showers=0,
        weather_codes=frozenset(),
        wind_speed=10,
        wind_gusts=15,
        wet_points=(),
    )
    return Assessment(
        timezone="UTC",
        current=current,
        recommendation=Recommendation.APTO,
        reasons=("sin lluvia relevante ni viento fuerte",),
        dry_window=None,
        forecast_hours=8,
    )


class TelegramLocationFlowTests(unittest.TestCase):
    def test_start_requests_location_with_native_button(self) -> None:
        update = {"message": {"chat": {"id": 123}, "text": "/start"}}
        with patch("main.send_message") as send_message:
            processed = process_telegram_update(_settings(), update)

        self.assertFalse(processed)
        self.assertEqual(send_message.call_args.kwargs["reply_markup"], LOCATION_KEYBOARD)

    @patch("main.evaluate_forecast", return_value=_assessment())
    @patch("main.fetch_zone_forecast", return_value=[])
    @patch("main.send_message")
    def test_location_uses_coordinates_received_from_telegram(
        self, send_message, fetch_zone_forecast, _evaluate_forecast
    ) -> None:
        update = {
            "message": {
                "chat": {"id": 123},
                "location": {"latitude": 19.432654, "longitude": -99.133278},
            }
        }

        processed = process_telegram_update(_settings(), update)

        self.assertTrue(processed)
        used_settings = fetch_zone_forecast.call_args.args[0]
        self.assertEqual(used_settings.latitude, 19.432654)
        self.assertEqual(used_settings.longitude, -99.133278)
        self.assertEqual(send_message.call_count, 2)
        self.assertIn(
            "19.432654, -99.133278", send_message.call_args_list[-1].kwargs["text"]
        )

    @patch("main.send_message")
    def test_ignores_an_unauthorized_chat(self, send_message) -> None:
        update = {
            "message": {
                "chat": {"id": 999},
                "location": {"latitude": 19.4, "longitude": -99.1},
            }
        }

        self.assertFalse(process_telegram_update(_settings(), update))
        send_message.assert_not_called()

    def test_location_coordinates_must_be_wgs84(self) -> None:
        with self.assertRaisesRegex(ValueError, "límites WGS84"):
            _coordinates_from_location({"latitude": 91, "longitude": 0})


if __name__ == "__main__":
    unittest.main()
