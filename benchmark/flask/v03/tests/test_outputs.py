import sys
from itertools import count

sys.path.insert(0, "/app")
from solve import app

_IP_SEQUENCE = count(1)


def _ip():
    return f"198.51.100.{next(_IP_SEQUENCE)}"


def _assert_headers(response, remaining):
    assert response.headers["X-RateLimit-Limit"] == "5"
    assert response.headers["X-RateLimit-Remaining"] == str(remaining)
    reset = int(response.headers["X-RateLimit-Reset"])
    assert 0 <= reset <= 10


def test_allowed_requests_decrement_headers():
    client = app.test_client()
    client.post("/api/reset")
    ip = _ip()
    for expected in (4, 3, 2, 1, 0):
        response = client.get("/api/resource", headers={"X-Forwarded-For": ip})
        assert response.status_code == 200
        assert response.get_json() == {"status": "ok"}
        _assert_headers(response, expected)


def test_sixth_request_is_denied_without_extra_capacity():
    client = app.test_client()
    client.post("/api/reset")
    ip = _ip()
    for _ in range(5):
        assert client.get(
            "/api/resource", headers={"X-Forwarded-For": ip}
        ).status_code == 200
    for _ in range(2):
        response = client.get("/api/resource", headers={"X-Forwarded-For": ip})
        assert response.status_code == 429
        data = response.get_json()
        assert data["error"] == "Rate limit exceeded"
        assert isinstance(data["retry_after_seconds"], int)
        assert 0 <= data["retry_after_seconds"] <= 10
        _assert_headers(response, 0)


def test_forwarded_chain_uses_first_ip_and_ips_are_independent():
    client = app.test_client()
    client.post("/api/reset")
    first = _ip()
    second = _ip()
    for _ in range(5):
        client.get(
            "/api/resource",
            headers={"X-Forwarded-For": f"{first}, 203.0.113.7"},
        )
    assert client.get(
        "/api/resource",
        headers={"X-Forwarded-For": f"{first}, 203.0.113.99"},
    ).status_code == 429
    response = client.get("/api/resource", headers={"X-Forwarded-For": second})
    assert response.status_code == 200
    _assert_headers(response, 4)


def test_remote_addr_is_used_without_forwarded_header():
    client = app.test_client()
    client.post("/api/reset")
    remote = _ip()
    for _ in range(5):
        client.get("/api/resource", environ_base={"REMOTE_ADDR": remote})
    assert client.get(
        "/api/resource", environ_base={"REMOTE_ADDR": remote}
    ).status_code == 429
    assert client.get(
        "/api/resource", environ_base={"REMOTE_ADDR": _ip()}
    ).status_code == 200


def test_reset_clears_all_ips_and_has_empty_window_headers():
    client = app.test_client()
    first = _ip()
    second = _ip()
    for ip in (first, second):
        for _ in range(5):
            client.get("/api/resource", headers={"X-Forwarded-For": ip})
    response = client.post("/api/reset", headers={"X-Forwarded-For": first})
    assert response.status_code == 200
    assert response.get_json() == {"status": "reset"}
    _assert_headers(response, 5)
    assert response.headers["X-RateLimit-Reset"] == "0"
    for ip in (first, second):
        response = client.get("/api/resource", headers={"X-Forwarded-For": ip})
        assert response.status_code == 200
        _assert_headers(response, 4)
