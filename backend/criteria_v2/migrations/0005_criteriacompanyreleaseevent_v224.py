"""Append-only per-company release gate; no existing score is automatically public."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('criteria_v2', '0004_checkpointapprovalreceipt_v222'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='CriteriaCompanyReleaseEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('decision', models.CharField(max_length=16,
                    choices=[('published', 'انتشار امتیازهای تأییدشده'),
                             ('held', 'توقف انتشار امتیازهای شرکت')])),
                ('approved_runs', models.JSONField(default=dict)),
                ('note', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name='dual_score_release_events', to='companies.company')),
                ('reviewer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ('-created_at', '-pk')},
        ),
    ]
