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
    assert r.get("glass") == "highball", f"Expected glass=highball, got {r.get('glass')}"

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
    assert len(r["ingredients"]) >= 7, f"Expected at least 7 ingredients"


def test_glass_type():
    r = load_output()
    assert r.get("glass") == "highball", f"Expected glass=highball, got {r.get('glass')}"


def test_vodka_amount():
    r = load_output()
    for ing in r["ingredients"]:
        if ing.get("ingredient") == "Vodka":
            assert ing.get("amount") == 4.5, f"Expected Vodka=4.5cl, got {ing.get('amount')}cl"
            break


def test_has_vodka():
    r = load_output()
    all_ings = [str(x) for x in r["ingredients"]]
    found = any("Vodka" in str(x) for x in r["ingredients"])
    assert found, f"Missing ingredient: Vodka"


def test_has_tomato_juice():
    r = load_output()
    all_ings = [str(x) for x in r["ingredients"]]
    found = any("Tomato juice" in str(x) for x in r["ingredients"])
    assert found, f"Missing ingredient: Tomato juice"


def test_has_lemon_juice():
    r = load_output()
    all_ings = [str(x) for x in r["ingredients"]]
    found = any("Lemon juice" in str(x) for x in r["ingredients"])
    assert found, f"Missing ingredient: Lemon juice"





def test_tomato_juice_amount():
    r = load_output()
    for ing in r['ingredients']:
        if ing.get('ingredient') == 'Tomato juice':
            amt = ing.get('amount')
            assert amt == 9, 'Expected Tomato juice=9cl, got ' + str(amt) + 'cl'
            break

def test_garnish():
    r = load_output()
    g = r.get("garnish", "")
    assert g is not None and len(g) > 0, "Missing garnish"
    assert "celery and optionall" in str(g).lower(), f"Expected garnish related to Celery and optionally lemon wedge"

