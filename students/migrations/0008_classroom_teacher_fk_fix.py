from django.db import migrations


def add_teacher_id_column(apps, schema_editor):
    table_name = 'students_classroom'

    with schema_editor.connection.cursor() as cursor:
        columns = [column.name for column in schema_editor.connection.introspection.get_table_description(cursor, table_name)]

        if 'teacher_id' not in columns:
            cursor.execute(
                'ALTER TABLE students_classroom ADD COLUMN teacher_id integer REFERENCES auth_user(id) DEFERRABLE INITIALLY DEFERRED'
            )


class Migration(migrations.Migration):

    dependencies = [
        ('students', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_teacher_id_column, migrations.RunPython.noop),
    ]