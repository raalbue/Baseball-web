from django.urls import path
from . import views

app_name = "manage"

urlpatterns = [
    path("users/", views.UserListView.as_view(), name="user-list"),
    path("users/add/", views.UserCreateView.as_view(), name="user-add"),
    path("users/<int:pk>/edit/", views.UserEditView.as_view(), name="user-edit"),
    path("users/<int:pk>/delete/", views.UserDeleteView.as_view(), name="user-delete"),
    path("users/<int:pk>/lists/", views.ManagedListView.as_view(), name="user-lists"),
    path("users/<int:pk>/lists/<int:list_pk>/delete/",
         views.ManagedListDeleteView.as_view(), name="user-list-delete"),
    path("lists/<int:list_pk>/items/",
         views.ManagedItemListView.as_view(), name="user-list-items"),
    path("lists/<int:list_pk>/items/<int:item_pk>/edit/",
         views.ManagedItemUpdateView.as_view(), name="user-item-edit"),
    path("lists/<int:list_pk>/items/<int:item_pk>/delete/",
         views.ManagedItemDeleteView.as_view(), name="user-item-delete"),
    # SQL injection demo endpoints — remove before any real deployment
    path("demo/sqli/vulnerable/", views.sqli_vulnerable, name="sqli-vulnerable"),
    path("demo/sqli/safe/", views.sqli_safe, name="sqli-safe"),
]
