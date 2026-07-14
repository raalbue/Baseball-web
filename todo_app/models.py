from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


def one_week_hence():
    return timezone.now() + timezone.timedelta(days=7)


class ToDoList(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="todo_lists")
    title = models.CharField(max_length=100)

    def get_absolute_url(self):
        return reverse("list", args=[self.id])

    def __str__(self):
        return self.title

    class Meta:
        db_table = "todolist"
        constraints = [
            models.UniqueConstraint(fields=["owner", "title"], name="unique_list_title_per_owner")
        ]


class ToDoItem(models.Model):
    title = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    due_date = models.DateTimeField(default=one_week_hence)
    todo_list = models.ForeignKey(ToDoList, on_delete=models.CASCADE)

    def get_absolute_url(self):
        return reverse("item-update", args=[str(self.todo_list.id), str(self.id)])

    def __str__(self):
        return f"{self.title}: due {self.due_date}"

    class Meta:
        ordering = ["due_date"]
        db_table = "todoitem"
