# Generated manually for SlipRecord tracking.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('exams', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SlipRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('last_viewed_at', models.DateTimeField(blank=True, null=True)),
                ('pdf_generated_at', models.DateTimeField(blank=True, null=True)),
                ('preview_count', models.PositiveIntegerField(default=0)),
                ('pdf_download_count', models.PositiveIntegerField(default=0)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_slip_records', to=settings.AUTH_USER_MODEL)),
                ('exam', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='slip_record', to='exams.examschedule')),
            ],
            options={
                'verbose_name': 'Slip Record',
                'verbose_name_plural': 'Slip Records',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['-created_at'], name='slips_slipr_created_8a9b15_idx'),
                    models.Index(fields=['pdf_generated_at'], name='slips_slipr_pdf_gen_7a6c42_idx'),
                ],
            },
        ),
    ]
