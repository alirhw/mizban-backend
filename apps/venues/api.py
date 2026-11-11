"""Django Ninja router for the venues app (Venues, operating hours, design add-ons, subscriptions).

Mounted centrally in config/api.py. Endpoints land here task by task;
views stay thin (Architecture Spec section 14): authenticate, validate
via schemas.py, delegate to services.py, map domain errors.
"""
from ninja import Router

router = Router(tags=["venues"])
