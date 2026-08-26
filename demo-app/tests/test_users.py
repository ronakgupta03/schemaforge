def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_users_shape(client):
    r = client.get("/users")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    for item in data:
        # exact key set = the API contract the split must preserve
        assert set(item) == {"id", "name", "email", "address", "date_of_birth"}
    assert data[0]["name"] == "Ada"
    assert data[0]["address"] == "1 Main St"
    assert data[1]["date_of_birth"] is None


def test_get_user(client):
    r = client.get("/users/1")
    assert r.status_code == 200
    assert r.json()["email"] == "ada@example.com"


def test_get_user_404(client):
    assert client.get("/users/999").status_code == 404


def test_create_user(client):
    r = client.post(
        "/users",
        json={"name": "Carol", "email": "carol@example.com",
              "address": "3 Third St", "date_of_birth": "1995-05-05"},
    )
    assert r.status_code == 201
    assert set(r.json()) == {"id", "name", "email", "address", "date_of_birth"}


def test_reports_addresses(client):
    r = client.get("/reports/addresses")
    assert r.status_code == 200
    body = r.json()
    assert body[0] == {"name": "Ada", "address": "1 Main St"}
