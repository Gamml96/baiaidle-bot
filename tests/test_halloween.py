import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from baiaidle.halloween import (
    get_halloween_status,
    is_halloween_invasion_open,
    enter_halloween_invasion,
)


class TestHalloween(unittest.IsolatedAsyncioTestCase):
    async def test_get_halloween_status_closed(self):
        tab = MagicMock()
        status_data = {
            "available": True,
            "title": "Halloween",
            "name": "Abóbora Gigante",
            "sub": "Próxima invasão",
            "goal": "Meta 22%",
            "next_time": "16:30",
            "is_open": False,
            "can_enter": False,
            "quota_done": False,
            "has_enter_btn": False,
            "is_dungeon": False,
        }
        tab.execute_script = AsyncMock(return_value={
            "result": {"result": {"value": json.dumps(status_data)}}
        })

        res = await get_halloween_status(tab)
        self.assertTrue(res["available"])
        self.assertFalse(res["is_open"])
        self.assertFalse(res["quota_done"])
        self.assertEqual(res["next_time"], "16:30")

    async def test_is_halloween_invasion_open_true(self):
        tab = MagicMock()
        status_data = {
            "available": True,
            "title": "Halloween",
            "name": "Invasão das Abóboras",
            "sub": "Aberta agora",
            "goal": "Meta 22%",
            "next_time": "16:30",
            "is_open": True,
            "can_enter": True,
            "quota_done": False,
            "has_enter_btn": True,
            "is_dungeon": False,
        }
        tab.execute_script = AsyncMock(return_value={
            "result": {"result": {"value": json.dumps(status_data)}}
        })

        is_open = await is_halloween_invasion_open(tab)
        self.assertTrue(is_open)

    async def test_is_halloween_invasion_closed_when_quota_100(self):
        tab = MagicMock()
        status_data = {
            "available": True,
            "title": "Halloween",
            "name": "Invasão das Abóboras",
            "sub": "Invasão aberta",
            "goal": "Meta 24%",
            "closes_in": "8min",
            "quota_text": "100/100",
            "kills": 100,
            "quota": 100,
            "quota_done": True,
            "is_open": True,
            "can_enter": False,
            "has_enter_btn": False,
            "is_dungeon": False,
        }
        tab.execute_script = AsyncMock(return_value={
            "result": {"result": {"value": json.dumps(status_data)}}
        })

        is_open = await is_halloween_invasion_open(tab)
        self.assertFalse(is_open)

    async def test_enter_halloween_invasion_aborts_when_quota_done(self):
        tab = MagicMock()
        status_data = {
            "quota_text": "100/100",
            "quota_done": True,
            "can_enter": False,
        }
        tab.execute_script = AsyncMock(return_value={
            "result": {"result": {"value": json.dumps(status_data)}}
        })

        success, msg = await enter_halloween_invasion(tab)
        self.assertFalse(success)
        self.assertIn("já cumprida", msg)

    async def test_enter_halloween_invasion_success(self):
        tab = MagicMock()
        # Mock 1: get_halloween_status, Mock 2: click hud enter, Mock 3: confirm yes
        tab.execute_script = AsyncMock(side_effect=[
            {"result": {"result": {"value": json.dumps({"quota_done": False, "can_enter": True})}}},
            {"result": {"result": {"value": "clicked_hud_enter"}}},
            {"result": {"result": {"value": True}}},
            {"result": {"result": {"value": True}}},
        ])

        messages = []
        async def on_message(msg):
            messages.append(msg)

        success, msg = await enter_halloween_invasion(tab, on_message=on_message)
        self.assertTrue(success)
        self.assertEqual(msg, "iniciada")
        self.assertTrue(any("Invasão das Abóboras" in m for m in messages))


if __name__ == "__main__":
    unittest.main()
