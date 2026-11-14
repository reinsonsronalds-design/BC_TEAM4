"""Stateless Slice & Sip demonstration API.

No orders, invoices, or support requests are persisted. Webhook delivery is
best effort. Use fictional/test data only.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any

import httpx
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

logger = logging.getLogger("slice_sip")

app = FastAPI(
    title="Slice & Sip API",
    version="1.1.0",
    description="Stateless order, invoice and customer-support demo API.",
)

# Prices are authoritative in the API, never supplied by a browser client.
CATALOG: dict[int, dict[str, Any]] = {
    1: {"name": "Artisanal Pepperoni Pizza", "price": Decimal("12.99")},
    2: {"name": "Raw Broccoli", "price": Decimal("8.99")},
    3: {"name": "Ginger Lemonade", "price": Decimal("4.99")},
}

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=50)


class OrderRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    customer_name: ShortText = Field(alias="customerName")
    items: list[OrderItem] = Field(min_length=1, max_length=20)


class SupportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    customer_name: ShortText = Field(alias="customerName")
    order_ticket: str | None = Field(default=None, alias="orderTicket", max_length=32)
    message: str = Field(min_length=3, max_length=4000)


def _ticket(prefix: str) -> str:
    # Random rather than sequential; unique across independent Fargate tasks.
    return f"{prefix}-{datetime.now(timezone.utc).year}-{uuid.uuid4().hex[:12].upper()}"


def _normalise_order_items(items: list[OrderItem]) -> tuple[list[dict[str, Any]], Decimal]:
    rows: list[dict[str, Any]] = []
    total = Decimal("0.00")
    for item in items:
        product = CATALOG.get(item.id)
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown product ID: {item.id}",
            )
        line_total = product["price"] * item.quantity
        total += line_total
        rows.append({
            "id": item.id,
            "name": product["name"],
            "quantity": item.quantity,
            "unit_price": str(product["price"]),
            "line_total": str(line_total),
        })
    return rows, total.quantize(Decimal("0.01"))


# ECS task definition injects these values from AWS Secrets Manager.
# The app itself needs no IAM task role or boto3 dependency.
DISCORD_WEBHOOK_ENV = {
    "orders": "DISCORD_ORDERS_WEBHOOK_URL",
    "invoices": "DISCORD_INVOICES_WEBHOOK_URL",
    "support": "DISCORD_SUPPORT_WEBHOOK_URL",
}


def _send_discord(channel: str, message: str) -> str:
    """Return sent, not_configured, or failed. Never log webhook URLs."""
    webhook_url = os.environ.get(DISCORD_WEBHOOK_ENV[channel], "").strip()
    if not webhook_url:
        return "not_configured"
    if not webhook_url.startswith("https://"):
        logger.warning("Discord webhook for %s must use HTTPS", channel)
        return "failed"
    try:
        response = httpx.post(
            webhook_url,
            json={"content": message[:2000], "allowed_mentions": {"parse": []}},
            timeout=5.0,
        )
        response.raise_for_status()
        return "sent"
    except httpx.HTTPError as exc:
        # Avoid logging str(exc): some HTTP errors include the secret URL.
        logger.warning("Discord delivery failed on %s (%s)", channel, type(exc).__name__)
        return "failed"


def _combined_notification_status(results: list[str]) -> str:
    if all(result == "sent" for result in results):
        return "sent"
    if all(result == "not_configured" for result in results):
        return "not_configured"
    return "partial_failure"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "slice-sip-api"}


@app.get("/ready")
def readiness() -> dict[str, str]:
    # No database or external dependency is needed to accept HTTP requests.
    return {"status": "ready", "service": "slice-sip-api"}


@app.post("/api/orders", status_code=status.HTTP_201_CREATED)
def create_order(
    request: OrderRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    """Calculate an order and invoice; no durable history or idempotency store."""
    if idempotency_key is not None:
        key = idempotency_key.strip()
        if not key or len(key) > 80:
            raise HTTPException(status_code=400, detail="Invalid Idempotency-Key")

    items, total = _normalise_order_items(request.items)
    order_ticket = _ticket("ORD")
    invoice_ticket = _ticket("INV")
    item_summary = "\n".join(f"• {row['quantity']} × {row['name']}" for row in items)

    order_result = _send_discord(
        "orders",
        f"🛒 **New demo order**\nOrder: `{order_ticket}`\nTotal: ${total:.2f}\n{item_summary}",
    )
    invoice_result = _send_discord(
        "invoices",
        f"🧾 **Demo invoice**\nInvoice: `{invoice_ticket}`\nOrder: `{order_ticket}`\nAmount: ${total:.2f}",
    )
    return {
        "order_ticket": order_ticket,
        "invoice_ticket": invoice_ticket,
        "total_amount": str(total),
        "currency": "USD",
        "notification_status": _combined_notification_status([order_result, invoice_result]),
    }


@app.post("/api/support", status_code=status.HTTP_201_CREATED)
def create_support_ticket(request: SupportRequest) -> dict[str, str]:
    """Forward a demo support message; nothing is stored in the application."""
    support_ticket = _ticket("SUP")
    # No DB means we cannot validate historical order references.
    related_order = (request.order_ticket or "Not specified").strip() or "Not specified"
    message = request.message.strip()
    result = _send_discord(
        "support",
        (
            f"💬 **Demo support request**\nTicket: `{support_ticket}`\n"
            f"Related order: `{related_order}`\nMessage: {message[:1000]}"
        ),
    )
    return {
        "support_ticket": support_ticket,
        "status": "received" if result == "sent" else "demo_only",
        "notification_status": result,
    }
