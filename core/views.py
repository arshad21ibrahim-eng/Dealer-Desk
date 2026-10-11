from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.http import JsonResponse

from .models import Product, Dealer, Order, InventoryLog
from .serializers import (
    ProductSerializer,
    ProductCreateSerializer,
    ProductUpdateSerializer,
    DealerSerializer,
    DealerCreateSerializer,
    OrderSerializer,
)
from .pagination import ContractPagination
from .services import create_draft_order_service
from .exceptions import ValidationError, NotFound, DuplicateError


def health(request):
    """GET /api/health/ — health check."""
    return JsonResponse({"status": "ok"})


# -----------------------------------------------------------------------------
# Products
# -----------------------------------------------------------------------------
@api_view(["GET", "POST"])
def product_list_create(request):
    if request.method == "GET":
        queryset = Product.objects.all().order_by("sku")
        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(sku__icontains=search) | Q(name__icontains=search) | Q(brand__icontains=search)
            )

        category = request.query_params.get("category")
        if category:
            queryset = queryset.filter(category=category)

        vehicle = request.query_params.get("vehicle")
        if vehicle:
            queryset = queryset.filter(vehicle_fitment__icontains=vehicle)

        paginator = ContractPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = ProductSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    elif request.method == "POST":
        sku = request.data.get("sku") if isinstance(request.data, dict) else None
        if not sku or not str(sku).strip():
            raise ValidationError(message="sku is required", details=["Missing sku"])
        sku = str(sku).strip()
        if Product.objects.filter(sku=sku).exists():
            raise DuplicateError(f"Product with SKU '{sku}' already exists")

        serializer = ProductCreateSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            details = []
            first_msg = "Validation error"
            for k, v in errors.items():
                err_text = v[0] if isinstance(v, list) else str(v)
                details.append(f"{k}: {err_text}")
                first_msg = f"{k}: {err_text}"
            raise ValidationError(message=first_msg, details=details)

        product = serializer.save(stock=0)
        return Response(ProductSerializer(product).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH"])
def product_detail(request, sku):
    try:
        product = Product.objects.get(sku=sku)
    except Product.DoesNotExist:
        raise NotFound(f"Product with SKU '{sku}' not found")

    if request.method == "GET":
        return Response(ProductSerializer(product).data)

    elif request.method == "PATCH":
        if "sku" in request.data and str(request.data["sku"]) != product.sku:
            raise ValidationError(message="SKU cannot change", details=["sku field is immutable"])

        serializer = ProductUpdateSerializer(product, data=request.data, partial=True)
        if not serializer.is_valid():
            errors = serializer.errors
            details = [f"{k}: {v[0] if isinstance(v, list) else v}" for k, v in errors.items()]
            raise ValidationError(message=details[0] if details else "Validation error", details=details)

        serializer.save()
        return Response(ProductSerializer(product).data)


# -----------------------------------------------------------------------------
# Inventory
# -----------------------------------------------------------------------------
@api_view(["PUT"])
def inventory_update(request, sku):
    try:
        product = Product.objects.get(sku=sku)
    except Product.DoesNotExist:
        raise NotFound(f"Product with SKU '{sku}' not found")

    quantity = request.data.get("quantity")
    if quantity is None or isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
        raise ValidationError(
            message="quantity must be an integer >= 0",
            details=["quantity is required and must be an integer >= 0"],
        )

    reason = request.data.get("reason", "")
    product.stock = quantity
    product.save(update_fields=["stock"])

    InventoryLog.objects.create(product=product, quantity=quantity, reason=str(reason))

    return Response({"sku": product.sku, "quantity": product.stock})


# -----------------------------------------------------------------------------
# Dealers
# -----------------------------------------------------------------------------
@api_view(["GET", "POST"])
def dealer_list_create(request):
    if request.method == "GET":
        queryset = Dealer.objects.all().order_by("id")
        paginator = ContractPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = DealerSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    elif request.method == "POST":
        dealer_code = request.data.get("dealer_code") if isinstance(request.data, dict) else None
        if not dealer_code or not str(dealer_code).strip():
            raise ValidationError(message="dealer_code is required", details=["Missing dealer_code"])
        dealer_code = str(dealer_code).strip()
        if Dealer.objects.filter(dealer_code=dealer_code).exists():
            raise DuplicateError(f"Dealer with dealer_code '{dealer_code}' already exists")

        serializer = DealerCreateSerializer(data=request.data)
        if not serializer.is_valid():
            errors = serializer.errors
            details = [f"{k}: {v[0] if isinstance(v, list) else v}" for k, v in errors.items()]
            raise ValidationError(message=details[0] if details else "Validation error", details=details)

        dealer = serializer.save()
        return Response(DealerSerializer(dealer).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def dealer_detail(request, pk):
    try:
        dealer = Dealer.objects.get(id=pk)
    except (Dealer.DoesNotExist, ValueError):
        raise NotFound(f"Dealer with id '{pk}' not found")

    return Response(DealerSerializer(dealer).data)


# -----------------------------------------------------------------------------
# Orders
# -----------------------------------------------------------------------------
@api_view(["GET", "POST"])
def order_list_create(request):
    if request.method == "GET":
        queryset = Order.objects.all().prefetch_related("items__product").select_related("dealer").order_by("-created_at")

        dealer_id = request.query_params.get("dealer_id")
        if dealer_id:
            queryset = queryset.filter(dealer_id=dealer_id)

        status_param = request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status=status_param)

        paginator = ContractPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = OrderSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    elif request.method == "POST":
        dealer_id = request.data.get("dealer_id")
        items = request.data.get("items")
        idempotency_key = request.headers.get("Idempotency-Key")

        if not dealer_id:
            raise ValidationError("dealer_id is required", details=["Missing dealer_id"])

        order, created = create_draft_order_service(
            dealer_id=dealer_id,
            items_data=items,
            idempotency_key=idempotency_key,
        )

        resp_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(OrderSerializer(order).data, status=resp_status)


@api_view(["GET"])
def order_detail(request, order_number):
    try:
        order = (
            Order.objects.prefetch_related("items__product")
            .select_related("dealer")
            .get(order_number=order_number)
        )
    except Order.DoesNotExist:
        raise NotFound(f"Order '{order_number}' not found")

    return Response(OrderSerializer(order).data)


# -----------------------------------------------------------------------------
# Dealer Assistant (GenAI)
# -----------------------------------------------------------------------------
@api_view(["POST"])
def assistant_chat(request):
    session_id = request.data.get("session_id")
    dealer_id = request.data.get("dealer_id")
    message = request.data.get("message")

    if not session_id or not isinstance(session_id, str):
        raise ValidationError(message="session_id is required", details=["Missing or invalid session_id"])

    if dealer_id is None or isinstance(dealer_id, bool) or not isinstance(dealer_id, int):
        raise ValidationError(message="dealer_id must be a valid integer", details=["Missing or invalid dealer_id"])

    if not message or not isinstance(message, str):
        raise ValidationError(message="message is required", details=["Missing or invalid message"])

    from .assistant import assistant_chat_turn

    result = assistant_chat_turn(
        session_id=session_id.strip(),
        dealer_id=dealer_id,
        user_message=message.strip(),
    )
    return Response(result, status=status.HTTP_200_OK)


# -----------------------------------------------------------------------------
# Forecasting and Reorder (ML)
# -----------------------------------------------------------------------------
@api_view(["GET"])
def forecast_detail(request, sku):
    from .reorder import reorder_service

    data = reorder_service.get_forecast_for_sku(sku)
    return Response(data, status=status.HTTP_200_OK)


@api_view(["GET"])
def reorder_suggestions(request):
    from .reorder import reorder_service

    suggestions = reorder_service.get_reorder_suggestions()
    return Response({"results": suggestions}, status=status.HTTP_200_OK)
