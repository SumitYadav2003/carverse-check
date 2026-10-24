from django.urls import path

from . import views

app_name = "checker"

urlpatterns = [
    path("", views.home, name="home"),
    path("check/", views.check, name="check"),
    path("report/<str:registration>/", views.report, name="report"),
    path("how-it-works/", views.page, {"template": "how_it_works"}, name="how_it_works"),
    path("methodology/", views.methodology, name="methodology"),
    path("help/", views.page, {"template": "help"}, name="help"),
    path("about/", views.page, {"template": "about"}, name="about"),
    path("privacy/", views.page, {"template": "privacy"}, name="privacy"),
    path("terms/", views.page, {"template": "terms"}, name="terms"),
    path("accessibility/", views.page, {"template": "accessibility"}, name="accessibility"),
    path("contact/", views.page, {"template": "contact"}, name="contact"),
    path("models/", views.models_index, name="models"),
    path("models/<slug:make_slug>/", views.models_make, name="models_make"),
    path("models/<slug:make_slug>/<slug:model_slug>/", views.models_model, name="models_model"),
    path("robots.txt", views.robots_txt, name="robots"),
]
