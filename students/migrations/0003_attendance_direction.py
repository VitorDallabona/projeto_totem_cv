# Generated manually to add direction field to Attendance model

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('students', '0002_classroom_enrolled_students'),
    ]

    operations = [
        # Adicionar campo 'direction' à tabela Attendance
        migrations.AddField(
            model_name='attendance',
            name='direction',
            field=models.CharField(
                choices=[
                    ('ENTRADA', 'Entrada (Esquerda para Direita)'),
                    ('SAÍDA', 'Saída (Direita para Esquerda)')
                ],
                default='ENTRADA',
                max_length=10
            ),
        ),
        # Adicionar related_name se a FK não tiver ainda
        migrations.AlterField(
            model_name='attendance',
            name='student',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='attendances',
                to='students.student'
            ),
        ),
        migrations.AlterField(
            model_name='attendance',
            name='classroom',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='attendance_records',
                to='students.classroom'
            ),
        ),
    ]
