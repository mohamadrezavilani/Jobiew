"""Independent immutable audit for each human six-axis score adjudication."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('criteria_v2', '0002_allow_empty_json_payloads'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='CriteriaScoreReviewEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_content_sha256', models.CharField(max_length=64)),
                ('decisions', models.JSONField(default=dict)),
                ('note', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('analysis', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                   related_name='human_score_review_events', to='criteria_v2.criteriaanalysis')),
                ('reviewer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                   to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ('-created_at', '-pk')},
        ),
        migrations.AddConstraint(
            model_name='criteriascorereviewevent',
            constraint=models.UniqueConstraint(fields=('analysis',), name='wi_dual_one_human_review'),
        ),
    ]
