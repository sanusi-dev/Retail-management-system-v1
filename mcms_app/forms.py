from .models import *
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.forms import inlineformset_factory
from django.db.models import Sum, F, Q
from decimal import Decimal
from django.forms.models import BaseInlineFormSet
from decimal import Decimal, InvalidOperation
from django.urls import reverse
import datetime


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "phone", "address"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "required": True}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class SupplierFilterForm(forms.Form):
    name = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Supplier Name"}
        ),
    )
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Phone Number"}
        ),
    )


class SupplierPaymentForm(forms.ModelForm):
    class Meta:
        model = SupplierPayment
        fields = [
            "supplier",
            "amount_paid",
            "payment_date",
            "payment_method",
            "remarks",
        ]
        widgets = {
            "supplier": forms.Select(attrs={"class": "form-control", "required": True}),
            "amount_paid": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "required": True,
                    "step": "0.01",
                    "min": "0.01",
                }
            ),
            "payment_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date", "required": True}
            ),
            "payment_method": forms.Select(attrs={"class": "form-control"}),
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["amount_paid"].widget.attrs["min"] = "200000.00"
        self.fields["supplier"].queryset = Supplier.objects.all()
        self.fields["payment_date"].widget.attrs["max"] = (
            timezone.now().date() + timezone.timedelta(days=365)
        ).isoformat()

        if self.instance and self.instance.pk:
            if not self.instance.is_editable:
                for field_name in self.fields:
                    self.fields[field_name].disabled = True
                if self.instance.status == SupplierPayment.COMPLETED:
                    self.add_error(
                        None, "This payment is COMPLETED and cannot be edited."
                    )
                elif self.instance.status == SupplierPayment.CANCELLED:
                    self.add_error(
                        None, "This payment is CANCELLED and cannot be edited."
                    )
                elif self.instance.has_deliveries:
                    self.add_error(
                        None,
                        "This payment cannot be edited because deliveries have already been made.",
                    )

    def clean_amount_paid(self):
        amount = self.cleaned_data.get("amount_paid")
        if amount is not None:
            if amount <= Decimal("0.00"):
                raise ValidationError("Payment amount must be greater than zero.")
            if amount < Decimal("200000.00"):
                raise ValidationError("Minimum payment amount is ₦200,000.00.")
        return amount

    def clean_payment_date(self):
        date = self.cleaned_data.get("payment_date")
        if date:
            today = timezone.now().date()
            one_year_future = today + timezone.timedelta(days=365)

            if isinstance(date, datetime.datetime):
                date = date.date()

            if date > one_year_future:
                raise ValidationError(
                    "Payment date cannot be more than one year in the future."
                )

            if not self.instance.pk and date < today:
                raise ValidationError(
                    "Payment date cannot be in the past for new payments."
                )

        if date and isinstance(date, datetime.datetime) and timezone.is_naive(date):
            return timezone.make_aware(date, timezone.get_default_timezone())
        return date

    def clean(self):
        cleaned_data = super().clean()
        if (
            self.instance
            and self.instance.pk
            and not self.instance.is_editable
            and self.has_changed()
        ):
            raise ValidationError(
                f"This payment (Status: {self.instance.get_status_display()}) cannot be edited at this stage."
            )
        return cleaned_data


