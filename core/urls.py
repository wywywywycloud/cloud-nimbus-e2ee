from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("legal/offer/", views.offer, name="offer"),
    path("legal/privacy/", views.privacy, name="privacy"),
    path("healthz/", views.health, name="health"),
    path("readyz/", views.readiness, name="readiness"),
    path("ops/metrics/", views.metrics, name="metrics"),
]
