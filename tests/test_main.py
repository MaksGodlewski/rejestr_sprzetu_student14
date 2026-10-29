import pytest

from main import create_app, get_conn, query


@pytest.fixture()
def client():
    app = create_app()
    app.config.update(TESTING=True)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE loans, equipment RESTART IDENTITY CASCADE")
    return app.test_client()


def add_item(client, name="Dell Latitude", inv="LAP-001", category="laptop"):
    return client.post("/equipment", data={
        "name": name, "category": category, "inventory_no": inv})


def status_of(client, item_id):
    items = client.get("/api/equipment").get_json()
    return next(i["status"] for i in items if i["id"] == item_id)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_add_equipment(client):
    add_item(client)
    items = client.get("/api/equipment").get_json()
    assert len(items) == 1
    assert items[0]["status"] == "available"


def test_duplicate_inventory_number_rejected(client):
    add_item(client)
    add_item(client, name="Inny laptop")
    assert len(client.get("/api/equipment").get_json()) == 1


def test_invalid_category_rejected(client):
    add_item(client, category="czajnik")
    assert client.get("/api/equipment").get_json() == []


def test_loan_and_return_flow(client):
    add_item(client)
    client.post("/loans", data={"equipment_id": 1, "borrower_name": "Jan Kowalski",
                                "due_date": "2030-01-01"})
    assert status_of(client, 1) == "loaned"
    page = client.get("/loans").get_data(as_text=True)
    assert "Jan Kowalski" in page

    loan_id = query("SELECT id FROM loans")[0]["id"]
    client.post(f"/loans/{loan_id}/return")
    assert status_of(client, 1) == "available"
    assert query("SELECT returned_at FROM loans")[0]["returned_at"] is not None


def test_cannot_loan_twice(client):
    add_item(client)
    client.post("/loans", data={"equipment_id": 1, "borrower_name": "Anna"})
    client.post("/loans", data={"equipment_id": 1, "borrower_name": "Piotr"})
    assert len(query("SELECT id FROM loans")) == 1
