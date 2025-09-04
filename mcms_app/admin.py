from django.contrib import admin
from .models import *

admin.site.register(Motorcycle)
admin.site.register(Supplier)
admin.site.register(Customer)
admin.site.register(SupplierPayment)
admin.site.register(SupplierPaymentItem)
admin.site.register(SupplierDelivery)
admin.site.register(SupplierDeliveryItem)
admin.site.register(Deposit)
admin.site.register(Withdrawal)
admin.site.register(Loan)
admin.site.register(LoanRepayment)
