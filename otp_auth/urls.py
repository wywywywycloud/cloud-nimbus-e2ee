from django.urls import path

from . import views

app_name = "otp_auth"
urlpatterns = [
    path("rotate/start/", views.rotate_start, name="rotate_start"),
    path("rotate/finish/", views.rotate_finish, name="rotate_finish"),
    path("setup/start/", views.setup_start, name="setup_start"),
    path("setup/finish/", views.setup_finish, name="setup_finish"),
    path("login/finish/", views.login_finish, name="login_finish"),
]