class SupplierPaymentItemForm(forms.ModelForm):
    class Meta:
        model = SupplierPaymentItem
        fields = ["motorcycle_model", "expected_quantity", "unit_price", "remarks"]
        widgets = {
            "motorcycle_model": forms.Select(
                attrs={"class": "form-control motorcycle-select", "required": True}
            ),
            "expected_quantity": forms.NumberInput(
                attrs={
                    "class": "form-control quantity-input",
                    "required": True,
                    "min": "1",
                }
            ),
            "unit_price": forms.NumberInput(
                attrs={
                    "class": "form-control price-input",
                    "required": True,
                    "step": "0.01",
                    "min": "0.01",
                }
            ),
            "remarks": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["motorcycle_model"].queryset = Motorcycle.objects.all()

        if hasattr(self.instance, "payment") and self.instance.payment:
            if self.instance.payment.status != SupplierPayment.ACTIVE or (
                self.instance.payment.status == SupplierPayment.ACTIVE
                and self.instance.payment.has_deliveries
            ):
                for field_name in self.fields:
                    self.fields[field_name].disabled = True

    def clean_expected_quantity(self):
        quantity = self.cleaned_data.get("expected_quantity")
        if quantity is not None and quantity <= 0:
            raise ValidationError("Expected quantity must be greater than zero.")
        return quantity

    def clean_unit_price(self):
        price = self.cleaned_data.get("unit_price")
        if price is not None and price <= Decimal("0.00"):
            raise ValidationError("Unit price must be greater than zero.")
        return price

    def clean(self):
        cleaned_data = super().clean()
        expected_quantity = cleaned_data.get("expected_quantity")
        unit_price = cleaned_data.get("unit_price")
        parent_amount_paid = self.parent_payment_amount_paid

        if parent_amount_paid is None and self.prefix:
            formset_instance = getattr(self, "formset_parent_instance", None)
            if formset_instance and hasattr(formset_instance, "amount_paid"):
                parent_amount_paid = formset_instance.amount_paid

        if (
            expected_quantity is not None
            and unit_price is not None
            and parent_amount_paid is not None
        ):
            item_total_value = Decimal(str(expected_quantity)) * unit_price
            if item_total_value > parent_amount_paid:
                raise ValidationError(
                    f"The value of this single item (₦{item_total_value:,.2f}) "
                    f"exceeds the total Amount Paid for this payment (₦{parent_amount_paid:,.2f})."
                )
        return cleaned_data


class BaseSupplierPaymentItemFormSet(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self.parent_amount_paid_for_items = kwargs.pop(
            "parent_amount_paid_for_items", None
        )
        super().__init__(*args, **kwargs)

        for form in self.forms:
            form.parent_payment_amount_paid = self.parent_amount_paid_for_items
            form.formset_parent_instance = self.instance

    def clean(self):
        super().clean()

        if any(self.errors):
            return

        total_items_value = Decimal("0.00")
        active_forms_count = 0
        motorcycle_models_seen = set()

        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data:
                continue
            if self.can_delete and self._should_delete_form(form):
                continue

            active_forms_count += 1

            motorcycle_model = form.cleaned_data.get("motorcycle_model")
            if motorcycle_model:
                if motorcycle_model in motorcycle_models_seen:
                    form.add_error(
                        "motorcycle_model",
                        "Duplicate motorcycle model in payment items. Each item must be unique.",
                    )
                motorcycle_models_seen.add(motorcycle_model)

            expected_quantity = form.cleaned_data.get("expected_quantity", 0)
            unit_price = form.cleaned_data.get("unit_price", Decimal("0.00"))

            if expected_quantity > 0 and unit_price > Decimal("0.00"):
                total_items_value += Decimal(str(expected_quantity)) * unit_price

        current_amount_paid_for_validation = self.parent_amount_paid_for_items

        if (
            current_amount_paid_for_validation is None
            and self.instance
            and hasattr(self.instance, "amount_paid")
        ):
            current_amount_paid_for_validation = self.instance.amount_paid

        if current_amount_paid_for_validation is not None:
            if active_forms_count > 0:
                if total_items_value != current_amount_paid_for_validation:
                    difference = current_amount_paid_for_validation - total_items_value
                    error_message = (
                        f"The total value of all items (₦{total_items_value:,.2f}) "
                        f"must be equal to the Amount Paid (₦{current_amount_paid_for_validation:,.2f}). "
                        f"Difference: ₦{difference:,.2f}."
                    )
                    raise ValidationError(error_message, code="total_mismatch")

            elif (
                active_forms_count == 0
                and current_amount_paid_for_validation > Decimal("0.00")
            ):
                raise ValidationError(
                    "If Amount Paid is greater than zero (₦{:.2f}), at least one payment item must be specified.".format(
                        current_amount_paid_for_validation
                    ),
                    code="no_items_for_payment",
                )
        elif active_forms_count > 0:
            raise ValidationError(
                "Cannot validate item totals: The payment's Amount Paid is not available to the item formset for comparison.",
                code="missing_amount_paid_for_validation",
            )


class SupplierPaymentItemFormSetHelper:
    def get_formset(self, data=None, instance=None, parent_amount_paid_for_items=None):
        formset_kwargs = {"form_kwargs": {}}
        if parent_amount_paid_for_items is not None:
            formset_kwargs["parent_amount_paid_for_items"] = (
                parent_amount_paid_for_items
            )

        PaymentItemFormSet = forms.inlineformset_factory(
            SupplierPayment,
            SupplierPaymentItem,
            form=SupplierPaymentItemForm,
            formset=BaseSupplierPaymentItemFormSet,
            fields=["motorcycle_model", "expected_quantity", "unit_price", "remarks"],
            extra=1,
            can_delete=True,
        )
        return PaymentItemFormSet(
            data=data, instance=instance, prefix="items", **formset_kwargs
        )


class PaymentFilterForm(forms.Form):
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.all(),
        required=False,
        empty_label="All Suppliers",
        widget=forms.Select(attrs={"class": "form-control "}),
    )
    payment_method = forms.ChoiceField(
        choices=[("", "All Methods")]
        + SupplierPayment._meta.get_field("payment_method").choices,
        required=False,
        widget=forms.Select(attrs={"class": "form-control "}),
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control ", "type": "date"}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    status = forms.ChoiceField(
        choices=[("", "All Statuses")] + SupplierPayment.STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )


class SupplierDeliveryForm(forms.ModelForm):
    class Meta:
        model = SupplierDelivery
        fields = ["payment", "delivery_date", "remarks"]
        widgets = {
            "payment": forms.Select(attrs={"class": "form-control", "required": True}),
            "delivery_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date", "required": True}
            ),
            "remarks": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        available_payments_queryset = (
            SupplierPayment.objects.filter(
                status=SupplierPayment.ACTIVE, payment_items__isnull=False
            )
            .annotate(
                annotated_total_expected_quantity=Coalesce(
                    Sum("payment_items__expected_quantity"),
                    0,
                    output_field=DecimalField(),
                ),
                annotated_total_delivered_quantity=Coalesce(
                    Sum(
                        "deliveries__delivery_items__delivered_quantity",
                        filter=Q(deliveries__is_cancelled=False),
                    ),
                    0,
                    output_field=DecimalField(),
                ),
            )
            .filter(
                Q(
                    annotated_total_delivered_quantity__lt=F(
                        "annotated_total_expected_quantity"
                    )
                )
                | Q(annotated_total_expected_quantity=Decimal("0.00"))
            )
            .select_related("supplier")
            .distinct()
            .order_by("payment_reference")
        )

        if self.instance and self.instance.pk and self.instance.payment:
            current_payment_qs = SupplierPayment.objects.filter(
                pk=self.instance.payment.pk
            )
            self.fields["payment"].queryset = (
                (available_payments_queryset | current_payment_qs)
                .distinct()
                .order_by("payment_reference")
            )
        else:
            self.fields["payment"].queryset = available_payments_queryset
        if self.instance.pk and self.instance.is_cancelled:
            for field_name in self.fields:
                self.fields[field_name].disabled = True
            self.add_error(None, "This delivery is CANCELLED and cannot be edited.")

    def clean(self):
        cleaned_data = super().clean()
        payment = cleaned_data.get("payment")

        if self.instance.pk and self.instance.is_cancelled and self.has_changed():
            raise ValidationError("This delivery is CANCELLED and cannot be edited.")

        if payment:
            if payment.status == SupplierPayment.CANCELLED:
                self.add_error(
                    "payment", "Cannot create delivery for a CANCELLED payment."
                )
            elif payment.status == SupplierPayment.COMPLETED:
                if not self.instance or not self.instance.pk:
                    self.add_error(
                        "payment",
                        f"Payment {payment.payment_reference} is already COMPLETED. No new deliveries can be added.",
                    )
            if not payment.payment_items.exists():
                self.add_error(
                    "payment", "Cannot create delivery for payment with no items."
                )
        return cleaned_data


