"""Add separate immutable research revision history; no data rewrites."""
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('assessments','0004_positive_workload_label_v14')]
    operations = [
        migrations.CreateModel(
            name='SemanticScoreOverride',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('batch_id', models.CharField(max_length=120)),
                ('action', models.CharField(choices=[('revise','اصلاح نمره'),('abstain','حذف نمره فاقد شاهد')],max_length=12)),
                ('baseline_score', models.PositiveSmallIntegerField(blank=True,null=True)),
                ('proposed_score', models.PositiveSmallIntegerField(blank=True,null=True)),
                ('source_content_sha256', models.CharField(max_length=64)),
                ('source_row_sha256', models.CharField(max_length=64)),
                ('evidence_excerpt', models.TextField(blank=True)),
                ('rationale', models.TextField()),
                ('review_method', models.CharField(default='offline_AI_recommendation',max_length=100)),
                ('status',models.CharField(choices=[('proposed','پیشنهاد AI، غیرفعال'),('active_provisional','فعال صرفاً در محاسبات داخلی')],default='proposed',max_length=20)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('dimension',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='semantic_overrides',to='assessments.aidimension')),
            ],
            options={'indexes':[models.Index(fields=['dimension','-id'],name='wi_sem_override_dim_pk')]},
        ),
        migrations.AddConstraint(model_name='semanticscoreoverride',constraint=models.UniqueConstraint(fields=('dimension','batch_id'),name='wi_sem_override_dim_batch')),
        migrations.AddConstraint(model_name='semanticscoreoverride',constraint=models.CheckConstraint(condition=(models.Q(baseline_score__isnull=True) | (models.Q(baseline_score__gte=1) & models.Q(baseline_score__lte=10))),name='wi_sem_override_base_1_10')),
        migrations.AddConstraint(model_name='semanticscoreoverride',constraint=models.CheckConstraint(condition=(models.Q(proposed_score__isnull=True) | (models.Q(proposed_score__gte=1) & models.Q(proposed_score__lte=10))),name='wi_sem_override_new_1_10')),
    ]
