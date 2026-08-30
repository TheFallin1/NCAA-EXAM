"""Split the examination selection into category and paper.

`exam_type` is renamed to `exam_category` -- it always held the category -- and
a `paper_type` column joins it. The two are stored apart so scheduling,
reporting, searching and filtering can each work on either without picking a
combined string back apart.

`PaperType` carries the papers themselves, which makes them configuration: the
placeholder AME names can be replaced from the admin once NCAA confirms them,
with no code or schema change.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0002_exampaper_numbersequence_examschedule_application_and_more'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='examschedule',
            name='exams_exams_exam_da_3d9242_idx',
        ),
        migrations.RenameField(
            model_name='examschedule',
            old_name='exam_type',
            new_name='exam_category',
        ),
        migrations.AlterField(
            model_name='examschedule',
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
            model_name='examschedule',
            name='paper_type',
            field=models.CharField(blank=True, db_index=True, max_length=32),
        ),
        migrations.AddIndex(
            model_name='examschedule',
            index=models.Index(
                fields=['exam_date', 'exam_category'],
                name='exams_exams_exam_da_abcedb_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='examschedule',
            index=models.Index(
                fields=['exam_category', 'paper_type'],
                name='exams_exams_exam_ca_942ba7_idx',
            ),
        ),
        migrations.CreateModel(
            name='PaperType',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'exam_category',
                    models.CharField(
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
                (
                    'code',
                    models.SlugField(
                        help_text=(
                            'Stable identifier stored on examination records. '
                            'Do not change it once records exist -- change the '
                            'name instead.'
                        ),
                        max_length=32,
                    ),
                ),
                (
                    'name',
                    models.CharField(
                        help_text=(
                            'The label officers see, e.g. "B737" or '
                            '"General Paper".'
                        ),
                        max_length=100,
                    ),
                ),
                (
                    'detection_terms',
                    models.TextField(
                        blank=True,
                        help_text=(
                            'One phrase per line that names this paper in an '
                            'application letter, e.g. "B737". A phrase only '
                            'counts where it appears in an examination '
                            'context, so the same words in a letterhead or a '
                            'training history are ignored.'
                        ),
                    ),
                ),
                (
                    'display_order',
                    models.PositiveSmallIntegerField(
                        default=0,
                        help_text='Lower numbers appear first in the dropdown.',
                    ),
                ),
                (
                    'is_active',
                    models.BooleanField(
                        default=True,
                        help_text=(
                            'Clear this to retire a paper. Records that '
                            'already use it keep their label; the paper simply '
                            'stops being offered.'
                        ),
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Paper Type',
                'verbose_name_plural': 'Paper Types',
                'ordering': ['exam_category', 'display_order', 'name'],
            },
        ),
        migrations.AddConstraint(
            model_name='papertype',
            constraint=models.UniqueConstraint(
                fields=('exam_category', 'code'),
                name='unique_paper_code_per_category',
            ),
        ),
    ]
