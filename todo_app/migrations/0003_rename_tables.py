from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('todo_app', '0002_account_person'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterModelTable(name='ToDoList', table='todolist'),
                migrations.AlterModelTable(name='ToDoItem', table='todoitem'),
                migrations.AlterModelTable(name='Account', table='account'),
                migrations.AlterModelTable(name='Person', table='person'),
            ],
            database_operations=[
                migrations.RunSQL('ALTER TABLE "todo_app_todolist" RENAME TO "todolist"'),
                migrations.RunSQL('ALTER TABLE "todo_app_todoitem" RENAME TO "todoitem"'),
                migrations.RunSQL('ALTER TABLE "todo_app_account" RENAME TO "account"'),
                migrations.RunSQL('ALTER TABLE "todo_app_person" RENAME TO "person"'),
            ],
        ),
    ]
