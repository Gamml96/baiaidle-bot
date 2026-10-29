import unittest
from unittest.mock import AsyncMock, patch, MagicMock
from baiaidle.hunts import (
    load_hunts_cache,
    save_hunts_cache,
    get_hunt_info,
    get_hunt_level,
    is_hunt_level_safe,
    get_hunts_list,
)
import baiaidle.hunts as hunts_mod

class TestHuntsCache(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Garante que o cache em memória seja limpo antes de cada teste
        hunts_mod._cached_hunts = None

    def tearDown(self):
        hunts_mod._cached_hunts = None

    def test_load_hunts_cache(self):
        cache = load_hunts_cache()
        self.assertIsInstance(cache, list)
        self.assertGreaterEqual(len(cache), 80)
        
        # Verifica se o primeiro item é Troll Cave com level 1
        first = cache[0]
        self.assertEqual(first["name"], "Troll Cave")
        self.assertEqual(first["level"], 1)

    def test_get_hunt_info(self):
        info = get_hunt_info("Troll Cave")
        self.assertIsNotNone(info)
        self.assertEqual(info["name"], "Troll Cave")
        self.assertEqual(info["level"], 1)

        # Case-insensitive
        info_lower = get_hunt_info("troll cave")
        self.assertEqual(info_lower, info)

        # Inexistente
        info_none = get_hunt_info("Hunt Fake 999")
        self.assertIsNone(info_none)

    def test_get_hunt_level(self):
        self.assertEqual(get_hunt_level("Troll Cave"), 1)
        self.assertEqual(get_hunt_level("Elf"), 8)
        self.assertEqual(get_hunt_level("Elf (facil)"), 8)
        self.assertEqual(get_hunt_level("elf (fácil)"), 8)
        self.assertEqual(get_hunt_level("amazon-camp"), 9)
        self.assertEqual(get_hunt_level("Hydra"), 100)
        self.assertEqual(get_hunt_level("Grim Reaper"), 130)
        self.assertEqual(get_hunt_level("darkthais"), 800)
        self.assertEqual(get_hunt_level("Dark Thais"), 800)
        self.assertIsNone(get_hunt_level("Nonexistent"))

    def test_darkthais_resolution_and_same_hunt(self):
        from baiaidle.hunts import is_same_hunt
        info = get_hunt_info("darkthais")
        self.assertIsNotNone(info)
        self.assertEqual(info["name"], "Dark Thais")
        self.assertEqual(info["level"], 800)

        # Deve reconhecer Dark Thais e darkthais como a mesma hunt
        self.assertTrue(is_same_hunt("Dark Thais", "darkthais"))
        self.assertTrue(is_same_hunt("darkthais", "Dark Thais"))
        self.assertFalse(is_same_hunt("Casa", "Dark Thais"))
        self.assertFalse(is_same_hunt("Casa", "darkthais"))

    def test_is_hunt_level_safe(self):
        # Personagem level 50 tentando Hydra (level 100) -> Não seguro
        self.assertFalse(is_hunt_level_safe("Hydra", char_level=50))

        # Personagem level 100 tentando Hydra (level 100) -> Seguro
        self.assertTrue(is_hunt_level_safe("Hydra", char_level=100))

        # Personagem level 90 com margem de 15 tentando Hydra (level 100) -> Seguro (90+15=105 >= 100)
        self.assertTrue(is_hunt_level_safe("Hydra", char_level=90, margin=15))

        # Hunt desconhecida -> Retorna True por segurança para não travar
        self.assertTrue(is_hunt_level_safe("Unknown Hunt", char_level=10))

    @patch("baiaidle.hunts.open_hunts_menu", new_callable=AsyncMock)
    async def test_get_hunts_list_uses_cache_without_opening_menu(self, mock_open):
        tab = MagicMock()
        # force_refresh=False não deve chamar open_hunts_menu se o cache estiver preenchido
        hunts = await get_hunts_list(tab, force_refresh=False)
        self.assertGreaterEqual(len(hunts), 80)
        mock_open.assert_not_called()

    @patch("baiaidle.hunts.save_hunts_cache")
    @patch("baiaidle.hunts.open_hunts_menu", new_callable=AsyncMock)
    async def test_get_hunts_list_force_refresh_opens_menu(self, mock_open, mock_save):
        mock_open.return_value = True
        tab = MagicMock()
        tab.execute_script = AsyncMock(return_value={
            "result": {"result": {"value": '[{"index": 1, "name": "Test Hunt", "level": 50, "raw_level": "lvl 50", "type": "EXP"}]'}}
        })

        hunts = await get_hunts_list(tab, force_refresh=True)
        mock_open.assert_called_once()
        self.assertEqual(len(hunts), 1)
        self.assertEqual(hunts[0]["name"], "Test Hunt")
        self.assertEqual(hunts[0]["level"], 50)
        mock_save.assert_called_once()

if __name__ == "__main__":
    unittest.main()
