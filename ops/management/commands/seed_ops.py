# ops/management/commands/seed_ops.py
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from ops.models import (
    ProductSize, FabricType, PrintPattern, ProductSKU,
    InventoryLocation, InventoryBalance,
    FabricMaterial, FabricInventory,
    Customer, OrderStatus, Order, OrderItem,
    ExpenseType, Expense,
)

# If you already added auto SKU generation in ProductSKU.save(),
# you can rely on that. Otherwise, we build one here when missing.
def build_sku_code(size: ProductSize, fabric: FabricType, pattern: PrintPattern | None) -> str:
    size_code = (size.code or "").upper()
    fabric_code = (fabric.name or "").strip().upper().replace(" ", "")[:10]
    if pattern is None:
        print_code = "PLAIN"
    else:
        print_code = (pattern.name or "").strip().upper().replace(" ", "")[:12]
    return f"BAG-{size_code}-{fabric_code}-{print_code}"


class Command(BaseCommand):
    help = "Seed ops tables with fake data from a JSON file (idempotent for reference tables)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            type=str,
            default="seed_data.json",
            help="Path to seed_data.json (default: ./seed_data.json)",
        )

    def handle(self, *args, **options):
        path = Path(options["path"]).resolve()
        if not path.exists():
            raise SystemExit(f"Seed file not found: {path}")

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        with transaction.atomic():
            self._seed_reference(data)
            self._seed_skus_and_inventory(data)
            self._seed_fabrics(data)
            self._seed_orders(data)
            self._seed_expenses(data)

        self.stdout.write(self.style.SUCCESS("✅ Seeding completed."))

    # ---------- helpers ----------
    def _get_size(self, code: str) -> ProductSize:
        return ProductSize.objects.get(code=code)

    def _get_fabric(self, name: str) -> FabricType:
        return FabricType.objects.get(name=name)

    def _get_print(self, name: str | None) -> PrintPattern | None:
        if name is None:
            return None
        return PrintPattern.objects.get(name=name)

    def _get_location(self, name: str) -> InventoryLocation:
        return InventoryLocation.objects.get(name=name)

    def _get_sku(self, size_code: str, fabric_name: str, print_name: str | None) -> ProductSKU:
        size = self._get_size(size_code)
        fabric = self._get_fabric(fabric_name)
        pattern = self._get_print(print_name)

        sku, created = ProductSKU.objects.get_or_create(
            size=size,
            fabric_type=fabric,
            print_pattern=pattern,
            defaults={
                "sku_code": build_sku_code(size, fabric, pattern),
                "unit_price": Decimal("0.00"),
                "is_active": True,
            },
        )
        # Ensure sku_code exists if field was blank
        if not sku.sku_code:
            sku.sku_code = build_sku_code(size, fabric, pattern)
            sku.save(update_fields=["sku_code"])
        return sku

    # ---------- seed steps ----------
    def _seed_reference(self, data: dict):
        # Sizes
        for row in data.get("product_sizes", []):
            ProductSize.objects.update_or_create(
                code=row["code"],
                defaults={"display_name": row.get("display_name", row["code"])},
            )

        # Fabrics
        for row in data.get("fabric_types", []):
            FabricType.objects.update_or_create(
                name=row["name"],
                defaults={"is_active": bool(row.get("is_active", True))},
            )

        # Prints
        for row in data.get("print_patterns", []):
            PrintPattern.objects.update_or_create(
                name=row["name"],
                defaults={"is_active": bool(row.get("is_active", True))},
            )

        # Locations
        for row in data.get("inventory_locations", []):
            InventoryLocation.objects.update_or_create(name=row["name"], defaults={})

        # Order statuses
        for row in data.get("order_statuses", []):
            OrderStatus.objects.update_or_create(
                code=row["code"],
                defaults={
                    "display_name": row.get("display_name", row["code"]),
                    "sort_order": int(row.get("sort_order", 0)),
                },
            )

        # Customers
        for row in data.get("customers", []):
            Customer.objects.update_or_create(
                full_name=row["full_name"],
                defaults={
                    "phone": row.get("phone", ""),
                    "email": row.get("email", ""),
                    "address": row.get("address", ""),
                },
            )

        # Expense types
        for row in data.get("expense_types", []):
            ExpenseType.objects.update_or_create(name=row["name"], defaults={"is_active": True})

    def _seed_skus_and_inventory(self, data: dict):
        # SKUs
        for row in data.get("product_skus", []):
            sku = self._get_sku(row["size_code"], row["fabric_type"], row.get("print_pattern"))
            # update price if provided
            if "unit_price" in row and row["unit_price"] is not None:
                sku.unit_price = Decimal(str(row["unit_price"]))
                sku.is_active = bool(row.get("is_active", True))
                sku.save(update_fields=["unit_price", "is_active"])

        # Inventory balances
        for row in data.get("inventory_balances", []):
            sku = self._get_sku(row["size_code"], row["fabric_type"], row.get("print_pattern"))
            loc = self._get_location(row["location"])
            InventoryBalance.objects.update_or_create(
                sku=sku,
                location=loc,
                defaults={
                    "qty_on_hand": int(row.get("qty_on_hand", 0)),
                    "reorder_level": int(row.get("reorder_level", 0)),
                },
            )

    def _seed_fabrics(self, data: dict):
        # Fabric materials
        for row in data.get("fabric_materials", []):
            fabric = self._get_fabric(row["fabric_type"])
            pattern = self._get_print(row.get("print_pattern"))
            FabricMaterial.objects.update_or_create(
                fabric_type=fabric,
                uom=row.get("uom", "meter"),
                is_printed=bool(row.get("is_printed", False)),
                print_pattern=pattern if bool(row.get("is_printed", False)) else None,
                defaults={},
            )

        # Fabric inventory
        for row in data.get("fabric_inventory", []):
            fabric = self._get_fabric(row["fabric_type"])
            pattern = self._get_print(row.get("print_pattern"))
            mat, _ = FabricMaterial.objects.get_or_create(
                fabric_type=fabric,
                uom=row.get("uom", "meter"),
                is_printed=bool(row.get("is_printed", False)),
                print_pattern=pattern if bool(row.get("is_printed", False)) else None,
            )
            loc = self._get_location(row["location"])
            FabricInventory.objects.update_or_create(
                fabric_material=mat,
                location=loc,
                defaults={"qty_on_hand": Decimal(str(row.get("qty_on_hand", "0.000")))},
            )

    def _seed_orders(self, data: dict):
        for row in data.get("orders", []):
            customer = Customer.objects.get(full_name=row["customer"])
            status = OrderStatus.objects.get(code=row["status"])

            # Idempotent-ish: don't duplicate if same ref exists in notes
            notes = row.get("notes", "")
            existing = Order.objects.filter(customer=customer, order_date=row["order_date"], notes=notes).first()
            if existing:
                order = existing
            else:
                order = Order.objects.create(
                    customer=customer,
                    status=status,
                    order_date=row["order_date"],
                    notes=notes,
                    shipping_fee=Decimal(str(row.get("shipping_fee", "0.00"))),
                    discount=Decimal(str(row.get("discount", "0.00"))),
                )

            # Clear old items to keep deterministic
            order.items.all().delete()

            subtotal = Decimal("0.00")
            for item in row.get("items", []):
                sku = self._get_sku(item["size_code"], item["fabric_type"], item.get("print_pattern"))
                qty = int(item["qty"])
                unit_price = Decimal(str(item.get("unit_price", sku.unit_price)))
                line_total = unit_price * qty
                OrderItem.objects.create(
                    order=order,
                    sku=sku,
                    qty=qty,
                    unit_price=unit_price,
                    line_total=line_total,
                )
                subtotal += line_total

            order.subtotal = subtotal
            order.total = subtotal + Decimal(str(order.shipping_fee)) - Decimal(str(order.discount))
            order.save(update_fields=["subtotal", "total", "shipping_fee", "discount"])

    def _seed_expenses(self, data: dict):
        for row in data.get("expenses", []):
            et = ExpenseType.objects.get(name=row["expense_type"])
            Expense.objects.update_or_create(
                expense_type=et,
                amount=Decimal(str(row["amount"])),
                expense_date=row["expense_date"],
                defaults={
                    "currency": row.get("currency", "EGP"),
                    "vendor": row.get("vendor", ""),
                    "notes": row.get("notes", ""),
                },
            )
