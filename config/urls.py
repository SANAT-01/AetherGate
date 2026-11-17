from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import URLPattern, URLResolver, path
from ninja import NinjaAPI

from apps.analytics.api import router as analytics_router
from apps.gateway.api import router as gateway_router

api = NinjaAPI(title="AetherGate API", version="1.0.0")
api.add_router("", gateway_router)
api.add_router("/analytics", analytics_router)

urlpatterns: list[URLPattern | URLResolver] = [
    path("admin/", admin.site.urls),
    path("v1/", api.urls),
]

if settings.DEBUG:
    # Serving this app via Uvicorn (not `manage.py runserver`) means Django's
    # usual automatic static-file serving in dev never kicks in — add it
    # explicitly here. Never enabled outside DEBUG; a real deployment would
    # serve static files via whitenoise or a reverse proxy instead.
    urlpatterns += staticfiles_urlpatterns()
