"""Factories for the billing app (PaymentTransactionFactory)."""
import uuid

import factory

from apps.billing.models import PaymentStatus, PaymentTransaction
from apps.bookings.tests.factories import BookingFactory


class PaymentTransactionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PaymentTransaction

    booking = factory.SubFactory(BookingFactory)
    customer = factory.LazyAttribute(lambda o: o.booking.customer)
    amount_toman = factory.LazyAttribute(lambda o: o.booking.amount_online_toman)
    currency = "TOMAN"
    status = PaymentStatus.INITIATED
    provider_name = "sandbox"
    provider_reference = factory.LazyFunction(lambda: f"SBX-{uuid.uuid4().hex[:16].upper()}")
    idempotency_key = factory.LazyFunction(lambda: str(uuid.uuid4()))
    redirect_url = factory.LazyAttribute(
        lambda o: f"https://sandbox.mizban.local/pg/startpay/{o.provider_reference}"
        if o.provider_reference
        else ""
    )
