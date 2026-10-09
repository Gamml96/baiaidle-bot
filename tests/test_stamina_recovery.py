import unittest
from baiaidle.sell import (
    IR_PARA_TREINO_ONLINE,
    VOLTAR_PARA_HUNT,
    MAX_STAMINA_MINUTES,
    STAMINA_RECOVERY_RATE,
    parse_stamina_time_to_minutes,
    calculate_remaining_recovery_time,
    DEFAULT_HUNT,
    HuntStats,
    is_training_location,
    resolve_target_hunt,
)

class TestStaminaRecovery(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(IR_PARA_TREINO_ONLINE, 20)
        self.assertEqual(VOLTAR_PARA_HUNT, 100)
        self.assertEqual(MAX_STAMINA_MINUTES, 2520)  # 42h * 60m
        self.assertEqual(STAMINA_RECOVERY_RATE, 8.0)
        self.assertEqual(DEFAULT_HUNT, "Infernal Demon")

    def test_hunt_stats_default_hunt(self):
        stats = HuntStats()
        self.assertEqual(stats.default_hunt, "Infernal Demon")
        stats.default_hunt = "Dragon Lord"
        stats.reset()
        self.assertEqual(stats.default_hunt, "Dragon Lord")

    def test_is_training_location(self):
        # Treino
        self.assertEqual(is_training_location("Treino Online"), (True, "treino"))
        self.assertEqual(is_training_location("Treino"), (True, "treino"))
        self.assertEqual(is_training_location("Exercise Dummy"), (True, "treino"))
        self.assertEqual(is_training_location("Treinamento"), (True, "treino"))
        self.assertEqual(is_training_location("online training"), (True, "treino"))

        # Casa
        self.assertEqual(is_training_location("Casa"), (True, "casa"))
        self.assertEqual(is_training_location("House"), (True, "casa"))
        self.assertEqual(is_training_location("Casa de Amigo"), (True, "casa"))
        self.assertEqual(is_training_location("Dummies"), (True, "casa"))
        self.assertEqual(is_training_location("Dummy 1"), (True, "casa"))

        # Hunts comuns
        self.assertEqual(is_training_location("Infernal Demon"), (False, ""))
        self.assertEqual(is_training_location("Dragon Lord"), (False, ""))
        self.assertEqual(is_training_location("Rotworm"), (False, ""))
        self.assertEqual(is_training_location(""), (False, ""))
        self.assertEqual(is_training_location(None), (False, ""))

    def test_parse_stamina_time_to_minutes(self):
        self.assertEqual(parse_stamina_time_to_minutes("42:00"), 2520)
        self.assertEqual(parse_stamina_time_to_minutes("35:20"), 2120)
        self.assertEqual(parse_stamina_time_to_minutes("35:20:00"), 2120)
        self.assertEqual(parse_stamina_time_to_minutes("42h 00m"), 2520)
        self.assertEqual(parse_stamina_time_to_minutes("42h"), 2520)
        self.assertEqual(parse_stamina_time_to_minutes("30m"), 30)
        self.assertEqual(parse_stamina_time_to_minutes("00:00"), 0)
        self.assertIsNone(parse_stamina_time_to_minutes(""))
        self.assertIsNone(parse_stamina_time_to_minutes(None))
        self.assertIsNone(parse_stamina_time_to_minutes("invalid"))

    def test_calculate_remaining_recovery_time_at_max(self):
        mins, text = calculate_remaining_recovery_time("42:00", 100)
        self.assertEqual(mins, 0)
        self.assertIn("100%", text)

        mins, text = calculate_remaining_recovery_time("", 100)
        self.assertEqual(mins, 0)
        self.assertIn("100%", text)

    def test_calculate_remaining_recovery_time_with_time_string(self):
        # 35:20 has 2120 minutes of stamina.
        # Needed: 2520 - 2120 = 400 minutes of stamina.
        # Real time: 400 / 8 = 50 real minutes.
        mins, text = calculate_remaining_recovery_time("35:20", 84)
        self.assertEqual(mins, 50)
        self.assertEqual(text, "50m")

        # 21:00 has 1260 minutes of stamina (half).
        # Needed: 1260 minutes of stamina.
        # Real time: 1260 / 8 = 157.5 -> round(157.5) = 158 real minutes = 2h 38m.
        mins, text = calculate_remaining_recovery_time("21:00", 50)
        self.assertEqual(mins, 158)
        self.assertEqual(text, "2h 38m")

        # 08:24 has 504 minutes of stamina (20%).
        # Needed: 2520 - 504 = 2016 minutes of stamina.
        # Real time: 2016 / 8 = 252 real minutes = 4h 12m.
        mins, text = calculate_remaining_recovery_time("08:24", 20)
        self.assertEqual(mins, 252)
        self.assertEqual(text, "4h 12m")

    def test_calculate_remaining_recovery_time_fallback_to_pct(self):
        # When stam_time is 00:00 or missing, but percentage is 80%:
        # Needed: 2520 * (1 - 0.8) = 504 stamina minutes.
        # Real time: 504 / 8 = 63 real minutes = 1h 3m.
        mins, text = calculate_remaining_recovery_time("00:00", 80)
        self.assertEqual(mins, 63)
        self.assertEqual(text, "1h 3m")

        mins, text = calculate_remaining_recovery_time("", 80)
        self.assertEqual(mins, 63)
        self.assertEqual(text, "1h 3m")

    def test_calculate_remaining_recovery_time_edge_cases(self):
        # Just 2 minutes needed
        # 2520 - 2518 = 2 stamina min -> 2/8 = 0.25 -> 0 mins (< 1m)
        mins, text = calculate_remaining_recovery_time("41:58", 99)
        self.assertEqual(text, "< 1m")

        # Invalid/unknown
        mins, text = calculate_remaining_recovery_time(None, None)
        self.assertEqual(text, "desconhecido")

if __name__ == "__main__":
    unittest.main()
