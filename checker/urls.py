from django.urls import path

from . import views

app_name = "checker"

urlpatterns = [
    path("", views.home, name="home"),
    path("check/", views.check, name="check"),
    path("report/<str:registration>/", views.report, name="report"),
]
