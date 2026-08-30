"""Seed the paper catalogue with the papers NCAA runs today.

Only a starting point. Once these rows exist they are the configuration:
adding a paper, renaming one -- the AME placeholders in particular -- or
retiring one happens in the admin, and this migration does not touch a row it
did not create.
"""
from django.db import migrations

# Kept as literals rather than imported from exams.paper_types: a migration has
# to describe the state of the world when it ran, and stays correct even after
# the module's defaults are edited.
SEED = {
    'cabin_crew': [
        ('b737', 'B737', ['B737', 'B-737', 'B 737', 'Boeing 737', '737']),
        ('general', 'General Paper', ['General Paper', 'General Examination']),
    ],
    'pilot': [
        ('general', 'General Paper', ['General Paper', 'General Examination']),
    ],
    'flight_dispatch': [
        ('paper_1', 'Paper 1', ['Paper 1', 'Paper I', 'Paper One', 'Paper-1']),
        ('paper_2', 'Paper 2', ['Paper 2', 'Paper II', 'Paper Two', 'Paper-2']),
    ],
    'ame': [
        ('general', 'General Paper', ['General Paper', 'General Examination']),
        # Placeholders. NCAA has not confirmed the official titles; renaming
        # them in the admin is all that is required once it does.
        ('ame_paper_2', 'AME Paper 2', ['AME Paper 2', 'Paper 2', 'Paper II']),
        ('ame_paper_3', 'AME Paper 3', ['AME Paper 3', 'Paper 3', 'Paper III']),
    ],
}


def seed(apps, schema_editor):
    PaperType = apps.get_model('exams', 'PaperType')
    for exam_category, papers in SEED.items():
        for order, (code, name, terms) in enumerate(papers):
            PaperType.objects.get_or_create(
                exam_category=exam_category,
                code=code,
                defaults={
                    'name': name,
                    'detection_terms': '\n'.join(terms),
                    'display_order': order,
                },
            )


def unseed(apps, schema_editor):
    PaperType = apps.get_model('exams', 'PaperType')
    for exam_category, papers in SEED.items():
        PaperType.objects.filter(
            exam_category=exam_category, code__in=[code for code, _, _ in papers]
        ).delete()


class Migration(migrations.Migration):

    dependencies = [('exams', '0003_paper_type_catalogue')]

    operations = [migrations.RunPython(seed, unseed)]
