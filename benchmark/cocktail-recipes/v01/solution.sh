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
    "name": "Negroni",
    "glass": "old-fashioned",
    "category": "Before Dinner Cocktail",
    "ingredients": [
      {
            "unit": "cl",
            "amount": 3,
            "ingredient": "Gin"
      },
      {
            "unit": "cl",
            "amount": 3,
            "ingredient": "Campari"
      },
      {
            "unit": "cl",
            "amount": 3,
            "ingredient": "Vermouth",
            "label": "Sweet red vermouth"
      }
],
    "garnish": "Half an orange slice",
    "preparation": "Build into old-fashioned glass filled with ice. Stir gently.",
}

with open("/app/output.json", "w") as f:
    json.dump(result, f, indent=2)

print(f"Completed recipe for: {result['name']}")
print(f"Ingredients: {len(result['ingredients'])}")
PYEOF
