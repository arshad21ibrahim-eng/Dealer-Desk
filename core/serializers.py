import re
from decimal import Decimal
from rest_framework import serializers
from .models import Product, Dealer, Order, OrderItem
from .services import quantize_money, format_money, TAX_RATE
from .exceptions import DuplicateError, ValidationError


MONEY_REGEX = re.compile(r"^\d+(\.\d{1,2})?$")


class ProductSerializer(serializers.ModelSerializer):
    price = serializers.SerializerMethodField()
    stock = serializers.IntegerField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "sku",
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "stock",
            "description",
        ]

    def get_price(self, obj) -> str:
        return format_money(obj.price)


class ProductCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "sku",
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "description",
        ]
        extra_kwargs = {
            "sku": {"validators": []},
        }

    def validate_price(self, value):
        try:
            dec = Decimal(str(value))
        except Exception:
            raise ValidationError("Price must be a valid number", code="VALIDATION_ERROR")
        if dec <= 0:
            raise ValidationError("Price must be greater than 0", code="VALIDATION_ERROR")
        # Check decimal places <= 2
        str_val = str(value)
        if "." in str_val and len(str_val.split(".")[1]) > 2:
            raise ValidationError("Price cannot have more than 2 decimal places", code="VALIDATION_ERROR")
        return quantize_money(dec)


class ProductUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "description",
        ]
        extra_kwargs = {
            "name": {"required": False},
            "category": {"required": False},
            "brand": {"required": False},
            "vehicle_fitment": {"required": False},
            "price": {"required": False},
            "description": {"required": False},
        }

    def validate_price(self, value):
        try:
            dec = Decimal(str(value))
        except Exception:
            raise ValidationError("Price must be a valid number", code="VALIDATION_ERROR")
        if dec <= 0:
            raise ValidationError("Price must be greater than 0", code="VALIDATION_ERROR")
        str_val = str(value)
        if "." in str_val and len(str_val.split(".")[1]) > 2:
            raise ValidationError("Price cannot have more than 2 decimal places", code="VALIDATION_ERROR")
        return quantize_money(dec)


class DealerSerializer(serializers.ModelSerializer):
    credit_limit = serializers.SerializerMethodField()

    class Meta:
        model = Dealer
        fields = [
            "id",
            "dealer_code",
            "name",
            "city",
            "phone",
            "email",
            "gstin",
            "credit_limit",
        ]

    def get_credit_limit(self, obj) -> str:
        return format_money(obj.credit_limit)


class DealerCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dealer
        fields = [
            "dealer_code",
            "name",
            "city",
            "phone",
            "email",
            "gstin",
            "credit_limit",
        ]
        extra_kwargs = {
            "dealer_code": {"required": True, "validators": []},
            "name": {"required": True},
            "city": {"required": False},
            "phone": {"required": False},
            "email": {"required": False},
            "gstin": {"required": False},
            "credit_limit": {"required": False},
        }

    def validate_dealer_code(self, value):
        if not value or not value.strip():
            raise ValidationError("dealer_code cannot be empty", code="VALIDATION_ERROR")
        return value.strip()


class OrderItemSerializer(serializers.ModelSerializer):
    unit_price = serializers.SerializerMethodField()
    line_subtotal = serializers.SerializerMethodField()
    line_tax = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "sku",
            "name",
            "quantity",
            "unit_price",
            "line_subtotal",
            "line_tax",
            "line_total",
        ]

    def _get_item_calc(self, obj):
        if getattr(obj.order, "status", "DRAFT") == "DRAFT" and hasattr(obj, "product") and obj.product:
            unit_price = quantize_money(obj.product.price)
            line_subtotal = quantize_money(unit_price * obj.quantity)
            line_tax = quantize_money(line_subtotal * TAX_RATE)
            line_total = line_subtotal + line_tax
            return unit_price, line_subtotal, line_tax, line_total
        return obj.unit_price, obj.line_subtotal, obj.line_tax, obj.line_total

    def get_unit_price(self, obj) -> str:
        unit_price, _, _, _ = self._get_item_calc(obj)
        return format_money(unit_price)

    def get_line_subtotal(self, obj) -> str:
        _, line_subtotal, _, _ = self._get_item_calc(obj)
        return format_money(line_subtotal)

    def get_line_tax(self, obj) -> str:
        _, _, line_tax, _ = self._get_item_calc(obj)
        return format_money(line_tax)

    def get_line_total(self, obj) -> str:
        _, _, _, line_total = self._get_item_calc(obj)
        return format_money(line_total)


class OrderSerializer(serializers.ModelSerializer):
    dealer_id = serializers.IntegerField(source="dealer.id")
    items = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()
    tax_total = serializers.SerializerMethodField()
    grand_total = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%S%z")
    updated_at = serializers.DateTimeField(format="%Y-%m-%dT%H:%M:%S%z")

    class Meta:
        model = Order
        fields = [
            "order_number",
            "dealer_id",
            "status",
            "items",
            "subtotal",
            "tax_total",
            "grand_total",
            "created_at",
            "updated_at",
        ]

    def _calc_totals(self, obj):
        items = list(obj.items.select_related("product").all())
        if obj.status == "DRAFT":
            subtotal = Decimal("0.00")
            tax_total = Decimal("0.00")
            for item in items:
                u_price = quantize_money(item.product.price if item.product else item.unit_price)
                l_subtotal = quantize_money(u_price * item.quantity)
                l_tax = quantize_money(l_subtotal * TAX_RATE)
                subtotal += l_subtotal
                tax_total += l_tax
            grand_total = subtotal + tax_total
            return items, subtotal, tax_total, grand_total
        return items, obj.subtotal, obj.tax_total, obj.grand_total

    def get_items(self, obj):
        items, _, _, _ = self._calc_totals(obj)
        return OrderItemSerializer(items, many=True).data

    def get_subtotal(self, obj) -> str:
        _, subtotal, _, _ = self._calc_totals(obj)
        return format_money(subtotal)

    def get_tax_total(self, obj) -> str:
        _, _, tax_total, _ = self._calc_totals(obj)
        return format_money(tax_total)

    def get_grand_total(self, obj) -> str:
        _, _, _, grand_total = self._calc_totals(obj)
        return format_money(grand_total)
