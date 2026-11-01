from __future__ import annotations

import json
from decimal import Decimal

import pytest

from contracts.orders import OrderLine
from invoicing import render
from invoicing_tests.conftest import BUCKET, make_order
from runtime.aws import client


def test_render_invoice_lists_lines_and_total() -> None:
    html = render.render_invoice(make_order())

    assert "Invoice ord-123" in html
    assert "ada@example.com" in html
    assert "TEA-001" in html
    assert "<td>MUG-002</td>" in html
    assert '<td class="num">7.00</td>' in html  # 2 x 3.50
    assert '<th class="num">15.00</th>' in html
    assert "Standard" in html


def test_render_invoice_marks_express_orders() -> None:
    assert "Express" in render.render_invoice(make_order(express=True))


def test_render_invoice_escapes_untrusted_values() -> None:
    order = make_order(
        customer_email="<script>alert(1)</script>@example.com",
        lines=[OrderLine(sku="<b>X</b>", quantity=1, unit_price=Decimal("1"))],
    )

    html = render.render_invoice(order)

    assert "<script>" not in html
    assert "<b>X</b>" not in html
    assert "&lt;b&gt;X&lt;/b&gt;" in html


def test_money_formats_two_decimals_and_thousands() -> None:
    assert render.money(Decimal("3.5")) == "3.50"
    assert render.money(Decimal("1234567.891")) == "1,234,567.89"


def test_invoice_key() -> None:
    assert render.invoice_key("ord-9") == "invoices/ord-9.html"


@pytest.mark.usefixtures("aws")
def test_main_uploads_invoice_and_prints_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    order = make_order()
    monkeypatch.setenv("ORDER_JSON", order.to_detail())

    render.main()

    assert json.loads(capsys.readouterr().out) == {
        "bucket": BUCKET,
        "key": "invoices/ord-123.html",
    }
    stored = client("s3").get_object(Bucket=BUCKET, Key="invoices/ord-123.html")
    assert stored["ContentType"].startswith("text/html")
    assert stored["Body"].read().decode() == render.render_invoice(order)


@pytest.mark.usefixtures("aws")
def test_main_fails_on_invalid_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORDER_JSON", '{"order_id": "ord-1"}')

    with pytest.raises(ValueError):
        render.main()


def test_main_requires_order_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORDER_JSON", raising=False)

    with pytest.raises(KeyError):
        render.main()
