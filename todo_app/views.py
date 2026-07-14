from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView

from .models import ToDoList, ToDoItem


class ListListView(LoginRequiredMixin, ListView):
    model = ToDoList
    template_name = "todo_app/index.html"

    def get_queryset(self):
        return ToDoList.objects.filter(owner=self.request.user)


class ItemListView(LoginRequiredMixin, ListView):
    model = ToDoItem
    template_name = "todo_app/todo_list.html"

    def get_queryset(self):
        self.todo_list = get_object_or_404(ToDoList, id=self.kwargs["list_id"], owner=self.request.user)
        return ToDoItem.objects.filter(todo_list=self.todo_list)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["todo_list"] = self.todo_list
        return context


class ListCreate(LoginRequiredMixin, CreateView):
    model = ToDoList
    fields = ["title"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Add a new list"
        return context

    def form_valid(self, form):
        form.instance.owner = self.request.user
        return super().form_valid(form)


class ItemCreate(LoginRequiredMixin, CreateView):
    model = ToDoItem
    fields = ["title", "description", "due_date"]

    def get_todo_list(self):
        return get_object_or_404(ToDoList, id=self.kwargs["list_id"], owner=self.request.user)

    def get_initial(self):
        initial_data = super().get_initial()
        initial_data["todo_list"] = self.get_todo_list()
        return initial_data

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["todo_list"] = self.get_todo_list()
        context["title"] = "Create a new item"
        return context

    def form_valid(self, form):
        form.instance.todo_list = self.get_todo_list()
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("list", args=[self.object.todo_list_id])


class ItemUpdate(LoginRequiredMixin, UpdateView):
    model = ToDoItem
    fields = ["title", "description", "due_date"]

    def get_queryset(self):
        return ToDoItem.objects.filter(todo_list__owner=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["todo_list"] = self.object.todo_list
        context["title"] = "Edit item"
        return context

    def get_success_url(self):
        return reverse("list", args=[self.object.todo_list_id])


class ListDelete(LoginRequiredMixin, DeleteView):
    model = ToDoList
    success_url = reverse_lazy("index")

    def get_queryset(self):
        return ToDoList.objects.filter(owner=self.request.user)


class ItemDelete(LoginRequiredMixin, DeleteView):
    model = ToDoItem

    def get_queryset(self):
        return ToDoItem.objects.filter(todo_list__owner=self.request.user)

    def get_success_url(self):
        return reverse_lazy("list", args=[self.kwargs["list_id"]])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["todo_list"] = self.object.todo_list
        return context
