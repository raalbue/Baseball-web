from django.contrib import admin
from .models import ToDoList, ToDoItem


class ToDoItemInline(admin.TabularInline):
    model = ToDoItem
    extra = 0
    fields = ["title", "due_date"]
    readonly_fields = ["created_date"]


@admin.register(ToDoList)
class ToDoListAdmin(admin.ModelAdmin):
    list_display = ["title", "owner", "item_count"]
    list_filter = ["owner"]
    search_fields = ["title", "owner__username"]
    inlines = [ToDoItemInline]

    @admin.display(description="Items")
    def item_count(self, obj):
        return obj.todoitem_set.count()


@admin.register(ToDoItem)
class ToDoItemAdmin(admin.ModelAdmin):
    list_display = ["title", "todo_list", "due_date", "created_date"]
    list_filter = ["todo_list__owner", "due_date"]
    search_fields = ["title", "todo_list__title", "todo_list__owner__username"]
    readonly_fields = ["created_date"]
