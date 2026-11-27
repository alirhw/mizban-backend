"""Root URL configuration: Django Admin plus the versioned Ninja API."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from apps.billing.views import sandbox_pay_view

from .api import api

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", api.urls),
    path("billing/sandbox/pay/<str:authority>/", sandbox_pay_view, name="billing-sandbox-pay"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
