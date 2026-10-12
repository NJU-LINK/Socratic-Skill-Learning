#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import json

result = {
    "name": "Manhattan",
    "glass": "martini",
    "category": "Before Dinner Cocktail",
    "ingredients": [
        {
            "unit": "cl",
            "amount": 5,
            "ingredient": "Whiskey",
            "label": "Rye whiskey",
        },
        {
            "unit": "cl",
            "amount": 2,
            "ingredient": "Vermouth",
            "label": "Red vermouth",
        },
        {"special": "1 dash Angostura Bitters"},
    ],
    "garnish": "Cherry",
    "preparation": "Stir in mixing glass with ice cubes. Strain into chilled cocktail glass.",
}

with open("/app/output.json", "w", encoding="utf-8") as output:
    json.dump(result, output, indent=2)
PY
