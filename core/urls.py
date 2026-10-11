from django.urls import path
from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("products/", views.product_list_create, name="product-list-create"),
    path("products/<str:sku>/", views.product_detail, name="product-detail"),
    path("inventory/<str:sku>/", views.inventory_update, name="inventory-update"),
    path("dealers/", views.dealer_list_create, name="dealer-list-create"),
    path("dealers/<int:pk>/", views.dealer_detail, name="dealer-detail"),
    path("orders/", views.order_list_create, name="order-list-create"),
    path("orders/<str:order_number>/", views.order_detail, name="order-detail"),
    path("assistant/chat/", views.assistant_chat, name="assistant-chat"),
    path("forecast/<str:sku>/", views.forecast_detail, name="forecast-detail"),
    path("reorder-suggestions/", views.reorder_suggestions, name="reorder-suggestions"),
]
