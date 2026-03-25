from django.urls import path
from . import views

app_name = "accounts"   # ✅ THIS FIXES THE ERROR

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
]