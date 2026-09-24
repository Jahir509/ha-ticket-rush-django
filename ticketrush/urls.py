from django.urls import path

from tickets import views

urlpatterns = [
    path("healthz", views.healthz),
    path("readyz", views.readyz),
    path("info", views.info),
    path("events", views.create_event),
    path("events/<str:event_id>", views.get_event),
    path("events/<str:event_id>/stats", views.stats),
    path("events/<str:event_id>/purchase", views.purchase),
]
