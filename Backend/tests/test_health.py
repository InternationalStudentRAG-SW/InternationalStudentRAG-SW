def test_root(client):
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["status"] == "running"


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"
