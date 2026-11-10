"""Opt-in private second opinion for current work/interview six-axis analyses."""
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
            name='ClaudeSixCheck',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                            serialize=False, verbose_name='ID')),
                ('status', models.CharField(max_length=16, default='running',
                    choices=[('running','در انتظار نتیجه'),('completed','تکمیل‌شده'),
                             ('needs_review','نوع تجربه نیازمند بررسی'),('failed','ناموفق')])),
                ('model_id', models.CharField(max_length=100)),
                ('prompt_version', models.CharField(max_length=50,
                    default='claude_six_second_opinion_v233')),
                ('source_sha256', models.CharField(max_length=64)),
                ('score_sha256', models.CharField(max_length=64)),
                ('original_scores', models.JSONField(default=dict)),
                ('claude_results', models.JSONField(default=dict)),
                ('comparison', models.JSONField(default=dict)),
                ('input_tokens', models.PositiveIntegerField(default=0)),
                ('output_tokens', models.PositiveIntegerField(default=0)),
                ('error_code', models.CharField(max_length=70, blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('finished_at', models.DateTimeField(null=True, blank=True)),
                ('analysis', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name='claude_six_checks', to='criteria_v2.criteriaanalysis')),
                ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name='claude_six_checks', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name='claudesixcheck',
            constraint=models.UniqueConstraint(
                fields=('analysis',), name='wi_one_claude_six_per_analysis'),
        ),
    ]
