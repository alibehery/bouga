from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import (
    ProductSize, FabricType, PrintPattern, ProductSKU,
    InventoryLocation, InventoryBalance, InventoryMovement,
    FabricMaterial, FabricInventory, FabricPrintJob,
    Customer, OrderStatus, Order, OrderItem,
    ExpenseType, Expense,
)

admin.site.register(ProductSize)
admin.site.register(FabricType)
admin.site.register(PrintPattern)
admin.site.register(ProductSKU)

admin.site.register(InventoryLocation)
admin.site.register(InventoryBalance)
admin.site.register(InventoryMovement)

admin.site.register(FabricMaterial)
admin.site.register(FabricInventory)
admin.site.register(FabricPrintJob)

admin.site.register(Customer)
admin.site.register(OrderStatus)
admin.site.register(Order)
admin.site.register(OrderItem)

admin.site.register(ExpenseType)
admin.site.register(Expense)
