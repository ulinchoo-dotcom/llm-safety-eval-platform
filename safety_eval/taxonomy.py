import json
from importlib.resources import files

TAXONOMY = json.loads(files("safety_eval").joinpath("data/taxonomy.v1.json").read_text())
VERSION = TAXONOMY["version"]
CATEGORIES = {item["id"] for item in TAXONOMY["categories"]}
SUBCATEGORIES = {item["id"]: item["category_id"] for item in TAXONOMY["subcategories"]}
ATTACKS = {item["id"] for item in TAXONOMY["attack_types"]}
