from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI

from apps.gateway.api import router as gateway_router

api = NinjaAPI(title="AetherGate API", version="1.0.0")
api.add_router("", gateway_router)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("v1/", api.urls),
]
