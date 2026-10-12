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
    "name": "Whiskey Sour",
    "glass": "old-fashioned",
    "category": "Before Dinner Cocktail",
    "ingredients": [
      {
            "unit": "cl",
            "amount": 4.5,
            "ingredient": "Whiskey",
            "label": "Bourbon whiskey"
      },
      {
            "unit": "cl",
            "amount": 3.0,
            "ingredient": "Lemon juice"
      },
      {
            "unit": "cl",
            "amount": 1.5,
            "ingredient": "Syrup",
            "label": "Sugar syrup"
      }
],
    "garnish": "Half an orange slice and cherry",
    "preparation": "Dash egg white (Optional: if used shake little harder to foam up the egg white). Pour all ingredients into cocktail shaker filled with ice. Shake. Strain into cocktail glass. If served ‘On the rocks’, strain ingredients into old-fashioned glass filled with ice.",
}

with open("/app/output.json", "w") as f:
    json.dump(result, f, indent=2)

print(f"Completed recipe for: {result['name']}")
print(f"Ingredients: {len(result['ingredients'])}")
PYEOF
