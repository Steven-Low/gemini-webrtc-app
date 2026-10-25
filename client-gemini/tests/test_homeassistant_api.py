"""Unit tests for Home Assistant service calls (all HTTP requests are mocked)."""

import os
import unittest
from unittest.mock import Mock, patch

from app.services import homeassistant_api


class HomeAssistantApiTests(unittest.TestCase):
    @patch.dict(os.environ, {"HASS_API_KEY": "unit-test-token"}, clear=True)
    @patch("app.services.homeassistant_api.requests.post")
    def test_turn_on_light_posts_expected_service_call(self, post):
        post.return_value = Mock(ok=True, status_code=200)

        result = homeassistant_api.turn_on_light()

        self.assertEqual(result, 200)
        post.assert_called_once_with(
            "http://10.10.10.142:8123/api/services/switch/turn_on",
            headers={
                "Authorization": "Bearer unit-test-token",
                "Content-Type": "application/json",
            },
            json={"entity_id": "switch.power_monitor_switch_1"},
            timeout=10,
        )

    @patch.dict(
        os.environ,
        {"HASS_API_KEY": "unit-test-token", "HASS_URL": "http://ha.local/"},
        clear=True,
    )
    @patch("app.services.homeassistant_api.requests.post")
    def test_turn_off_light_uses_configured_url(self, post):
        post.return_value = Mock(ok=True, status_code=200)

        result = homeassistant_api.turn_off_light()

        self.assertEqual(result, 200)
        self.assertEqual(
            post.call_args.args[0],
            "http://ha.local/api/services/switch/turn_off",
        )
        self.assertEqual(post.call_args.kwargs["json"], {
            "entity_id": "switch.power_monitor_switch_1"
        })

    @patch.dict(os.environ, {}, clear=True)
    @patch("app.services.homeassistant_api.requests.post")
    def test_missing_token_returns_error_without_request(self, post):
        result = homeassistant_api.turn_on_light()

        self.assertEqual(result, "HASS_API_KEY is not configured")
        post.assert_not_called()

    @patch.dict(os.environ, {"HASS_API_KEY": "unit-test-token"}, clear=True)
    @patch("app.services.homeassistant_api.requests.post")
    def test_http_error_returns_response_body(self, post):
        post.return_value = Mock(ok=False, text="unauthorized")

        result = homeassistant_api.turn_off_light()

        self.assertEqual(result, "unauthorized")


if __name__ == "__main__":
    unittest.main()
