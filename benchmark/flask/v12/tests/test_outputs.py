import string
import sys
import uuid
from datetime import datetime

sys.path.insert(0, "/app")
from solve import app


def _shorten(client, suffix=None):
    url = f"https://example.com/{suffix or uuid.uuid4().hex}"
    response = client.post("/shorten", json={"url": url})
    assert response.status_code == 201
    data = response.get_json()
    assert data["original_url"] == url
    return data["short_code"], url


def test_codes_are_unique_six_character_alphanumerics():
    client = app.test_client()
    codes = [_shorten(client)[0] for _ in range(20)]
    assert len(set(codes)) == len(codes)
    assert all(
        len(code) == 6
        and set(code) <= set(string.ascii_letters + string.digits)
        for code in codes
    )


def test_redirect_updates_only_selected_code_and_stats_are_complete():
    client = app.test_client()
    first, first_url = _shorten(client)
    second, _ = _shorten(client)
    for _ in range(3):
        response = client.get(f"/{first}", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["Location"] == first_url
    stats = client.get(f"/stats/{first}").get_json()
    assert stats["short_code"] == first
    assert stats["original_url"] == first_url
    assert stats["visits"] == 3
    datetime.fromisoformat(stats["created_at"])
    assert client.get(f"/stats/{second}").get_json()["visits"] == 0


def test_missing_and_invalid_urls_have_exact_errors():
    client = app.test_client()
    for body in ({}, None):
        response = client.post("/shorten", json=body)
        assert response.status_code == 400
        assert response.get_json() == {"error": "URL is required"}
    for url in ("example.com", "ftp://example.com", ""):
        response = client.post("/shorten", json={"url": url})
        assert response.status_code == 400
        assert response.get_json() == {"error": "Invalid URL"}


def test_unknown_redirect_and_stats_are_json_404():
    client = app.test_client()
    code = uuid.uuid4().hex
    for path in (f"/{code}", f"/stats/{code}"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 404
        assert response.get_json() == {"error": "Short code not found"}


def test_popular_is_top_five_by_visits_with_creation_order_ties():
    client = app.test_client()
    counts = [60, 60, 50, 40, 30, 20]
    created = []
    for index, count in enumerate(counts):
        code, url = _shorten(client, f"popular-{uuid.uuid4().hex}-{index}")
        for _ in range(count):
            assert client.get(f"/{code}", follow_redirects=False).status_code == 302
        created.append((code, url, count))

    response = client.get("/popular")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 5
    assert [
        (item["short_code"], item["original_url"], item["visits"])
        for item in data
    ] == created[:5]


def test_static_routes_are_not_captured_by_redirect_route():
    client = app.test_client()
    code, _ = _shorten(client)
    assert client.get(f"/stats/{code}").status_code == 200
    assert client.get("/popular").status_code == 200
    assert client.post("/shorten", json={"url": "https://openai.com"}).status_code == 201
