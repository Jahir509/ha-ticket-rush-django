from django.urls import path

from users import views


urlpatterns = [
    path("users", views.users),
    path("users/<int:user_id>", views.user_detail),
]
