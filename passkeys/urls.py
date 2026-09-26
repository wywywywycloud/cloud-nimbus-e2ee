from django.urls import path

from . import views

app_name = "passkeys"
urlpatterns = [
    path("register/start/", views.register_start, name="register_start"),
    path("register/finish/", views.register_finish, name="register_finish"),
    path("activate/start/", views.activate_start, name="activate_start"),
    path("activate/finish/", views.activate_finish, name="activate_finish"),
    path("login/start/", views.login_start, name="login_start"),
    path("login/finish/", views.login_finish, name="login_finish"),
    path("reset/start/", views.reset_start, name="reset_start"),
    path("reset/finish/", views.reset_finish, name="reset_finish"),
]
