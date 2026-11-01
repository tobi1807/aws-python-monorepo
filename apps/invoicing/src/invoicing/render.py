"""Render an invoice for an order and upload it to S3.

Runs as an ECS Fargate task started by the fulfilment state machine.

Environment:
  ORDER_JSON      an ``OrderPlaced`` event as JSON (the EventBridge ``detail``)
  INVOICE_BUCKET  bucket to write ``invoices/{order_id}.html`` into
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from html import escape

from contracts.orders import OrderPlaced
from runtime.aws import client

CENT = Decimal("0.01")


def invoice_key(order_id: str) -> str:
    return f"invoices/{order_id}.html"


def money(value: Decimal) -> str:
    return f"{value.quantize(CENT):,.2f}"


def render_invoice(order: OrderPlaced) -> str:
    """Pure function: an order in, an HTML invoice out."""
    rows = "\n".join(
        "      <tr>"
        f"<td>{escape(line.sku)}</td>"
        f'<td class="num">{line.quantity}</td>'
        f'<td class="num">{money(line.unit_price)}</td>'
        f'<td class="num">{money(line.unit_price * line.quantity)}</td>'
        "</tr>"
        for line in order.lines
    )
    shipping = "Express" if order.express else "Standard"
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Invoice {escape(order.order_id)}</title>
  </head>
  <body>
    <h1>Invoice</h1>
    <p>Order: {escape(order.order_id)}</p>
    <p>Customer: {escape(order.customer_email)}</p>
    <p>Placed: {order.placed_at.isoformat()}</p>
    <p>Shipping: {shipping}</p>
    <table>
      <thead>
        <tr><th>SKU</th><th>Qty</th><th>Unit price</th><th>Line total</th></tr>
      </thead>
      <tbody>
{rows}
      </tbody>
      <tfoot>
        <tr><th colspan="3">Total</th><th class="num">{money(order.total)}</th></tr>
      </tfoot>
    </table>
  </body>
</html>
"""


def upload_invoice(order: OrderPlaced, bucket: str) -> str:
    key = invoice_key(order.order_id)
    client("s3").put_object(
        Bucket=bucket,
        Key=key,
        Body=render_invoice(order).encode(),
        ContentType="text/html; charset=utf-8",
    )
    return key


def main() -> None:
    # A pex entry point's return value becomes the process exit code, so this
    # returns None; the result is reported on stdout.
    order = OrderPlaced.model_validate_json(os.environ["ORDER_JSON"])
    bucket = os.environ["INVOICE_BUCKET"]
    key = upload_invoice(order, bucket)
    print(json.dumps({"bucket": bucket, "key": key}))


if __name__ == "__main__":
    main()
