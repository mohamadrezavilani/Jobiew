"""Optional independent Claude six-axis comparison; no backfill or public scores."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('criteria_v2', '0005_criteriacompanyreleaseevent_v224'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='CriteriaClaudeComparison',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_content_sha256', models.CharField(max_length=64)),
                ('story_sha256', models.CharField(max_length=64)),
                ('model_id', models.CharField(max_length=100)),
                ('status', models.CharField(max_length=24, default='running', choices=[
                    ('running', 'درحال اجرا'), ('completed', 'تکمیل‌شده'),
                    ('needs_review', 'نیازمند بررسی نوع تجربه'),
                    ('failed', 'ناموفق')])),
                ('detected_kind', models.CharField(max_length=20, blank=True)),
                ('claude_axes', models.JSONField(default=dict, blank=True)),
                ('comparison', models.JSONField(default=dict, blank=True)),
                ('input_tokens', models.PositiveIntegerField(default=0)),
                ('output_tokens', models.PositiveIntegerField(default=0)),
                ('error_type', models.CharField(max_length=64, blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(null=True, blank=True)),
                ('analysis', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                    related_name='claude_six_comparison', to='criteria_v2.criteriaanalysis')),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ('-created_at', '-pk')},
        ),
    ]
