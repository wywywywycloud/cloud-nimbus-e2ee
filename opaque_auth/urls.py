from django.urls import path

from . import views

app_name = "opaque_auth"

urlpatterns = [
    path("register/start/", views.register_start, name="register_start"),
    path("register/finish/", views.register_finish, name="register_finish"),
    path("login/start/", views.login_start, name="login_start"),
    path("login/finish/", views.login_finish, name="login_finish"),
    path("change/start/", views.change_start, name="change_start"),
    path("change/finish/", views.change_finish, name="change_finish"),
]
