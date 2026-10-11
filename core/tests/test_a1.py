import re
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from core.models import Product, Dealer, Order, OrderItem

MONEY_REGEX = re.compile(r"^-?\d+\.\d{2}$")


class BackendCoreA1Tests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dealer = Dealer.objects.create(
            dealer_code="DLR-TEST-01",
            name="Test Dealer Ltd",
            city="Bengaluru",
            phone="9876543210",
            email="test@dealer.com",
            gstin="29ABCDE1234F1Z5",
            credit_limit=Decimal("50000.00"),
        )
        self.product = Product.objects.create(
            sku="TST-1001",
            name="High Performance Brake Pad",
            category="Brakes",
            brand="Brembo",
            vehicle_fitment="KTM Duke 390",
            price=Decimal("1500.00"),
            stock=50,
            description="Premium brake pad",
        )
        self.product2 = Product.objects.create(
            sku="TST-1002",
            name="Air Filter Universal",
            category="Filters",
            brand="K&N",
            vehicle_fitment="Universal",
            price=Decimal("800.00"),
            stock=20,
            description="High flow air filter",
        )

    def test_health_check(self):
        res = self.client.get("/api/health/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "ok"})

    def test_products_list_and_filters(self):
        res = self.client.get("/api/products/?page_size=10")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("count", data)
        self.assertIn("results", data)
        self.assertGreaterEqual(data["count"], 2)

        first = data["results"][0]
        for field in ("sku", "name", "category", "brand", "vehicle_fitment", "price", "stock", "description"):
            self.assertIn(field, first)
        self.assertTrue(MONEY_REGEX.match(first["price"]))
        self.assertIsInstance(first["stock"], int)

        # Search filter
        res_search = self.client.get("/api/products/?search=Brembo")
        self.assertEqual(res_search.status_code, 200)
        skus = [p["sku"] for p in res_search.json()["results"]]
        self.assertIn("TST-1001", skus)

        # Category filter
        res_cat = self.client.get("/api/products/?category=Brakes")
        self.assertEqual(res_cat.status_code, 200)
        skus = [p["sku"] for p in res_cat.json()["results"]]
        self.assertIn("TST-1001", skus)

        # Vehicle filter
        res_veh = self.client.get("/api/products/?vehicle=Duke")
        self.assertEqual(res_veh.status_code, 200)
        skus = [p["sku"] for p in res_veh.json()["results"]]
        self.assertIn("TST-1001", skus)

    def test_product_detail_and_404(self):
        res = self.client.get("/api/products/TST-1001/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["sku"], "TST-1001")

        res_404 = self.client.get("/api/products/NON-EXISTENT/")
        self.assertEqual(res_404.status_code, 404)
        err = res_404.json().get("error", {})
        self.assertEqual(err.get("code"), "NOT_FOUND")
        self.assertIn("message", err)
        self.assertIsInstance(err.get("details"), list)

    def test_product_create_and_duplicate(self):
        payload = {
            "sku": "NEW-2001",
            "name": "Spark Plug",
            "category": "Engine",
            "brand": "NGK",
            "vehicle_fitment": "Universal",
            "price": "250.50",
            "description": "Iridium spark plug",
        }
        res = self.client.post("/api/products/", payload, format="json")
        self.assertEqual(res.status_code, 201)
        created = res.json()
        self.assertEqual(created["sku"], "NEW-2001")
        self.assertEqual(created["stock"], 0)
        self.assertEqual(created["price"], "250.50")

        # Duplicate SKU -> 409 DUPLICATE
        res_dup = self.client.post("/api/products/", payload, format="json")
        self.assertEqual(res_dup.status_code, 409)
        err = res_dup.json()["error"]
        self.assertEqual(err["code"], "DUPLICATE")

        # Invalid price (<= 0) -> 400 VALIDATION_ERROR
        bad_payload = dict(payload, sku="BAD-PRICE", price="0.00")
        res_bad = self.client.post("/api/products/", bad_payload, format="json")
        self.assertEqual(res_bad.status_code, 400)
        self.assertEqual(res_bad.json()["error"]["code"], "VALIDATION_ERROR")

    def test_product_patch(self):
        res = self.client.patch("/api/products/TST-1001/", {"price": "1650.00"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["price"], "1650.00")

        # Attempt to change SKU
        res_sku = self.client.patch("/api/products/TST-1001/", {"sku": "DIFFERENT-SKU"}, format="json")
        self.assertEqual(res_sku.status_code, 400)
        self.assertEqual(res_sku.json()["error"]["code"], "VALIDATION_ERROR")

    def test_inventory_update(self):
        res = self.client.put("/api/inventory/TST-1001/", {"quantity": 88, "reason": "Restock"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"sku": "TST-1001", "quantity": 88})

        # Product detail reflects updated stock
        detail = self.client.get("/api/products/TST-1001/").json()
        self.assertEqual(detail["stock"], 88)

        # Negative quantity -> 400 VALIDATION_ERROR
        res_neg = self.client.put("/api/inventory/TST-1001/", {"quantity": -5}, format="json")
        self.assertEqual(res_neg.status_code, 400)
        self.assertEqual(res_neg.json()["error"]["code"], "VALIDATION_ERROR")

        # Unknown SKU -> 404 NOT_FOUND
        res_404 = self.client.put("/api/inventory/NO-SKU/", {"quantity": 10}, format="json")
        self.assertEqual(res_404.status_code, 404)
        self.assertEqual(res_404.json()["error"]["code"], "NOT_FOUND")

    def test_dealers_endpoints(self):
        res = self.client.get("/api/dealers/")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("count", data)
        self.assertIn("results", data)

        res_detail = self.client.get(f"/api/dealers/{self.dealer.id}/")
        self.assertEqual(res_detail.status_code, 200)
        self.assertEqual(res_detail.json()["dealer_code"], "DLR-TEST-01")

        # Create dealer
        new_dealer_payload = {
            "dealer_code": "DLR-NEW-02",
            "name": "Apex Spares",
            "city": "Chennai",
            "credit_limit": "25000.00",
        }
        res_create = self.client.post("/api/dealers/", new_dealer_payload, format="json")
        self.assertEqual(res_create.status_code, 201)
        self.assertEqual(res_create.json()["dealer_code"], "DLR-NEW-02")

        # Duplicate dealer_code -> 409 DUPLICATE
        res_dup = self.client.post("/api/dealers/", new_dealer_payload, format="json")
        self.assertEqual(res_dup.status_code, 409)
        self.assertEqual(res_dup.json()["error"]["code"], "DUPLICATE")

    def test_create_draft_order_success_and_stock_not_deducted(self):
        initial_stock = Product.objects.get(sku="TST-1001").stock
        payload = {
            "dealer_id": self.dealer.id,
            "items": [
                {"sku": "TST-1001", "quantity": 2},
                {"sku": "TST-1002", "quantity": 1},
            ],
        }
        res = self.client.post("/api/orders/", payload, format="json")
        self.assertEqual(res.status_code, 201)
        data = res.json()

        self.assertEqual(data["dealer_id"], self.dealer.id)
        self.assertEqual(data["status"], "DRAFT")
        self.assertTrue(data["order_number"].startswith("ORD-"))
        self.assertEqual(len(data["items"]), 2)

        # Money calculations
        # TST-1001: 1500 * 2 = 3000, tax = 540, total = 3540
        # TST-1002: 800 * 1 = 800, tax = 144, total = 944
        # subtotal = 3800, tax = 684, grand = 4484
        self.assertEqual(data["subtotal"], "3800.00")
        self.assertEqual(data["tax_total"], "684.00")
        self.assertEqual(data["grand_total"], "4484.00")

        # Draft order MUST NOT mutate stock
        after_stock = Product.objects.get(sku="TST-1001").stock
        self.assertEqual(initial_stock, after_stock)

        # Retrieve order
        res_get = self.client.get(f"/api/orders/{data['order_number']}/")
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.json()["order_number"], data["order_number"])

    def test_create_order_validations(self):
        # Empty items
        res = self.client.post("/api/orders/", {"dealer_id": self.dealer.id, "items": []}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR")

        # Unknown dealer
        res = self.client.post("/api/orders/", {"dealer_id": 999999, "items": [{"sku": "TST-1001", "quantity": 1}]}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR")

        # Unknown SKU
        res = self.client.post("/api/orders/", {"dealer_id": self.dealer.id, "items": [{"sku": "UNKNOWN-SKU", "quantity": 1}]}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR")

        # Duplicate SKU in items
        res = self.client.post(
            "/api/orders/",
            {
                "dealer_id": self.dealer.id,
                "items": [
                    {"sku": "TST-1001", "quantity": 1},
                    {"sku": "TST-1001", "quantity": 2},
                ],
            },
            format="json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR")

        # Non-positive quantity
        res = self.client.post("/api/orders/", {"dealer_id": self.dealer.id, "items": [{"sku": "TST-1001", "quantity": 0}]}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR")

    def test_idempotency_key(self):
        payload = {
            "dealer_id": self.dealer.id,
            "items": [{"sku": "TST-1001", "quantity": 1}],
        }
        headers = {"HTTP_IDEMPOTENCY_KEY": "unique-idem-key-1"}

        res1 = self.client.post("/api/orders/", payload, format="json", **headers)
        self.assertEqual(res1.status_code, 201)
        ord1 = res1.json()["order_number"]

        # Same key, same payload -> returns original order
        res2 = self.client.post("/api/orders/", payload, format="json", **headers)
        self.assertIn(res2.status_code, [200, 201])
        self.assertEqual(res2.json()["order_number"], ord1)

        # Same key, different payload -> 409 IDEMPOTENCY_CONFLICT
        diff_payload = {
            "dealer_id": self.dealer.id,
            "items": [{"sku": "TST-1001", "quantity": 5}],
        }
        res3 = self.client.post("/api/orders/", diff_payload, format="json", **headers)
        self.assertEqual(res3.status_code, 409)
        self.assertEqual(res3.json()["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_product_price_validation_decimals(self):
        # More than 2 decimal places -> 400 VALIDATION_ERROR
        bad_payload = {
            "sku": "BAD-DEC-1",
            "name": "Bad Decimal Part",
            "category": "Accessories",
            "brand": "Generic",
            "vehicle_fitment": "Universal",
            "price": "199.999",
            "description": "Too many decimals",
        }
        res = self.client.post("/api/products/", bad_payload, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR")

    def test_draft_order_uses_updated_catalogue_price(self):
        # Update product price from 1500.00 to 1800.00
        patch_res = self.client.patch("/api/products/TST-1001/", {"price": "1800.00"}, format="json")
        self.assertEqual(patch_res.status_code, 200)

        # Create new draft order
        order_payload = {
            "dealer_id": self.dealer.id,
            "items": [{"sku": "TST-1001", "quantity": 1}],
        }
        res = self.client.post("/api/orders/", order_payload, format="json")
        self.assertEqual(res.status_code, 201)
        data = res.json()
        item = data["items"][0]
        self.assertEqual(item["unit_price"], "1800.00")
        self.assertEqual(item["line_subtotal"], "1800.00")
        self.assertEqual(item["line_tax"], "324.00")
        self.assertEqual(item["line_total"], "2124.00")

    def test_seed_data_idempotency_twice(self):
        from django.core.management import call_command

        # Run seed_data command twice
        call_command("seed_data")
        prod_count_1 = Product.objects.count()
        dealer_count_1 = Dealer.objects.count()

        call_command("seed_data")
        prod_count_2 = Product.objects.count()
        dealer_count_2 = Dealer.objects.count()

        self.assertEqual(prod_count_1, prod_count_2)
        self.assertEqual(dealer_count_1, dealer_count_2)
        self.assertGreaterEqual(prod_count_1, 600)
        self.assertGreaterEqual(dealer_count_1, 25)
