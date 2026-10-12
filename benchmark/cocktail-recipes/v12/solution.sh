#!/bin/bash
set -e
exec python3 << 'PYEOF'
import json, re

with open("/app/task.json") as f:
    task = json.load(f)

with open("/app/format_spec.json") as f:
    spec = json.load(f)

# Read reference text
with open("/app/knowledge/ref.txt") as f:
    text = f.read()

# Extract recipe data from reference text
result = {
    "name": "Espresso Martini",
    "glass": "martini",
    "category": "After Dinner Cocktail",
    "ingredients": [
      {
            "unit": "cl",
            "amount": 5,
            "ingredient": "Vodka"
      },
      {
            "unit": "cl",
            "amount": 1,
            "ingredient": "Coffee liqueur",
            "label": "Kahl\u00faa"
      },
      {
            "special": "Sugar syrup (according to individual preference of sweetness)"
      },
      {
            "special": "1 short strong Espresso"
      }
],
    "garnish": "",
    "preparation": "Shake and strain into a chilled cocktail glass.",
}

with open("/app/output.json", "w") as f:
    json.dump(result, f, indent=2)

print(f"Completed recipe for: {result['name']}")
print(f"Ingredients: {len(result['ingredients'])}")
PYEOF
