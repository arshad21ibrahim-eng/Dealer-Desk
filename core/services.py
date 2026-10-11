import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
import zoneinfo
from django.db import transaction
from django.utils import timezone
from .models import Dealer, Product, Order, OrderItem, DailyOrderSequence
from .exceptions import ValidationError, IdempotencyConflictError


TAX_RATE = Decimal("0.18")
TWO_PLACES = Decimal("0.01")
KOLKATA_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")


def quantize_money(amount: Decimal) -> Decimal:
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    return amount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def format_money(amount: Decimal) -> str:
    return f"{quantize_money(amount):.2f}"


def get_request_hash(dealer_id: int, items_data: list) -> str:
    canonical = {
        "dealer_id": dealer_id,
        "items": sorted(
            [{"sku": str(it.get("sku")), "quantity": int(it.get("quantity", 0))} for it in items_data],
            key=lambda x: x["sku"],
        ),
    }
    encoded = json.dumps(canonical, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def generate_order_number() -> str:
    now_kolkata = datetime.now(KOLKATA_TZ).date()
    seq, _ = DailyOrderSequence.objects.select_for_update().get_or_create(
        date=now_kolkata,
        defaults={"last_number": 0},
    )
    seq.last_number += 1
    seq.save(update_fields=["last_number"])
    return f"ORD-{now_kolkata.strftime('%Y%m%d')}-{seq.last_number:04d}"


def create_draft_order_service(dealer_id: int, items_data: list, idempotency_key: str = None) -> tuple[Order, bool]:
    """Creates a DRAFT order. Does not deduct inventory.
    Returns (order, created_boolean).
    """
    if not items_data or not isinstance(items_data, list):
        raise ValidationError(message="Order must contain at least one item", details=["items list cannot be empty"])

    # Check dealer
    try:
        dealer = Dealer.objects.get(id=dealer_id)
    except (Dealer.DoesNotExist, ValueError, TypeError):
        raise ValidationError(message=f"Dealer with id {dealer_id} does not exist", details=["dealer_id is invalid"])

    # Validate items and check duplicate SKUs
    seen_skus = set()
    cleaned_items = []
    for idx, item in enumerate(items_data):
        if not isinstance(item, dict):
            raise ValidationError(message="Each item must be an object", details=[f"item {idx} is invalid"])
        sku = item.get("sku")
        if not sku or not isinstance(sku, str):
            raise ValidationError(message="Each item must specify a valid sku", details=[f"item {idx} missing sku"])
        if sku in seen_skus:
            raise ValidationError(
                message=f"Duplicate SKU '{sku}' in order items",
                details=[f"The same SKU '{sku}' cannot appear multiple times in the same order"],
            )
        seen_skus.add(sku)

        quantity = item.get("quantity")
        if quantity is None or not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            raise ValidationError(
                message=f"Quantity for SKU '{sku}' must be an integer >= 1",
                details=[f"Invalid quantity {quantity} for SKU {sku}"],
            )
        cleaned_items.append({"sku": sku, "quantity": quantity})

    # Validate products exist
    products_by_sku = {p.sku: p for p in Product.objects.filter(sku__in=seen_skus)}
    for item in cleaned_items:
        sku = item["sku"]
        if sku not in products_by_sku:
            raise ValidationError(message=f"Product with SKU '{sku}' does not exist", details=[f"unknown SKU: {sku}"])

    req_hash = get_request_hash(dealer_id, cleaned_items)

    with transaction.atomic():
        if idempotency_key:
            existing = Order.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                if existing.request_hash == req_hash:
                    return existing, False
                else:
                    raise IdempotencyConflictError(
                        message="Idempotency key reused with different request payload",
                        details=[f"Key '{idempotency_key}' conflict"],
                    )

        order_num = generate_order_number()
        order = Order.objects.create(
            order_number=order_num,
            dealer=dealer,
            status="DRAFT",
            subtotal=Decimal("0.00"),
            tax_total=Decimal("0.00"),
            grand_total=Decimal("0.00"),
            idempotency_key=idempotency_key,
            request_hash=req_hash,
        )

        subtotal = Decimal("0.00")
        tax_total = Decimal("0.00")
        order_items = []

        for item in cleaned_items:
            product = products_by_sku[item["sku"]]
            qty = item["quantity"]
            unit_price = quantize_money(product.price)
            line_subtotal = quantize_money(unit_price * qty)
            line_tax = quantize_money(line_subtotal * TAX_RATE)
            line_total = line_subtotal + line_tax

            subtotal += line_subtotal
            tax_total += line_tax

            order_items.append(
                OrderItem(
                    order=order,
                    product=product,
                    sku=product.sku,
                    name=product.name,
                    quantity=qty,
                    unit_price=unit_price,
                    line_subtotal=line_subtotal,
                    line_tax=line_tax,
                    line_total=line_total,
                )
            )

        OrderItem.objects.bulk_create(order_items)
        order.subtotal = subtotal
        order.tax_total = tax_total
        order.grand_total = subtotal + tax_total
        order.save(update_fields=["subtotal", "tax_total", "grand_total"])

        return order, True
