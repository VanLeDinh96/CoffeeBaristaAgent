import json
import unicodedata
from pathlib import Path


class MenuConfigurationError(ValueError):
    pass


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    return " ".join("".join(c for c in value if not unicodedata.combining(c)).split())


def load_menu(path: Path) -> list[dict]:
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise MenuConfigurationError(f"Cannot read menu file {path}") from exc

    if not isinstance(items, list):
        raise MenuConfigurationError("Menu must be a JSON array")

    ids = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict) or any(
            not isinstance(item.get(field), str) or not item[field].strip()
            for field in ("id", "name", "category_id")
        ):
            raise MenuConfigurationError(f"Invalid menu entry at index {index}")
        item_id = item["id"]
        if item_id in ids:
            raise MenuConfigurationError(f"Duplicate menu ID {item_id}")
        ids.add(item_id)
        price = item.get("price_vnd")
        if type(price) is not int or price < 0:
            raise MenuConfigurationError(f"Invalid price for {item_id}")
        for field, values in (
            ("aliases", item.get("aliases")),
            ("tags", item.get("tags", [])),
            ("ingredients", item.get("ingredients", [])),
        ):
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not normalize(value) for value in values
            ):
                raise MenuConfigurationError(f"Invalid {field} for {item_id}")
        if not isinstance(item.get("description"), str):
            raise MenuConfigurationError(f"Invalid description for {item_id}")
    return items


class Menu:
    def __init__(self, path: Path):
        self._entries = [
            (item, tuple(map(normalize, [item["name"], *item["aliases"]])))
            for item in sorted(
                load_menu(path),
                key=lambda item: (item["price_vnd"], normalize(item["name"])),
            )
        ]

    def get_menu_item(self, name: str) -> dict:
        """Look up an item by name or alias. Return found, ambiguous, or not_found."""
        query = normalize(name)
        exact = [item for item, names in self._entries if query in names]
        matches = exact or (self.search_menu(query=query) if query else [])
        if len(matches) == 1:
            return {"status": "found", "item": matches[0]}
        if matches:
            return {"status": "ambiguous", "options": matches}
        return {"status": "not_found"}

    def search_menu(
        self,
        query: str | None = None,
        category_id: str | None = None,
        max_price_vnd: int | None = None,
        include_max_price: bool = True,
        tag: str | None = None,
    ) -> list[dict]:
        """Find menu items matching all filters, sorted by price then name.

        Args:
            query: Optional name or alias fragment.
            category_id: Optional category ID, such as coffee or tea.
            max_price_vnd: Optional upper bound in whole Vietnamese dong.
            include_max_price: Include items priced exactly at the upper bound.
            tag: Optional menu tag. Use cold for drinks explicitly served cold,
                or refreshing for drinks described as light and refreshing.
        """
        query = normalize(query or "")
        category = normalize(category_id or "")
        tag = normalize(tag or "")
        matches = []
        for item, names in self._entries:
            if category and normalize(item["category_id"]) != category:
                continue
            if query and not any(query in name for name in names):
                continue
            if tag and not any(tag == normalize(value) for value in item.get("tags", [])):
                continue
            price = item["price_vnd"]
            if max_price_vnd is not None and (
                price > max_price_vnd or (price == max_price_vnd and not include_max_price)
            ):
                continue
            matches.append(item)
        return matches
