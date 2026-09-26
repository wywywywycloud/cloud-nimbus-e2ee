from django.urls import path

from . import views

app_name = "otp_auth"
urlpatterns = [
    path("setup/start/", views.setup_start, name="setup_start"),
    path("setup/finish/", views.setup_finish, name="setup_finish"),
    path("login/finish/", views.login_finish, name="login_finish"),
]
