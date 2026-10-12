import json, os

def load_output():
    with open("/app/output.json") as f:
        return json.load(f)

def test_output_exists():
    assert os.path.exists("/app/output.json"), "output.json not found"

def test_has_name():
    r = load_output()
    assert r.get("name"), "Missing name"
    assert len(r["name"]) > 0

def test_has_glass():
    r = load_output()
    assert r.get("glass") == "old-fashioned", f"Expected glass=old-fashioned, got {r.get('glass')}"

def test_has_ingredients():
    r = load_output()
    assert len(r.get("ingredients", [])) >= 2, "Need at least 2 ingredients"
    for ing in r["ingredients"]:
        has_name = ing.get("ingredient") or ing.get("special")
        assert has_name, "Ingredient missing both name and special field"

def test_has_preparation():
    r = load_output()
    assert r.get("preparation"), "Missing preparation method"
    assert len(r["preparation"]) > 10

def test_amounts_valid():
    r = load_output()
    for ing in r["ingredients"]:
        amt = ing.get("amount")
        if amt is not None:
            assert amt > 0, f"Invalid amount: {amt} for {ing['ingredient']}"

def test_total_volume():
    r = load_output()
    total = 0
    for ing in r["ingredients"]:
        amt = ing.get("amount")
        unit = ing.get("unit")
        if amt and unit == "cl":
            total += amt
    assert total > 0, "Zero total volume"
    # Most cocktails are 6-24 cl total
    assert 3 <= total <= 40, f"Unusual total volume: {total} cl"

def test_ingredient_count():
    r = load_output()
    assert len(r["ingredients"]) >= 3, f"Expected at least 3 ingredients"


def test_glass_type():
    r = load_output()
    assert r.get("glass") == "old-fashioned", f"Expected glass=old-fashioned, got {r.get('glass')}"


def test_lemon_juice_amount():
    r = load_output()
    for ing in r['ingredients']:
        if ing.get('ingredient') == 'Lemon juice':
            assert ing.get('amount') == 3, f"Expected Lemon juice=3cl, got {ing.get('amount')}cl"
            break


def test_syrup_amount():
    r = load_output()
    for ing in r['ingredients']:
        if 'syrup' in ing.get('ingredient', '').lower():
            assert ing.get('amount') == 1.5, f"Expected Syrup=1.5cl, got {ing.get('amount')}cl"
            break


def test_whiskey_amount():
    r = load_output()
    for ing in r["ingredients"]:
        if ing.get("ingredient") == "Whiskey":
            assert ing.get("amount") == 4.5, f"Expected Whiskey=4.5cl, got {ing.get('amount')}cl"
            break


def test_has_whiskey():
    r = load_output()
    all_ings = [str(x) for x in r["ingredients"]]
    found = any("Whiskey" in str(x) for x in r["ingredients"])
    assert found, f"Missing ingredient: Whiskey"


def test_has_lemon_juice():
    r = load_output()
    all_ings = [str(x) for x in r["ingredients"]]
    found = any("Lemon juice" in str(x) for x in r["ingredients"])
    assert found, f"Missing ingredient: Lemon juice"


def test_has_syrup():
    r = load_output()
    all_ings = [str(x) for x in r["ingredients"]]
    found = any("Syrup" in str(x) for x in r["ingredients"])
    assert found, f"Missing ingredient: Syrup"


def test_garnish():
    r = load_output()
    g = r.get("garnish", "")
    assert g is not None and len(g) > 0, "Missing garnish"
    assert "half an orange slice" in str(g).lower(), f"Expected garnish related to Half an orange slice and cherry"

