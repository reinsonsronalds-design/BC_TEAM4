import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as api

client = TestClient(api.app)


@pytest.fixture(autouse=True)
def clear_webhooks(monkeypatch):
    for env in api.DISCORD_WEBHOOK_ENV.values():
        monkeypatch.delenv(env, raising=False)


def test_health_and_ready_without_database():
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").json()["status"] == "ready"


def test_order_contract_without_secrets():
    response = client.post("/api/orders", json={"customerName": "Demo", "items": [{"id": 1, "quantity": 2}, {"id": 3, "quantity": 1}]})
    assert response.status_code == 201
    body = response.json()
    assert body["order_ticket"].startswith("ORD-")
    assert body["invoice_ticket"].startswith("INV-")
    assert body["total_amount"] == "30.97"
    assert body["currency"] == "USD"
    assert body["notification_status"] == "not_configured"


def test_unknown_product_and_invalid_quantity():
    request = {"customerName": "Demo", "items": [{"id": 999, "quantity": 1}]}
    assert client.post("/api/orders", json=request).status_code == 422
    request["items"][0] = {"id": 1, "quantity": 0}
    assert client.post("/api/orders", json=request).status_code == 422


def test_bad_idempotency_header_rejected():
    response = client.post("/api/orders", json={"customerName": "Demo", "items": [{"id": 1, "quantity": 1}]}, headers={"Idempotency-Key": " "})
    assert response.status_code == 400


def test_order_and_invoice_direct_webhooks(monkeypatch):
    monkeypatch.setenv("DISCORD_ORDERS_WEBHOOK_URL", "https://discord.com/api/webhooks/test-orders")
    monkeypatch.setenv("DISCORD_INVOICES_WEBHOOK_URL", "https://discord.com/api/webhooks/test-invoices")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr(api.httpx, "post", fake_post)
    response = client.post("/api/orders", json={"customerName": "Demo", "items": [{"id": 1, "quantity": 1}]})
    assert response.status_code == 201
    assert response.json()["notification_status"] == "sent"
    assert len(calls) == 2
    assert all(c[1]["allowed_mentions"] == {"parse": []} for c in calls)


def test_discord_failure_is_reported_without_exposing_webhook(monkeypatch, caplog):
    monkeypatch.setenv("DISCORD_ORDERS_WEBHOOK_URL", "https://discord.com/api/webhooks/secret-token")

    def fake_post(url, **kwargs):
        raise httpx.ConnectError("No connection")

    monkeypatch.setattr(api.httpx, "post", fake_post)
    response = client.post("/api/orders", json={"customerName": "Demo", "items": [{"id": 1, "quantity": 1}]})
    assert response.status_code == 201
    assert response.json()["notification_status"] == "partial_failure"
    assert "secret-token" not in caplog.text


def test_support_ticket_with_and_without_webhook(monkeypatch):
    payload = {"customerName": "Test", "orderTicket": "ORD-TEST", "message": "Example demo message"}
    missing = client.post("/api/support", json=payload)
    assert missing.status_code == 201
    assert missing.json()["status"] == "demo_only"

    monkeypatch.setenv("DISCORD_SUPPORT_WEBHOOK_URL", "https://discord.com/api/webhooks/test-support")
    sent = []

    def fake_post(url, **kwargs):
        sent.append(kwargs["json"]["content"])
        return httpx.Response(204, request=httpx.Request("POST", url))

    monkeypatch.setattr(api.httpx, "post", fake_post)
    response = client.post("/api/support", json=payload)
    assert response.status_code == 201
    assert response.json()["status"] == "received"
    assert "Example demo message" in sent[0]
