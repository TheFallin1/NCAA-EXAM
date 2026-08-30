"""Carry the officer's paper selection, and what OCR read, on the application.

The officer's category is renamed to what it always was, and the paper joins it
as its own column. The detected values stay separate from the selected ones so
the two can be compared, shown side by side and audited.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('applications', '0002_applicationdocument_rotation_applied_and_more'),
        ('exams', '0004_seed_paper_types'),
    ]

    operations = [
        migrations.RenameField(
            model_name='application',
            old_name='exam_type',
            new_name='exam_category',
        ),
        migrations.RenameField(
            model_name='application',
            old_name='detected_exam_type',
            new_name='detected_exam_category',
        ),
        migrations.RenameField(
            model_name='application',
            old_name='detected_exam_type_evidence',
            new_name='detected_exam_category_evidence',
        ),
        migrations.RenameField(
            model_name='application',
            old_name='detected_exam_type_ambiguous',
            new_name='detected_exam_category_ambiguous',
        ),
        migrations.AlterField(
            model_name='application',
            name='exam_category',
            field=models.CharField(
                choices=[
                    ('cabin_crew', 'Cabin Crew'),
                    ('pilot', 'Pilot'),
                    ('flight_dispatch', 'Flight Dispatch'),
                    ('ame', 'AME'),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name='application',
            name='paper_type',
            field=models.CharField(blank=True, db_index=True, max_length=32),
        ),
        migrations.AddField(
            model_name='application',
            name='detected_paper_type',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='application',
            name='detected_paper_type_evidence',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='application',
            name='detected_paper_type_ambiguous',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='application',
            name='processing_status',
            field=models.CharField(
                choices=[
                    ('draft', 'Draft'),
                    ('queued', 'Queued for OCR'),
                    ('processing', 'OCR in progress'),
                    ('failed', 'OCR failed'),
                    ('mismatch', 'Examination category mismatch'),
                    ('paper_mismatch', 'Paper type mismatch'),
                    ('review', 'Awaiting verification'),
                    ('confirmed', 'Confirmed'),
                    ('scheduled', 'Scheduled'),
                ],
                db_index=True,
                default='draft',
                max_length=16,
            ),
        ),
    ]