class SupplierDeliveryItemForm(forms.ModelForm):
    class Meta:
        model = SupplierDeliveryItem
        fields = ["motorcycle_model", "delivered_quantity", "delivery_remarks"]
        widgets = {
            "motorcycle_model": forms.Select(
                attrs={
                    "class": "form-control delivery-motorcycle-select",
                    "required": True,
                }
            ),
            "delivered_quantity": forms.NumberInput(
                attrs={
                    "class": "form-control delivered-quantity-input",
                    "required": True,
                    "min": "1",
                }
            ),
            "delivery_remarks": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if hasattr(self.instance, "delivery") and self.instance.delivery:
            payment_items = self.instance.delivery.payment.payment_items.all()
            self.fields["motorcycle_model"].queryset = Motorcycle.objects.filter(
                payment_items__in=payment_items
            ).distinct()
        else:
            self.fields["motorcycle_model"].queryset = Motorcycle.objects.all()


SupplierDeliveryItemFormSet = inlineformset_factory(
    SupplierDelivery,
    SupplierDeliveryItem,
    form=SupplierDeliveryItemForm,
    extra=1,
    can_delete=True,
    min_num=1,
    validate_min=True,
)


class SupplierDeliveryItemFormSetHelper:
    def __init__(self, formset_class=SupplierDeliveryItemFormSet):
        self.formset_class = formset_class

    def get_formset(self, data=None, instance=None):
        class ValidatedDeliveryFormSet(self.formset_class):
            def clean(self):
                super().clean()

                forms_to_process = [
                    form
                    for form in self.forms
                    if form.cleaned_data and not form.cleaned_data.get("DELETE", False)
                ]

                if not forms_to_process:
                    raise ValidationError("At least one delivery item is required")

                motorcycle_models_seen = {}

                for i, form in enumerate(forms_to_process):
                    motorcycle_model = form.cleaned_data.get("motorcycle_model")
                    delivered_quantity = form.cleaned_data.get("delivered_quantity")

                    if motorcycle_model:
                        if motorcycle_model in motorcycle_models_seen:
                            form.add_error(
                                "motorcycle_model",
                                f"Duplicate motorcycle model: {motorcycle_model}",
                            )
                        motorcycle_models_seen[motorcycle_model] = i

                        if self.instance and self.instance.pk and self.instance.payment:
                            try:
                                payment_item = self.instance.payment.payment_items.get(
                                    motorcycle_model=motorcycle_model
                                )
                            except SupplierPaymentItem.DoesNotExist:
                                form.add_error(
                                    "motorcycle_model",
                                    f"'{motorcycle_model}' was not included in the original payment.",
                                )
                                continue

                            if (
                                delivered_quantity is not None
                                and delivered_quantity > 0
                            ):
                                total_delivered_existing_in_db = (
                                    SupplierDeliveryItem.objects.filter(
                                        delivery__payment=self.instance.payment,
                                        motorcycle_model=motorcycle_model,
                                        delivery__is_cancelled=False,
                                    )
                                    .exclude(
                                        pk=form.instance.pk if form.instance else None
                                    )
                                    .aggregate(total=Sum("delivered_quantity"))["total"]
                                    or 0
                                )

                                if (
                                    total_delivered_existing_in_db + delivered_quantity
                                ) > payment_item.expected_quantity:
                                    form.add_error(
                                        "delivered_quantity",
                                        f"Total delivered quantity for {motorcycle_model} "
                                        f"({total_delivered_existing_in_db + delivered_quantity}) exceeds "
                                        f"expected quantity ({payment_item.expected_quantity}).",
                                    )

        return ValidatedDeliveryFormSet(data=data, instance=instance)


class DeliveryFilterForm(forms.Form):
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.all(),
        required=False,
        empty_label="All Suppliers",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    payment = forms.ModelChoiceField(
        queryset=SupplierPayment.objects.all(),
        required=False,
        empty_label="All Payments",
        widget=forms.Select(attrs={"class": "form-control "}),
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control ", "type": "date"}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    show_cancelled = forms.BooleanField(
        required=False, widget=forms.CheckboxInput(attrs={"class": "form-check-input"})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        payment_choices = [("", "All Payments")] + [
            (p.id, p.payment_reference) for p in SupplierPayment.objects.all()
        ]
        self.fields["payment"].choices = payment_choices


class InventoryFilterForm(forms.Form):
    brand = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Brand"}),
    )
    model_name = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Model Name"}
        ),
    )
    min_quantity = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "placeholder": "Min Qty"}
        ),
    )
    max_quantity = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "placeholder": "Max Qty"}
        ),
    )


