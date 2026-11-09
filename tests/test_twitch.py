import json
import unittest
from unittest.mock import AsyncMock, patch

from baiaidle import twitch


class TestTwitchLoginExtraction(unittest.TestCase):
    def test_extract_from_thumbnail(self):
        src = "https://static-cdn.jtvnw.net/previews-ttv/live_user_SomeStreamer-320x180.jpg"
        self.assertEqual(twitch.extract_login_from_preview(src), "somestreamer")

    def test_extract_with_query_string(self):
        src = "https://static-cdn.jtvnw.net/previews-ttv/live_user_abc_123-560x315.jpg?t=123"
        self.assertEqual(twitch.extract_login_from_preview(src), "abc_123")

    def test_extract_ignores_non_preview_urls(self):
        self.assertIsNone(twitch.extract_login_from_preview(""))
        self.assertIsNone(twitch.extract_login_from_preview("https://example.com/a.jpg"))

    def test_extract_never_returns_generic_word(self):
        # O falso positivo antigo: a palavra "Twitch" de um texto qualquer.
        self.assertIsNone(twitch.extract_login_from_preview("Twitch"))


class TestPickLive(unittest.TestCase):
    def test_picks_first_active_live(self):
        lives = [
            {"login": "parceiro", "off": False, "afk": False, "partner": True},
            {"login": "outro", "off": False, "afk": False, "partner": False},
        ]
        self.assertEqual(twitch.pick_live(lives)["login"], "parceiro")

    def test_skips_drop_ended(self):
        lives = [
            {"login": "esgotada", "off": True, "afk": False},
            {"login": "valida", "off": False, "afk": False},
        ]
        self.assertEqual(twitch.pick_live(lives)["login"], "valida")

    def test_prefers_non_afk(self):
        lives = [
            {"login": "afk", "off": False, "afk": True},
            {"login": "ativa", "off": False, "afk": False},
        ]
        self.assertEqual(twitch.pick_live(lives)["login"], "ativa")

    def test_falls_back_to_afk_if_only_option(self):
        lives = [{"login": "afk", "off": False, "afk": True}]
        self.assertEqual(twitch.pick_live(lives)["login"], "afk")

    def test_returns_none_without_valid_lives(self):
        self.assertIsNone(twitch.pick_live([]))
        self.assertIsNone(twitch.pick_live([{"login": "x", "off": True}]))

    def test_requires_login(self):
        self.assertIsNone(twitch.pick_live([{"login": "", "off": False}]))


class TestNormalizeToken(unittest.TestCase):
    def test_strips_oauth_prefix(self):
        self.assertEqual(twitch.normalize_token("oauth:abc"), "abc")
        self.assertEqual(twitch.normalize_token("OAUTH:abc"), "abc")

    def test_keeps_plain_token(self):
        self.assertEqual(twitch.normalize_token(" abc "), "abc")


class TestValidateToken(unittest.TestCase):
    def test_empty_token(self):
        ok, msg = twitch.validate_token("")
        self.assertFalse(ok)
        self.assertIn("vazio", msg.lower())

    def test_invalid_token_returns_login(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps({"login": "minhaconta"}).encode()

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            ok, login = twitch.validate_token("oauth:abc")
        self.assertTrue(ok)
        self.assertEqual(login, "minhaconta")


class FakeTab:
    def __init__(self, value):
        self.value = value
        self.scripts = []

    async def execute_script(self, script):
        self.scripts.append(script)
        return {"result": {"result": {"value": self.value}}}


class TestGetTwitchLives(unittest.IsolatedAsyncioTestCase):
    async def test_reads_tiles_payload(self):
        payload = {
            "found": True,
            "lives": [
                {"login": "canal", "name": "Canal", "title": "Baiak", "off": False,
                 "afk": False, "partner": True, "meta": "drop por mais 1 h"},
            ],
        }
        tab = FakeTab(json.dumps(payload))
        with patch.object(twitch, "open_twitch_modal", AsyncMock(return_value=True)), \
             patch.object(twitch, "close_twitch_modal", AsyncMock()) as close_mock:
            data = await twitch.get_twitch_lives(tab)

        self.assertTrue(data["found"])
        self.assertEqual(data["lives"][0]["login"], "canal")
        close_mock.assert_awaited_once()

    async def test_returns_empty_when_modal_does_not_open(self):
        tab = FakeTab("")
        with patch.object(twitch, "open_twitch_modal", AsyncMock(return_value=False)), \
             patch.object(twitch, "close_twitch_modal", AsyncMock()):
            data = await twitch.get_twitch_lives(tab)

        self.assertFalse(data["found"])
        self.assertEqual(data["lives"], [])

    async def test_choose_uses_best_live(self):
        payload = {
            "found": True,
            "lives": [
                {"login": "esgotada", "off": True, "afk": False},
                {"login": "valida", "off": False, "afk": False},
            ],
        }
        tab = FakeTab(json.dumps(payload))
        with patch.object(twitch, "open_twitch_modal", AsyncMock(return_value=True)), \
             patch.object(twitch, "close_twitch_modal", AsyncMock()):
            channel = await twitch.choose_twitch_live(tab)

        self.assertEqual(channel, "valida")


if __name__ == "__main__":
    unittest.main()
