"""Allow empty draft JSON in the new architecture-only criteria tables.

No historical rows or existing scores are changed; blank=True only affects
model/form validation. Defaults and database JSON types stay unchanged.
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('criteria_v2', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='criteriaanalysis',
            name='raw_payload',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name='criteriaaxisscore',
            name='evidence',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
