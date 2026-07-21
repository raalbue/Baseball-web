from django.urls import path
from . import views

urlpatterns = [
    path("",                   views.GameListView.as_view(),   name="baseball-list"),
    path("new/",               views.Page1View.as_view(),      name="baseball-new"),
    path("roster/",            views.Page2View.as_view(),      name="baseball-roster"),
    path("api/career-stats/<int:player_id>/", views.career_stats_api, name="baseball-career-stats-api"),
    path("<int:pk>/",          views.GameDetailView.as_view(), name="baseball-detail"),
    path("<int:pk>/roll/",     views.RollView.as_view(),       name="baseball-roll"),
    path("<int:pk>/simulate/", views.SimulateView.as_view(),   name="baseball-simulate"),
    path("<int:pk>/replay/",   views.ReplayView.as_view(),     name="baseball-replay"),
    path("<int:pk>/waiting/",  views.WaitingView.as_view(),        name="baseball-waiting"),
    path("<int:pk>/join/",     views.Player2JoinView.as_view(),    name="baseball-join"),
    path("<int:pk>/cancel/",   views.CancelWaitingView.as_view(),  name="baseball-cancel"),
]
