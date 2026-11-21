"""Central Django Ninja API instance (v1).

Every domain app exposes an (initially empty) Router in apps.<app>.api and
it is mounted here under its /api/v1/ prefix (Architecture Spec section
13). The global error contract of section 19 is registered once, here.
"""
from django.conf import settings
from django.db import connection
from ninja import NinjaAPI, Schema

from apps.accounts.api import router as accounts_router
from apps.billing.api import router as billing_router
from apps.bookings.api import router as bookings_router
from apps.panoramas.api import router as panoramas_router, spaces_router, venue_spaces_router
from apps.reviews.api import router as reviews_router
from apps.scheduling.api import router as scheduling_router
from apps.venues.api import router as venues_router
from apps.wallets.api import router as wallets_router
from core.exceptions import register_exception_handlers

api = NinjaAPI(
    title="Miz Ban API",
    version="1.0.0",
    description="Two-sided 360-degree visual table-reservation platform - API v1.",
    urls_namespace="api-v1",
)

register_exception_handlers(api)


class HealthOut(Schema):
    status: str
    db: bool
    redis: bool


@api.get("/healthz", response=HealthOut, tags=["system"])
def healthz(request):
    """Readiness probe (Task T-004): bounded DB and Redis checks.

    Never exposes credentials, connection strings or internals.
    """
    db_ok = False
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        db_ok = True
    except Exception:
        db_ok = False

    redis_ok = False
    try:
        import redis as redis_lib

        client = redis_lib.Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1
        )
        redis_ok = bool(client.ping())
    except Exception:
        redis_ok = False

    return {"status": "ok", "db": db_ok, "redis": redis_ok}


api.add_router("/auth", accounts_router)
api.add_router("/venues", venues_router)
api.add_router("/venues", venue_spaces_router)
api.add_router("/panoramas", panoramas_router)
api.add_router("/spaces", spaces_router)
api.add_router("/scheduling", scheduling_router)
api.add_router("/bookings", bookings_router)
api.add_router("/billing", billing_router)
api.add_router("/wallet", wallets_router)
api.add_router("/reviews", reviews_router)
