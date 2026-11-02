"""Optional independent Claude second opinion; no changes to existing ratings."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('assessments', '0005_semantic_score_override_v17'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ClaudeValidationRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(max_length=16, default='running', choices=[
                    ('running','درحال بررسی'),('completed','تکمیل‌شده'),('failed','ناموفق')])),
                ('model_id', models.CharField(max_length=100)),
                ('prompt_version', models.CharField(max_length=32, default='independent_five_v111')),
                ('source_sha256', models.CharField(max_length=64)),
                ('original_scores', models.JSONField(default=dict)),
                ('claude_results', models.JSONField(default=dict)),
                ('comparison', models.JSONField(default=dict)),
                ('input_tokens', models.PositiveIntegerField(default=0)),
                ('output_tokens', models.PositiveIntegerField(default=0)),
                ('estimated_cost_usd', models.DecimalField(max_digits=9,decimal_places=6,default=0)),
                ('error_type', models.CharField(max_length=60,blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('finished_at', models.DateTimeField(null=True,blank=True)),
                ('assessment', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name='claude_validation_runs',to='assessments.aiassessment')),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name='jobiew_claude_validations',to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-created_at', '-id'),
                'indexes': [models.Index(fields=['assessment','-id'], name='wi_claude_assessment_idx')],
            },
        )
    ]
