from django.urls import include, path, re_path

from . import views

urlpatterns = [
    path("a/", views.a),
    re_path(r"^b/$", views.BView.as_view()),
    path("sub/", include("shop.urls")),
]
