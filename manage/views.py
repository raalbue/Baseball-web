from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import connection
from django.forms import modelform_factory
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import DeleteView, ListView

from accounts.mixins import StaffRequiredMixin
from accounts.models import Profile
from todo_app.models import ToDoList, ToDoItem
from .forms import AdminUserCreateForm, AdminUserEditForm, AdminProfileForm

User = get_user_model()

TodoItemEditForm = modelform_factory(ToDoItem, fields=["title", "description", "due_date"])


class UserListView(StaffRequiredMixin, ListView):
    model = User
    template_name = "manage/user_list.html"
    context_object_name = "users"
    queryset = User.objects.select_related("profile").order_by("username")


class UserCreateView(StaffRequiredMixin, View):
    template_name = "manage/user_form.html"

    def get(self, request):
        return render(request, self.template_name, {
            "user_form": AdminUserCreateForm(),
            "profile_form": AdminProfileForm(),
            "action": "Create",
        })

    def post(self, request):
        user_form = AdminUserCreateForm(request.POST)
        profile_form = AdminProfileForm(request.POST)
        if user_form.is_valid() and profile_form.is_valid():
            user = user_form.save()
            profile = user.profile  # created by signal
            profile_form = AdminProfileForm(request.POST, instance=profile)
            profile_form.save()
            messages.success(request, f"User '{user.username}' created.")
            return redirect("manage:user-list")
        return render(request, self.template_name, {
            "user_form": user_form,
            "profile_form": profile_form,
            "action": "Create",
        })


class UserEditView(StaffRequiredMixin, View):
    template_name = "manage/user_form.html"

    def get_user(self, pk):
        return get_object_or_404(User.objects.select_related("profile"), pk=pk)

    def get(self, request, pk):
        target = self.get_user(pk)
        return render(request, self.template_name, {
            "user_form": AdminUserEditForm(instance=target),
            "profile_form": AdminProfileForm(instance=target.profile),
            "target_user": target,
            "action": "Edit",
        })

    def post(self, request, pk):
        target = self.get_user(pk)
        user_form = AdminUserEditForm(request.POST, instance=target)
        profile_form = AdminProfileForm(request.POST, instance=target.profile)
        if user_form.is_valid() and profile_form.is_valid():
            user = user_form.save(commit=False)
            new_password = user_form.cleaned_data.get("new_password")
            if new_password:
                user.set_password(new_password)
            user.save()
            profile_form.save()
            messages.success(request, f"User '{target.username}' updated.")
            return redirect("manage:user-list")
        return render(request, self.template_name, {
            "user_form": user_form,
            "profile_form": profile_form,
            "target_user": target,
            "action": "Edit",
        })


class UserDeleteView(StaffRequiredMixin, DeleteView):
    model = User
    template_name = "manage/user_confirm_delete.html"
    success_url = reverse_lazy("manage:user-list")
    context_object_name = "target_user"

    def post(self, request, *args, **kwargs):
        if self.get_object().pk == request.user.pk:
            messages.error(request, "You cannot delete your own account.")
            return redirect("manage:user-list")
        return super().post(request, *args, **kwargs)


class ManagedListView(StaffRequiredMixin, ListView):
    model = ToDoList
    template_name = "manage/todolist_list.html"
    context_object_name = "todo_lists"

    def get_target_user(self):
        return get_object_or_404(User, pk=self.kwargs["pk"])

    def get_queryset(self):
        return ToDoList.objects.filter(owner=self.get_target_user())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["target_user"] = self.get_target_user()
        return context


class ManagedItemListView(StaffRequiredMixin, ListView):
    model = ToDoItem
    template_name = "manage/todoitem_list.html"
    context_object_name = "items"

    def get_todo_list(self):
        return get_object_or_404(ToDoList, pk=self.kwargs["list_pk"])

    def get_queryset(self):
        return ToDoItem.objects.filter(todo_list=self.get_todo_list())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["todo_list"] = self.get_todo_list()
        return context


class ManagedListDeleteView(StaffRequiredMixin, DeleteView):
    model = ToDoList
    template_name = "manage/todolist_confirm_delete.html"
    context_object_name = "todo_list"

    def get_success_url(self):
        return reverse_lazy("manage:user-lists", kwargs={"pk": self.object.owner_id})


class ManagedItemUpdateView(StaffRequiredMixin, View):
    template_name = "manage/todoitem_form.html"

    def get_item(self, list_pk, item_pk):
        return get_object_or_404(ToDoItem, pk=item_pk, todo_list_id=list_pk)

    def get(self, request, list_pk, item_pk):
        item = self.get_item(list_pk, item_pk)
        form = TodoItemEditForm(instance=item)
        return render(request, self.template_name, {"form": form, "object": item,
                                                    "todo_list": item.todo_list})

    def post(self, request, list_pk, item_pk):
        item = self.get_item(list_pk, item_pk)
        form = TodoItemEditForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, "Item updated.")
            return redirect("manage:user-list-items", list_pk=item.todo_list_id)
        return render(request, self.template_name, {"form": form, "object": item,
                                                    "todo_list": item.todo_list})


class ManagedItemDeleteView(StaffRequiredMixin, DeleteView):
    model = ToDoItem
    template_name = "manage/todoitem_confirm_delete.html"
    context_object_name = "item"

    def get_success_url(self):
        return reverse_lazy("manage:user-list-items",
                            kwargs={"list_pk": self.object.todo_list_id})


# ---------------------------------------------------------------------------
# SQL INJECTION DEMO — local learning only, never deploy this
# ---------------------------------------------------------------------------

def sqli_vulnerable(request):
    """Vulnerable: builds the SQL query via Python string interpolation."""
    username = request.GET.get("username", "")
    # The username value is dropped directly into the query string —
    # an attacker controls what the database engine actually executes.
    query = f"SELECT id, username, email, is_staff FROM auth_user WHERE username = '{username}'"
    rows = []
    error = None
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
    except Exception as exc:
        error = str(exc)
    return render(request, "manage/sqli_demo.html", {
        "mode": "vulnerable",
        "username": username,
        "query": query,
        "rows": rows,
        "error": error,
    })


def sqli_safe(request):
    """Safe: passes the value as a parameter — the DB driver escapes it."""
    username = request.GET.get("username", "")
    query = "SELECT id, username, email, is_staff FROM auth_user WHERE username = %s"
    rows = []
    error = None
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, [username])
            rows = cursor.fetchall()
    except Exception as exc:
        error = str(exc)
    return render(request, "manage/sqli_demo.html", {
        "mode": "safe",
        "username": username,
        "query": query,
        "rows": rows,
        "error": error,
    })
