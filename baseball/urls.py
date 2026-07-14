from django.urls import path
from . import views

urlpatterns = [
    path("",                   views.GameListView.as_view(),   name="baseball-list"),
    path("new/",               views.GameCreateView.as_view(), name="baseball-new"),
    path("roster/",            views.RosterView.as_view(),    name="baseball-roster"),
    path("<int:pk>/",          views.GameDetailView.as_view(), name="baseball-detail"),
    path("<int:pk>/roll/",     views.RollView.as_view(),       name="baseball-roll"),
    path("<int:pk>/simulate/", views.SimulateView.as_view(),   name="baseball-simulate"),
]
