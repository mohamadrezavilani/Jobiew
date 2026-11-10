"""Private, immutable human-review receipt; no changes to historical ratings."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('criteria_v2', '0003_score_review_event_v209'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='CheckpointApprovalReceipt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_content_sha256', models.CharField(max_length=64)),
                ('scores_sha256', models.CharField(max_length=64)),
                ('batch_token', models.CharField(max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('analysis', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                    related_name='checkpoint_approval_receipt', to='criteria_v2.criteriaanalysis')),
                ('reviewer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    to=settings.AUTH_USER_MODEL)),
                ('score_review_event', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                    to='criteria_v2.criteriascorereviewevent')),
            ],
        ),
    ]