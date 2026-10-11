import csv
from decimal import Decimal
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Product, Dealer


class Command(BaseCommand):
    help = "Load catalogue.csv and dealers.csv from data/ into the database. Idempotent."

    def handle(self, *args, **options):
        data_dir = settings.DATA_DIR

        catalogue_path = data_dir / "catalogue.csv"
        dealers_path = data_dir / "dealers.csv"

        if not catalogue_path.exists():
            self.stderr.write(self.style.ERROR(f"Catalogue file not found at {catalogue_path}"))
            return
        if not dealers_path.exists():
            self.stderr.write(self.style.ERROR(f"Dealers file not found at {dealers_path}"))
            return

        with transaction.atomic():
            # Seed Products
            products = []
            with open(catalogue_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    products.append(
                        Product(
                            sku=row["sku"].strip(),
                            name=row["name"].strip(),
                            category=row["category"].strip(),
                            brand=row["brand"].strip(),
                            vehicle_fitment=row["vehicle_fitment"].strip(),
                            price=Decimal(row["price"].strip()),
                            stock=int(row["stock"].strip()),
                            description=row["description"].strip(),
                        )
                    )

            if products:
                Product.objects.bulk_create(
                    products,
                    update_conflicts=True,
                    unique_fields=["sku"],
                    update_fields=[
                        "name",
                        "category",
                        "brand",
                        "vehicle_fitment",
                        "price",
                        "stock",
                        "description",
                    ],
                )
            self.stdout.write(self.style.SUCCESS(f"Successfully seeded {len(products)} products"))

            # Seed Dealers
            dealers = []
            with open(dealers_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    credit_limit_raw = row.get("credit_limit", "0.00").strip()
                    dealers.append(
                        Dealer(
                            dealer_code=row["dealer_code"].strip(),
                            name=row["name"].strip(),
                            city=row.get("city", "").strip(),
                            phone=row.get("phone", "").strip(),
                            email=row.get("email", "").strip(),
                            gstin=row.get("gstin", "").strip(),
                            credit_limit=Decimal(credit_limit_raw) if credit_limit_raw else Decimal("0.00"),
                        )
                    )

            if dealers:
                Dealer.objects.bulk_create(
                    dealers,
                    update_conflicts=True,
                    unique_fields=["dealer_code"],
                    update_fields=[
                        "name",
                        "city",
                        "phone",
                        "email",
                        "gstin",
                        "credit_limit",
                    ],
                )
            self.stdout.write(self.style.SUCCESS(f"Successfully seeded {len(dealers)} dealers"))
