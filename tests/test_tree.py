import unittest
from unittest.mock import AsyncMock, patch

from baiaidle.tree import (
    SORCERER_PRIORITY,
    KNIGHT_PRIORITY,
    DRUID_PRIORITY,
    PALADIN_PRIORITY,
    get_priority_for_vocation,
    get_tree_status,
    auto_allocate_character_points,
    run_auto_tree,
)


class TestTreePriorities(unittest.TestCase):
    def test_vocation_priorities_capstones(self):
        # MS capstones & key damage
        self.assertIn("Avatar of Storm", SORCERER_PRIORITY)
        self.assertIn("Momentum", SORCERER_PRIORITY)
        self.assertIn("Lord of Destruction", SORCERER_PRIORITY)
        self.assertIn("Arcane Power", SORCERER_PRIORITY)

        # EK capstones & defense
        self.assertIn("Avatar of Steel", KNIGHT_PRIORITY)
        self.assertIn("Gift of Life", KNIGHT_PRIORITY)
        self.assertIn("Colossus", KNIGHT_PRIORITY)
        self.assertIn("Bulwark", KNIGHT_PRIORITY)

        # ED capstones & heal/magic
        self.assertIn("Avatar of Nature", DRUID_PRIORITY)
        self.assertIn("Gift of Life", DRUID_PRIORITY)
        self.assertIn("Hail Storm", DRUID_PRIORITY)
        self.assertIn("Wrath of Nature", DRUID_PRIORITY)

        # RP capstones & distance/crit
        self.assertIn("Avatar of Light", PALADIN_PRIORITY)
        self.assertIn("Sharpshooter", PALADIN_PRIORITY)
        self.assertIn("Positional Tactics", PALADIN_PRIORITY)
        self.assertIn("Culling Shot", PALADIN_PRIORITY)

    def test_get_priority_for_vocation(self):
        self.assertEqual(get_priority_for_vocation("Royal MS"), SORCERER_PRIORITY)
        self.assertEqual(get_priority_for_vocation("Master Sorcerer"), SORCERER_PRIORITY)
        self.assertEqual(get_priority_for_vocation("MS"), SORCERER_PRIORITY)

        self.assertEqual(get_priority_for_vocation("Royal Tyr"), KNIGHT_PRIORITY)
        self.assertEqual(get_priority_for_vocation("Elite Knight"), KNIGHT_PRIORITY)
        self.assertEqual(get_priority_for_vocation("EK"), KNIGHT_PRIORITY)

        self.assertEqual(get_priority_for_vocation("Royal Eir"), DRUID_PRIORITY)
        self.assertEqual(get_priority_for_vocation("Elder Druid"), DRUID_PRIORITY)
        self.assertEqual(get_priority_for_vocation("ED"), DRUID_PRIORITY)

        self.assertEqual(get_priority_for_vocation("Royal Paladin"), PALADIN_PRIORITY)
        self.assertEqual(get_priority_for_vocation("Paladin"), PALADIN_PRIORITY)
        self.assertEqual(get_priority_for_vocation("RP"), PALADIN_PRIORITY)
        self.assertEqual(get_priority_for_vocation(char_index=3), PALADIN_PRIORITY)


class TestTreeExecution(unittest.IsolatedAsyncioTestCase):
    async def test_get_tree_status(self):
        page = AsyncMock()
        mock_data = [
            {"index": 0, "title": "Royal MS", "points": 5, "spent": 20},
            {"index": 1, "title": "Royal Tyr", "points": 0, "spent": 25},
            {"index": 2, "title": "Royal Eir", "points": 2, "spent": 23},
        ]
        page.execute_script.return_value = {"result": {"result": {"value": mock_data}}}

        status = await get_tree_status(page)
        self.assertEqual(len(status), 3)
        self.assertEqual(status[0]["points"], 5)
        self.assertEqual(status[1]["points"], 0)
        self.assertEqual(status[2]["points"], 2)

    async def test_auto_allocate_character_points(self):
        page = AsyncMock()
        mock_res = {
            "initialPts": 3,
            "finalPts": 0,
            "allocated": ["Arcane Power", "Arcane Power", "Arcane Focus"],
            "okText": "Confirmar (3)",
        }
        page.execute_script.return_value = {"result": {"result": {"value": mock_res}}}

        res = await auto_allocate_character_points(page, char_index=0, vocation="Royal MS")
        self.assertEqual(res["initialPts"], 3)
        self.assertEqual(res["finalPts"], 0)
        self.assertEqual(len(res["allocated"]), 3)

    @patch("baiaidle.tree.get_setting")
    async def test_run_auto_tree_disabled(self, mock_get_setting):
        mock_get_setting.return_value = False
        page = AsyncMock()

        res = await run_auto_tree(page)
        self.assertFalse(res["enabled"])
        self.assertEqual(res["allocated_total"], 0)

    @patch("baiaidle.tree.get_setting")
    async def test_run_auto_tree_enabled_allocates(self, mock_get_setting):
        mock_get_setting.return_value = True
        page = AsyncMock()
        mock_tree_res = {
            "allocatedTotal": 2,
            "details": [
                {
                    "title": "Royal MS",
                    "spent": 2,
                    "finalPts": 0,
                    "nodes": ["Arcane Power", "Arcane Focus"],
                }
            ],
        }
        page.execute_script.return_value = {"result": {"result": {"value": mock_tree_res}}}

        res = await run_auto_tree(page)
        self.assertTrue(res["enabled"])
        self.assertEqual(res["allocated_total"], 2)
        self.assertEqual(len(res["details"]), 1)
        self.assertEqual(res["details"][0]["title"], "Royal MS")
        self.assertEqual(res["details"][0]["spent"], 2)


if __name__ == "__main__":
    unittest.main()
