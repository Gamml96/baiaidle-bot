import re
import unittest


def parse_sale_value_text(text: str) -> int:
    """Mesma lógica de extração numérica de actions.get_sale_value."""
    if text is None:
        return 0
    text = str(text).strip()
    numbers = re.sub(r"[^0-9]", "", text)
    if not numbers:
        return 0
    try:
        return int(numbers)
    except ValueError:
        return 0


class TestSellValue(unittest.TestCase):
    def test_parse_sale_value_with_approximation_and_dots(self):
        raw_text = "≈ 1.100.950"
        self.assertEqual(parse_sale_value_text(raw_text), 1100950)

    def test_parse_sale_value_with_total_label(self):
        raw_text = "Total estimado ≈ 1.100.950"
        self.assertEqual(parse_sale_value_text(raw_text), 1100950)

    def test_parse_sale_value_plain_number(self):
        raw_text = "500000"
        self.assertEqual(parse_sale_value_text(raw_text), 500000)

    def test_parse_sale_value_empty_or_none(self):
        self.assertEqual(parse_sale_value_text(None), 0)
        self.assertEqual(parse_sale_value_text(""), 0)
        self.assertEqual(parse_sale_value_text("Sem valor"), 0)


if __name__ == "__main__":
    unittest.main()