class MotorcycleForm(forms.ModelForm):
    class Meta:
        model = Motorcycle
        fields = ["name", "brand"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter Motorcycle model name",
                }
            ),
            "brand": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Enter Motorcycle brand name",
                }
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get("name")
        brand = cleaned_data.get("brand")

        if name and brand:
            query = Motorcycle.objects.filter(name__iexact=name, brand__iexact=brand)
            if self.instance and self.instance.pk:
                query = query.exclude(pk=self.instance.pk)
            if query.exists():
                error_msg = f"A motorcycle with the brand '{brand}' and model name '{name}' already exists."
                self.add_error("name", error_msg)
                self.add_error("brand", error_msg)
        return cleaned_data


class MotorcycleFilterForm(forms.Form):
    name = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Model Name"}
        ),
        label="Name",
    )
    brand = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Brand"}),
        label="brand",
    )
    status = forms.ChoiceField(
        choices=[("", "All Statuses")] + Motorcycle.STATUS_CHOICES,
        required=False,
        label="Status",
        widget=forms.Select(attrs={"class": "form-control"}),
    )


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["firstname", "lastname", "phone", "address"]
        widgets = {
            "firstname": forms.TextInput(attrs={"class": "form-control"}),
            "lastname": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                }
            ),
        }


class CustomerFilterForm(forms.Form):
    firstname = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "firstname"}
        ),
    )
    lastname = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "lastname"}
        ),
    )
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "phone"}),
    )


