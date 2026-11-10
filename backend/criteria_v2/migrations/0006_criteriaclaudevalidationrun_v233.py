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
            name='CriteriaClaudeValidationRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('running', 'در حال اجرا'), ('completed', 'تکمیل شده'), ('failed', 'ناموفق')], default='running', max_length=16)),
                ('model_id', models.CharField(max_length=100)),
                ('prompt_version', models.CharField(default='independent_six_v233', max_length=40)),
                ('source_content_sha256', models.CharField(max_length=64)),
                ('source_text_sha256', models.CharField(max_length=64)),
                ('original_scores', models.JSONField(default=dict)),
                ('claude_results', models.JSONField(default=dict)),
                ('comparison', models.JSONField(default=dict)),
                ('input_tokens', models.PositiveIntegerField(default=0)),
                ('output_tokens', models.PositiveIntegerField(default=0)),
                ('error_type', models.CharField(blank=True, max_length=80)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('analysis', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='claude_six_checks', to='criteria_v2.criteriaanalysis')),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='jobiew_claude_six_checks', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ('-created_at', '-pk')},
        ),
        migrations.AddIndex(
            model_name='criteriaclaudevalidationrun',
            index=models.Index(fields=['analysis', '-id'], name='wi_claude6_analysis_idx'),
        ),
    ]
