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
    assert r.get("glass") == "martini", f"Expected glass=martini, got {r.get('glass')}"

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
    assert r.get("glass") == "martini", f"Expected glass=martini, got {r.get('glass')}"


def test_lime_juice_amount():
    r = load_output()
    for ing in r['ingredients']:
        if ing.get('ingredient') == 'Lime juice':
            assert ing.get('amount') == 2.5, f"Expected Lime juice=2.5cl (IBA), got {ing.get('amount')}cl"
            break


def test_white_rum_amount():
    r = load_output()
    for ing in r["ingredients"]:
        if ing.get("ingredient") == "White rum":
            assert ing.get("amount") == 4.5, f"Expected White rum=4.5cl, got {ing.get('amount')}cl"
            break


def test_has_white_rum():
    r = load_output()
    all_ings = [str(x) for x in r["ingredients"]]
    found = any("White rum" in str(x) for x in r["ingredients"])
    assert found, f"Missing ingredient: White rum"


def test_has_lime_juice():
    r = load_output()
    all_ings = [str(x) for x in r["ingredients"]]
    found = any("Lime juice" in str(x) for x in r["ingredients"])
    assert found, f"Missing ingredient: Lime juice"


def test_has_syrup():
    r = load_output()
    all_ings = [str(x) for x in r["ingredients"]]
    found = any("Syrup" in str(x) for x in r["ingredients"])
    assert found, f"Missing ingredient: Syrup"