class DepositForm(forms.ModelForm):
    class Meta:
        model = Deposit
        fields = [
            "customer",
            "deposit_amount",
            "deposit_date",
            "deposit_type",
            "transaction_note",
        ]
        widgets = {
            "customer": forms.Select(attrs={"class": "form-select"}),
            "deposit_amount": forms.NumberInput(
                attrs={"class": "form-control", "placeholder": "Enter amount"}
            ),
            "deposit_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "deposit_type": forms.Select(attrs={"class": "form-select"}),
            "transaction_note": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Enter a transaction note (optional)",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["deposit_date"].initial = timezone.now().date()

        for field_name, field in self.fields.items():
            if isinstance(
                field.widget,
                (forms.TextInput, forms.NumberInput, forms.Textarea, forms.DateInput),
            ):
                field.widget.attrs.update({"class": "form-control"})
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.update({"class": "form-select"})

    def clean(self):
        cleaned_data = super().clean()
        customer = cleaned_data.get("customer")
        deposit_amount = cleaned_data.get("deposit_amount")
        deposit_date = cleaned_data.get("deposit_date")

        if not customer:
            raise ValidationError("Please select a valid customer for this deposit.")

        if deposit_amount is not None:
            if deposit_amount <= 0:
                raise ValidationError("Deposit amount must be greater than zero.")

        if deposit_date:
            if hasattr(deposit_date, "date"):
                deposit_date_obj = deposit_date.date()
            else:
                deposit_date_obj = deposit_date

            current_date = timezone.now().date()
            if deposit_date_obj > current_date:
                raise ValidationError("Deposit date cannot be in the future.")

        return cleaned_data

    def save(self, commit=True):
        deposit = super().save(commit=False)

        if commit:
            with transaction.atomic():
                old_amount = None
                if deposit.pk:
                    try:
                        old_deposit = Deposit.objects.get(pk=deposit.pk)
                        old_amount = old_deposit.deposit_amount
                    except Deposit.DoesNotExist:
                        pass

                deposit.save()

                if old_amount is not None and old_amount != deposit.deposit_amount:
                    deposit.update_status_based_on_withdrawals()

        return deposit


class DepositFilterForm(forms.Form):
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all(),
        required=False,
        empty_label="All Customers",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    deposit_amount = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "placeholder": "Deposit amount"}
        ),
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                "class": "form-control",
                "type": "date",
                "placeholder": "Choose Date From:",
            }
        ),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                "class": "form-control",
                "type": "date",
                "placeholder": "Choose Date To",
            }
        ),
    )
    deposit_type = forms.ChoiceField(
        choices=[("", "All Types")] + Deposit.DEPOSIT_TYPE_CHOICES,
        required=False,
        label="Deposit Type",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    deposit_status = forms.ChoiceField(
        choices=[("", "All Status")] + Deposit.DEPOSIT_STATUS_CHOICES,
        required=False,
        label="Deposit Status",
        widget=forms.Select(attrs={"class": "form-control"}),
    )


class WithdrawalForm(forms.ModelForm):
    class Meta:
        model = Withdrawal
        fields = ["deposit", "withdrawal_amount", "withdrawal_date", "remarks"]
        widgets = {
            "deposit": forms.Select(attrs={"class": "form-select"}),
            "withdrawal_amount": forms.NumberInput(
                attrs={"class": "form-control", "placeholder": "Enter amount"}
            ),
            "withdrawal_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "remarks": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Enter a remark (optional)",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["withdrawal_date"].initial = timezone.now().date()

        if not self.instance.pk:
            self.fields["deposit"].queryset = Deposit.objects.filter(
                deposit_status__in=["active"]
            ).select_related("customer")
        else:
            current_deposit = self.instance.deposit
            available_deposits = Deposit.objects.filter(
                deposit_status__in=["active", "completed"]
            ).select_related("customer")

            if current_deposit and current_deposit not in available_deposits:
                from django.db.models import Q

                self.fields["deposit"].queryset = Deposit.objects.filter(
                    Q(deposit_status__in=["active", "completed"])
                    | Q(pk=current_deposit.pk)
                ).select_related("customer")

    def clean(self):
        cleaned_data = super().clean()
        deposit = cleaned_data.get("deposit")
        withdrawal_amount = cleaned_data.get("withdrawal_amount")
        withdrawal_date = cleaned_data.get("withdrawal_date")

        if not deposit:
            raise ValidationError("Please select a valid deposit for this withdrawal.")

        if withdrawal_amount is not None:
            if withdrawal_amount <= 0:
                raise ValidationError("Withdrawal amount must be greater than zero.")

        if withdrawal_date:
            if hasattr(withdrawal_date, "date"):
                withdrawal_date_obj = withdrawal_date.date()
            else:
                withdrawal_date_obj = withdrawal_date

            current_date = timezone.now().date()
            if withdrawal_date_obj > current_date:
                raise ValidationError("Withdrawal date cannot be in the future.")

        if deposit and withdrawal_amount:
            total_withdrawn_from_deposit = deposit.get_total_withdrawn()

            if self.instance.pk:
                try:
                    original_withdrawal = Withdrawal.objects.get(pk=self.instance.pk)
                    if original_withdrawal.withdrawal_status == "completed":
                        total_withdrawn_from_deposit -= (
                            original_withdrawal.withdrawal_amount
                        )
                except Withdrawal.DoesNotExist:
                    pass

            total_after_withdrawal = total_withdrawn_from_deposit + withdrawal_amount
            remaining_in_deposit = deposit.deposit_amount - total_withdrawn_from_deposit

            if withdrawal_amount > remaining_in_deposit:
                raise ValidationError(
                    f"Withdrawal amount exceeds remaining balance in this deposit. "
                    f"Available in deposit {deposit.deposit_reference}: ₦{remaining_in_deposit:.2f}"
                )

            customer = deposit.customer
            total_deposit = (
                Deposit.objects.filter(
                    customer=customer, deposit_status__in=["active", "completed"]
                ).aggregate(total_amount=Sum("deposit_amount"))["total_amount"]
                or 0
            )

            total_withdrawn = (
                Withdrawal.objects.filter(
                    deposit__customer=customer, withdrawal_status="completed"
                ).aggregate(total_amount=Sum("withdrawal_amount"))["total_amount"]
                or 0
            )

            if self.instance.pk:
                try:
                    original_withdrawal = Withdrawal.objects.get(pk=self.instance.pk)
                    if original_withdrawal.withdrawal_status == "completed":
                        total_withdrawn -= original_withdrawal.withdrawal_amount
                except Withdrawal.DoesNotExist:
                    pass

            available_balance = total_deposit - total_withdrawn

            if total_deposit == 0:
                raise ValidationError("This customer has no deposit balance.")

            if withdrawal_amount > available_balance:
                raise ValidationError(
                    f"Insufficient overall balance. Available balance: ₦{available_balance:.2f}"
                )

        return cleaned_data

    def save(self, commit=True):
        withdrawal = super().save(commit=False)

        if commit:
            with transaction.atomic():
                withdrawal.save()

        return withdrawal


class WithdrawalFilterForm(forms.Form):
    deposit = forms.ModelChoiceField(
        queryset=Deposit.objects.all(),
        required=False,
        empty_label="All deposits",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    withdrawal_amount = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "placeholder": "Withdrawal Amount"}
        ),
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    withdrawal_status = forms.ChoiceField(
        choices=[("", "All Status")] + Withdrawal.WITHDRAWAL_STATUS_CHOICES,
        required=False,
        label="Withdrawal Status",
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        deposit_choices = [("", "All Deposits")] + [
            (d.id, d.deposit_reference) for d in Deposit.objects.all()
        ]
        self.fields["deposit"].choices = deposit_choices


class LoanFilterForm(forms.Form):
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Customer",
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control "}),
    )
    status = forms.ChoiceField(
        choices=[("", "All Statuses")] + Loan.LOAN_STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Loan Status",
    )
    min_amount = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(
            attrs={"class": "form-control ", "placeholder": "Min Amount"}
        ),
        label="Min. Loan Amount",
    )
    max_amount = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "placeholder": "Max Amount"}
        ),
        label="Max. Loan Amount",
    )


