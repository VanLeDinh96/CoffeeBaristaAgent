import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from barista.menu import Menu, MenuConfigurationError

MENU_PATH = Path(__file__).resolve().parents[1] / "menu.json"


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.menu = Menu(MENU_PATH)

    def test_lookup(self):
        for name in ("LATTE", "  ca PHE   LATTE ", "CÀ PHÊ LATTE"):
            with self.subTest(name=name):
                result = self.menu.get_menu_item(name)
                self.assertEqual(result["status"], "found")
                self.assertEqual(result["item"]["price_vnd"], 45000)
        self.assertEqual(self.menu.get_menu_item("ca phe den")["item"]["id"], "black-coffee")
        self.assertEqual(self.menu.get_menu_item("cà phê")["status"], "ambiguous")
        self.assertEqual(self.menu.get_menu_item("trà đào"), {"status": "not_found"})

    def test_budget_and_category(self):
        for inclusive, expected in (
            (False, ["black-coffee", "latte"]),
            (True, ["black-coffee", "latte", "cappuccino"]),
        ):
            with self.subTest(inclusive=inclusive):
                items = self.menu.search_menu(
                    category_id="coffee", max_price_vnd=50000, include_max_price=inclusive
                )
                self.assertEqual([item["id"] for item in items], expected)
        self.assertEqual(self.menu.search_menu(query="latte", category_id="tea"), [])
        self.assertEqual(
            [item["price_vnd"] for item in self.menu.search_menu(max_price_vnd=50000)],
            [35000, 40000, 45000, 50000],
        )

    def test_invalid_data(self):
        item = json.loads(MENU_PATH.read_text(encoding="utf-8"))[0]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "menu.json"
            with self.assertRaises(MenuConfigurationError):
                Menu(path)
            for data in ("invalid", json.dumps([item, item]), *(
                json.dumps([dict(item, price_vnd=price)]) for price in (-1, 1.5, "1", True)
            )):
                with self.subTest(data=data):
                    path.write_text(data, encoding="utf-8")
                    with self.assertRaises(MenuConfigurationError):
                        Menu(path)
