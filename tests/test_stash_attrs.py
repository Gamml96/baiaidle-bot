import unittest
from unittest.mock import AsyncMock, patch

from baiaidle.actions import stash_valuable_items
from baiaidle.settings import get_setting, set_setting, load_settings, save_settings


class TestStashAttributes(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Save previous stash_attributes setting
        self.prev_attrs = get_setting("stash_attributes", [])

    def tearDown(self):
        set_setting("stash_attributes", self.prev_attrs)

    async def test_stash_valuable_items_with_attributes(self):
        page = AsyncMock()
        mock_result = {
            "stashed": 2,
            "items": [
                "Boots of Haste (Tier 2 · Exp +1%)",
                "Demon Armor (Tier 3 · Onslaught +0.5%)",
            ]
        }
        page.execute_script.return_value = {"result": {"result": {"value": str(mock_result).replace("'", '"')}}}

        res = await stash_valuable_items(page, min_tier=4, target_attributes=["exp", "onslaught"])
        self.assertEqual(res["stashed"], 2)
        self.assertEqual(len(res["items"]), 2)
        self.assertIn("Boots of Haste (Tier 2 · Exp +1%)", res["items"])
        self.assertIn("Demon Armor (Tier 3 · Onslaught +0.5%)", res["items"])

        # Check that js string sent to execute_script contains targetAttrs
        executed_js = page.execute_script.call_args[0][0]
        self.assertIn('"exp"', executed_js)
        self.assertIn('"onslaught"', executed_js)
        self.assertIn("attrMap", executed_js)

    def test_settings_stash_attributes(self):
        set_setting("stash_attributes", ["exp", "onslaught", "crit damage"])
        settings = load_settings()
        self.assertEqual(settings.get("stash_attributes"), ["exp", "onslaught", "crit damage"])

        # Clean
        set_setting("stash_attributes", [])
        settings = load_settings()
        self.assertEqual(settings.get("stash_attributes"), [])


if __name__ == "__main__":
    unittest.main()