class LoanRepaymentFilterForm(forms.Form):
    loan = forms.ModelChoiceField(
        queryset=Loan.objects.all().order_by("-loan_date"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select select2"}),
        empty_label="Loan",
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select select2"}),
        empty_label="Customer",
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    amount = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "placeholder": "Amount"}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        loan_choices = [("", "All Loans")] + [
            (l.id, l.loan_reference) for l in Loan.objects.all()
        ]
        self.fields["loan"].choices = loan_choices


class LoanForm(forms.ModelForm):
    class Meta:
        model = Loan
        fields = ["customer", "loan_amount", "remarks"]
        widgets = {
            "customer": forms.Select(attrs={"class": "form-select select2"}),
            "loan_amount": forms.NumberInput(
                attrs={
                    "placeholder": "Enter loan amount",
                    "class": "form-control",
                    "step": "0.01",
                }
            ),
            "remarks": forms.TextInput(
                attrs={
                    "placeholder": "Remarks (e.g., for bike purchase)",
                    "class": "form-control",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.update({"class": "form-select select2"})
            else:
                field.widget.attrs.update({"class": "form-control"})

    def clean_loan_amount(self):
        amount = self.cleaned_data.get("loan_amount")
        if amount is not None and amount <= Decimal("0.00"):
            raise forms.ValidationError("Loan amount must be greater than zero.")
        return amount


class LoanRepaymentForm(forms.ModelForm):
    class Meta:
        model = LoanRepayment
        fields = ["loan", "repayment_amount", "repayment_date", "remarks"]
        widgets = {
            "loan": forms.Select(attrs={"class": "form-select select2"}),
            "repayment_amount": forms.NumberInput(
                attrs={
                    "placeholder": "Enter repayment amount",
                    "class": "form-control",
                    "step": "0.01",
                }
            ),
            "repayment_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "remarks": forms.TextInput(
                attrs={
                    "placeholder": "Remarks (e.g., partial payment)",
                    "class": "form-control",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["loan"].queryset = (
            Loan.objects.filter(loan_status__in=["pending", "partially repaid"])
            .select_related("customer")
            .order_by("-loan_date", "customer__firstname")
        )
        if not self.instance.pk:
            self.fields["repayment_date"].initial = timezone.now().date()

    def clean_repayment_amount(self):
        amount = self.cleaned_data.get("repayment_amount")
        if amount is not None and amount <= Decimal("0.00"):
            raise forms.ValidationError("Repayment amount must be greater than zero.")
        return amount

    def clean(self):
        cleaned_data = super().clean()
        loan = cleaned_data.get("loan")
        repayment_amount = cleaned_data.get("repayment_amount")
        repayment_date = cleaned_data.get("repayment_date")

        if not loan:
            self.add_error("loan", "Please select a valid loan.")
            return cleaned_data

        if loan.loan_status == "repaid":
            self.add_error(
                "loan", f"Loan {loan.loan_reference} is already fully repaid."
            )
        if loan.loan_status == "cancelled":
            self.add_error("loan", f"Loan {loan.loan_reference} has been cancelled.")

        balance_to_validate_against = loan.balance
        if self.instance and self.instance.pk:
            balance_to_validate_against += self.instance.repayment_amount

        if repayment_amount and balance_to_validate_against is not None:
            if repayment_amount > balance_to_validate_against:
                self.add_error(
                    "repayment_amount",
                    f"Repayment (₦{repayment_amount:,.2f}) exceeds remaining loan balance (₦{balance_to_validate_against:,.2f}).",
                )

        if repayment_date:
            repayment_date_part = repayment_date.date()
            current_date = timezone.now().date()
            if repayment_date_part > current_date:
                self.add_error(
                    "repayment_date", "Repayment date cannot be in the future."
                )

            if loan and loan.loan_date:
                loan_date_part = loan.loan_date.date()
                if repayment_date_part < loan_date_part:
                    self.add_error(
                        "repayment_date",
                        "Repayment date cannot be before the loan date.",
                    )

    def save(self, commit=True):
        repayment = super().save(commit=False)

        if not commit:
            return repayment

        is_editing = bool(self.instance.pk)
        original_loan_of_repayment = None
        original_repayment_amount = Decimal("0.00")

        if is_editing:
            try:
                original_repayment_db = LoanRepayment.objects.get(pk=self.instance.pk)
                original_loan_of_repayment = original_repayment_db.loan
                original_repayment_amount = original_repayment_db.repayment_amount
            except LoanRepayment.DoesNotExist:
                is_editing = False

        repayment.save()

        current_loan_of_repayment = repayment.loan

        if is_editing:
            if original_loan_of_repayment == current_loan_of_repayment:
                current_loan_of_repayment.balance += original_repayment_amount
                current_loan_of_repayment.update_balance(repayment.repayment_amount)
            else:
                if original_loan_of_repayment:
                    original_loan_of_repayment.update_balance(
                        -original_repayment_amount
                    )

                current_loan_of_repayment.update_balance(repayment.repayment_amount)
        else:
            current_loan_of_repayment.update_balance(repayment.repayment_amount)

        return repayment


class SaleCreateForm(forms.ModelForm):
    class Meta:
        model = Sale
        fields = [
            "customer",
            "motorcycle",
            "sale_date",
            "payment_type",
            "final_price",
            "engine_no",
            "chassis_no",
            "remarks",
        ]
        widgets = {
            "customer": forms.Select(
                attrs={"class": "form-select select2", "placeholder": "Customer"}
            ),
            "motorcycle": forms.Select(attrs={"class": "form-select select2"}),
            "sale_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "payment_type": forms.Select(attrs={"class": "form-select"}),
            "final_price": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "engine_no": forms.TextInput(attrs={"class": "form-control"}),
            "chassis_no": forms.TextInput(attrs={"class": "form-control"}),
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sale_date"].initial = timezone.now().date()

    def clean_sale_date(self):
        sale_datetime_obj = self.cleaned_data.get("sale_date")

        if sale_datetime_obj:
            sale_date_part = sale_datetime_obj.date()

            current_date = timezone.now().date()
            if sale_date_part > current_date:
                raise forms.ValidationError("Sale date cannot be in the future.")

        return sale_datetime_obj

    def clean_final_price(self):
        final_price = self.cleaned_data.get("final_price")
        if final_price is not None and final_price <= Decimal("0.00"):
            raise forms.ValidationError("Final price must be greater than zero.")
        return final_price

    def clean_engine_no(self):
        engine_no = self.cleaned_data.get("engine_no")
        if Sale.objects.filter(engine_no__iexact=engine_no).exists():
            raise forms.ValidationError(
                "This Engine Number has already been recorded in a sale."
            )
        return engine_no

    def clean_chassis_no(self):
        chassis_no = self.cleaned_data.get("chassis_no")
        if Sale.objects.filter(chassis_no__iexact=chassis_no).exists():
            raise forms.ValidationError(
                "This Chassis Number has already been recorded in a sale."
            )
        return chassis_no

    def clean(self):
        cleaned_data = super().clean()
        motorcycle = cleaned_data.get("motorcycle")
        payment_type = cleaned_data.get("payment_type")
        final_price = cleaned_data.get("final_price")
        customer = cleaned_data.get("customer")

        if motorcycle:
            try:
                inventory = Inventory.objects.get(motorcycle_model=motorcycle)
                if inventory.current_quantity <= 0:
                    self.add_error(
                        "motorcycle", f"'{motorcycle}' is currently out of stock."
                    )
            except Inventory.DoesNotExist:
                self.add_error(
                    "motorcycle",
                    f"Inventory record for '{motorcycle}' not found. Cannot sell.",
                )

        if payment_type == "DEPOSIT" and customer and final_price is not None:
            available_balance = Withdrawal.get_customer_balance(customer)
            if available_balance < final_price:
                self.add_error(
                    "final_price",
                    f"Customer's available deposit balance (₦{available_balance:,.2f}) is insufficient "
                    f"to cover the final price (₦{final_price:,.2f}).",
                )
        return cleaned_data


class SaleEditForm(forms.ModelForm):
    class Meta:
        model = Sale
        fields = ["sale_date", "engine_no", "chassis_no", "remarks"]
        widgets = {
            "sale_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "engine_no": forms.TextInput(attrs={"class": "form-control"}),
            "chassis_no": forms.TextInput(attrs={"class": "form-control"}),
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = getattr(self, "instance", None)
        if instance and instance.pk:
            pass

    def clean_sale_date(self):
        sale_datetime_obj = self.cleaned_data.get("sale_date")

        if sale_datetime_obj:
            sale_date_part = sale_datetime_obj.date()

            current_date = timezone.now().date()
            if sale_date_part > current_date:
                raise forms.ValidationError("Sale date cannot be in the future.")

        return sale_datetime_obj

    def clean_engine_no(self):
        engine_no = self.cleaned_data.get("engine_no")
        if self.instance and self.instance.pk and engine_no != self.instance.engine_no:
            if (
                Sale.objects.filter(engine_no__iexact=engine_no)
                .exclude(pk=self.instance.pk)
                .exists()
            ):
                raise forms.ValidationError(
                    "This Engine Number is already in use by another sale."
                )
        return engine_no

    def clean_chassis_no(self):
        chassis_no = self.cleaned_data.get("chassis_no")
        if (
            self.instance
            and self.instance.pk
            and chassis_no != self.instance.chassis_no
        ):
            if (
                Sale.objects.filter(chassis_no__iexact=chassis_no)
                .exclude(pk=self.instance.pk)
                .exists()
            ):
                raise forms.ValidationError(
                    "This Chassis Number is already in use by another sale."
                )
        return chassis_no


class SaleFilterForm(forms.Form):
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all(),
        required=False,
        empty_label="Customer",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    motorcycle = forms.ModelChoiceField(
        queryset=Motorcycle.objects.all(),
        required=False,
        empty_label="Motorcycle",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    engine_no = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "engine_no"}
        ),
        label="Engine_No",
    )
    chasis_no = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "chasis_no"}
        ),
        label="Chasis_No",
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    payment_type = forms.ChoiceField(
        choices=[("", "All types")] + Sale.PAYMENT_TYPE_CHOICES,
        required=False,
        label="Payment Types",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    status = forms.ChoiceField(
        choices=[("", "All Statuses")] + Sale.STATUS_CHOICES,
        required=False,
        label="Sale Status",
        widget=forms.Select(attrs={"class": "form-control"}),
    )


class ActivityLogFilterForm(forms.Form):
    PERIOD_CHOICES = [
        ("today", "Today"),
        ("yesterday", "Yesterday"),
        ("this_week", "This Week"),
        ("last_7_days", "Last 7 Days"),
        ("this_month", "This Month"),
    ]

    VIEW_CHOICES = [
        ("summary", "Summary"),
        ("detailed", "Detailed View"),
    ]

    period = forms.ChoiceField(
        choices=PERIOD_CHOICES,
        required=True,
        label="Select Period",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    view_type = forms.ChoiceField(
        choices=VIEW_CHOICES,
        required=True,
        label="View Type",
        initial="summary",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
