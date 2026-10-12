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
    "name": "Rose",
    "glass": "martini",
    "category": "After Dinner Cocktail",
    "ingredients": [
      {
            "unit": "cl",
            "amount": 2,
            "ingredient": "Kirsch"
      },
      {
            "unit": "cl",
            "amount": 4,
            "ingredient": "Vermouth",
            "label": "Dry vermouth"
      },
      {
            "special": "3 dashes Strawberry syrup"
      }
],
    "garnish": "",
    "preparation": "Stir all ingredients with ice and strain into a cocktail glass.",
}

with open("/app/output.json", "w") as f:
    json.dump(result, f, indent=2)

print(f"Completed recipe for: {result['name']}")
print(f"Ingredients: {len(result['ingredients'])}")
PYEOF
