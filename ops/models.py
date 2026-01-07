
from __future__ import annotations

from django.db import models
from django.core.validators import MinValueValidator
# ops/models.py
from django.utils.text import slugify

def build_sku_code(size, fabric_type, print_pattern) -> str:
    """
    Example outputs:
      BAG-STD-COTTON-PLAIN
      BAG-BABY-CANVAS-P03
      BAG-LRG-COTTON-FLOWERS
    """
    size_code = (size.code or "").upper()
    fabric_code = slugify(fabric_type.name).upper().replace("-", "")[:10]  # COTTON, CANVAS...
    if print_pattern is None:
        print_code = "PLAIN"
    else:
        # you can choose one of these styles:
        # print_code = f"P{print_pattern.id:02d}"   # P03
        print_code = slugify(print_pattern.name).upper().replace("-", "")[:12]  # FLOWERS
    return f"BAG-{size_code}-{fabric_code}-{print_code}"



class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# -------------------- Catalog --------------------

class ProductSize(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)  # BABY, STANDARD, LARGE
    display_name = models.CharField(max_length=50)

    def __str__(self) -> str:
        return self.display_name


class FabricType(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class PrintPattern(TimeStampedModel):
    """
    Your 6 prints (patterns).
    Plain bag => print_pattern is NULL on ProductSKU.
    """
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class ProductSKU(TimeStampedModel):
    """
    Sellable + storable unit.
    Plain bag => print_pattern=None
    """
    sku_code = models.CharField(max_length=60, unique=True, blank=True)
    size = models.ForeignKey(ProductSize, on_delete=models.PROTECT)
    fabric_type = models.ForeignKey(FabricType, on_delete=models.PROTECT)
    print_pattern = models.ForeignKey(
        PrintPattern,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Leave empty for plain (no print).",
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["size", "fabric_type", "print_pattern"],
                name="uniq_sku_by_size_fabric_print",
            )
        ]

    def __str__(self) -> str:
        return self.sku_code

    def save(self, *args, **kwargs):
        if not self.sku_code:
            self.sku_code = build_sku_code(self.size, self.fabric_type, self.print_pattern)
        super().save(*args, **kwargs)


# -------------------- Inventory (finished goods) --------------------

class InventoryLocation(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)

    def __str__(self) -> str:
        return self.name


class InventoryBalance(TimeStampedModel):
    sku = models.ForeignKey(ProductSKU, on_delete=models.CASCADE)
    location = models.ForeignKey(InventoryLocation, on_delete=models.PROTECT)
    qty_on_hand = models.IntegerField(default=0)
    reorder_level = models.IntegerField(default=0, validators=[MinValueValidator(0)])

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sku", "location"],
                name="uniq_balance_per_sku_location",
            )
        ]

    def __str__(self) -> str:
        return f"{self.sku} @ {self.location}: {self.qty_on_hand}"


class InventoryMovement(TimeStampedModel):
    IN_ = "IN"
    OUT = "OUT"
    ADJ = "ADJ"
    MOVEMENT_CHOICES = [(IN_, "IN"), (OUT, "OUT"), (ADJ, "ADJUST")]

    sku = models.ForeignKey(ProductSKU, on_delete=models.CASCADE)
    location = models.ForeignKey(InventoryLocation, on_delete=models.PROTECT)
    movement_type = models.CharField(max_length=3, choices=MOVEMENT_CHOICES)
    qty = models.IntegerField(validators=[MinValueValidator(1)])
    ref_table = models.CharField(max_length=50, null=True, blank=True)  # e.g. "order"
    ref_id = models.CharField(max_length=50, null=True, blank=True)     # e.g. "123"
    note = models.TextField(blank=True, default="")

    def __str__(self) -> str:
        return f"{self.movement_type} {self.qty} {self.sku}"


# -------------------- Fabric inventory (raw + printed fabric) --------------------

class FabricMaterial(TimeStampedModel):
    """
    RAW fabric: is_printed=False, print_pattern=NULL
    PRINTED fabric: is_printed=True,  print_pattern=<pattern>
    """
    fabric_type = models.ForeignKey(FabricType, on_delete=models.PROTECT)
    uom = models.CharField(max_length=20, default="meter")  # meters, kg, etc.
    is_printed = models.BooleanField(default=False)
    print_pattern = models.ForeignKey(
        PrintPattern,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Only set if is_printed=True",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["fabric_type", "uom", "is_printed", "print_pattern"],
                name="uniq_fabric_material_variant",
            )
        ]

    def __str__(self) -> str:
        if self.is_printed and self.print_pattern:
            return f"{self.fabric_type} (PRINTED: {self.print_pattern})"
        return f"{self.fabric_type} (RAW)"


class FabricInventory(TimeStampedModel):
    fabric_material = models.ForeignKey(FabricMaterial, on_delete=models.CASCADE)
    location = models.ForeignKey(InventoryLocation, on_delete=models.PROTECT)
    qty_on_hand = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["fabric_material", "location"],
                name="uniq_fabric_balance_per_material_location",
            )
        ]

    def __str__(self) -> str:
        return f"{self.fabric_material} @ {self.location}: {self.qty_on_hand} {self.fabric_material.uom}"


class FabricPrintJob(TimeStampedModel):
    """
    Converts RAW fabric -> PRINTED fabric.
    """
    print_pattern = models.ForeignKey(PrintPattern, on_delete=models.PROTECT)
    input_fabric_material = models.ForeignKey(
        FabricMaterial, on_delete=models.PROTECT, related_name="print_inputs"
    )
    input_qty = models.DecimalField(max_digits=14, decimal_places=3)
    output_fabric_material = models.ForeignKey(
        FabricMaterial, on_delete=models.PROTECT, related_name="print_outputs"
    )
    output_qty = models.DecimalField(max_digits=14, decimal_places=3)
    print_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self) -> str:
        return f"Print {self.print_pattern} ({self.input_qty}->{self.output_qty})"


# -------------------- Customers + Orders --------------------

class Customer(TimeStampedModel):
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    address = models.TextField(blank=True, default="")

    def __str__(self) -> str:
        return self.full_name


class OrderStatus(TimeStampedModel):
    code = models.CharField(max_length=40, unique=True)  # NEW, SHIPPED, ...
    display_name = models.CharField(max_length=80)
    sort_order = models.IntegerField(default=0)

    def __str__(self) -> str:
        return self.display_name


class Order(TimeStampedModel):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    status = models.ForeignKey(OrderStatus, on_delete=models.PROTECT)
    order_date = models.DateField()
    notes = models.TextField(blank=True, default="")

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self) -> str:
        return f"Order #{self.id}"


class OrderItem(TimeStampedModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    sku = models.ForeignKey(ProductSKU, on_delete=models.PROTECT)
    qty = models.IntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self) -> str:
        return f"{self.order} - {self.sku} x{self.qty}"


class OrderStatusHistory(TimeStampedModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    from_status = models.ForeignKey(OrderStatus, on_delete=models.PROTECT, related_name="+")
    to_status = models.ForeignKey(OrderStatus, on_delete=models.PROTECT, related_name="+")

    def __str__(self) -> str:
        return f"{self.order}: {self.from_status} -> {self.to_status}"


# -------------------- Expenses --------------------

class ExpenseType(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class Expense(TimeStampedModel):
    expense_type = models.ForeignKey(ExpenseType, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="EGP")
    expense_date = models.DateField()
    vendor = models.CharField(max_length=120, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    ref_table = models.CharField(max_length=50, null=True, blank=True)
    ref_id = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.expense_type}: {self.amount} {self.currency}"
