from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import *
from django.core.exceptions import ValidationError
from django.utils import timezone


# Signal for InventoryTransaction: Update Inventory when a transaction is created
@receiver(post_save, sender=InventoryTransaction)
def update_inventory_on_transaction(sender, instance, created, **kwargs):
    if created:
        Inventory.update_inventory(instance.motorcycle_model)


# Signal for SupplierDeliveryItem: Create InventoryTransaction when a new item is saved
@receiver(post_save, sender=SupplierDeliveryItem)
def create_inventory_transaction_on_delivery_item_save(
    sender, instance, created, **kwargs
):
    if created:
        try:
            InventoryTransaction.objects.create(
                transaction_type="SUPPLIER_DELIVERY",
                motorcycle_model=instance.motorcycle_model,
                quantity=instance.delivered_quantity,
                reference_model="SupplierDeliveryItem",
                reference_id=instance.pk,
                remarks=f"Delivery from {instance.delivery.payment.supplier.name} - {instance.delivery.delivery_reference}",
            )
        except Exception as e:
            print(
                f"ERROR: Failed to create InventoryTransaction for SupplierDeliveryItem {instance.pk}: {e}"
            )
