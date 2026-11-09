"""Only new schema. Existing experiences and ratings are never overwritten."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

KIND_CHOICES = [('work', 'شرایط کاری'), ('interview', 'شرایط مصاحبه')]
VERSION_CHOICES = [('work6_v2', 'شش معیار شرایط کاری'), ('interview6_v2', 'شش معیار شرایط مصاحبه')]
AXIS_CHOICES = [
    ('work_compensation_fairness','حقوق، مزایا و عدالت پرداخت'),
    ('work_life_flexibility','تعادل کار و زندگی و انعطاف‌پذیری'),
    ('work_growth_career','رشد و آینده شغلی'),
    ('work_management_culture','مدیریت و فرهنگ'),
    ('work_stability_security','ثبات و امنیت شغلی'),
    ('work_challenge_autonomy','چالش‌برانگیز بودن کار و اختیار عمل'),
    ('interview_professional_respect','احترام و رفتار حرفه‌ای'),
    ('interview_information_clarity','شفافیت اطلاعات'),
    ('interview_quality_fairness','کیفیت و عدالت مصاحبه'),
    ('interview_time_management','نظم و مدیریت زمان'),
    ('interview_communication','ارتباطات و اطلاع‌رسانی'),
    ('interview_feedback_outcome','نتیجه‌دهی و بازخورد'),
]


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ('experiences', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='CriteriaReviewEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_kind', models.CharField(max_length=20, choices=KIND_CHOICES)),
                ('criteria_version', models.CharField(max_length=16, choices=VERSION_CHOICES)),
                ('source_content_sha256', models.CharField(max_length=64)),
                ('decision', models.CharField(max_length=20, choices=[('confirmed','دسته‌بندی تأیید شد؛ آمادهٔ مرحلهٔ ارزیابی'),('needs_revision','دسته‌بندی نیازمند اصلاح است'),('excluded','این روایت نباید برای معیارها استفاده شود')])),
                ('suggested_kind', models.CharField(max_length=20, blank=True, choices=KIND_CHOICES)),
                ('note', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('experience', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='dual_criteria_review_events',to='experiences.publicexperience')),
                ('reviewer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ('-created_at', '-pk'), 'indexes':[models.Index(fields=['experience','-created_at'],name='wi_dual_review_exp_ts')]},
        ),
        migrations.CreateModel(
            name='CriteriaAnalysis',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('criteria_version',models.CharField(max_length=16,choices=VERSION_CHOICES)),
                ('source_content_sha256',models.CharField(max_length=64)),
                ('model_name',models.CharField(max_length=120)),
                ('prompt_version',models.CharField(max_length=120)),
                ('run_id',models.CharField(max_length=120,unique=True)),
                ('raw_payload',models.JSONField(default=dict)),
                ('review_status',models.CharField(max_length=24,default='unreviewed')),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('experience',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='dual_criteria_analyses',to='experiences.publicexperience')),
            ],
        ),
        migrations.CreateModel(
            name='CriteriaAxisScore',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('key',models.CharField(max_length=60,choices=AXIS_CHOICES)),
                ('score',models.PositiveSmallIntegerField(null=True,blank=True)),
                ('confidence',models.PositiveSmallIntegerField(default=0)),
                ('evidence',models.JSONField(default=list)),
                ('explanation',models.TextField(blank=True)),
                ('semantic_status',models.CharField(max_length=24,default='unreviewed')),
                ('analysis',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='axis_scores',to='criteria_v2.criteriaanalysis')),
            ],
        ),
        migrations.AddConstraint(model_name='criteriaaxisscore',constraint=models.UniqueConstraint(fields=('analysis','key'),name='wi_dual_score_one_key_per_run')),
        migrations.AddConstraint(model_name='criteriaaxisscore',constraint=models.CheckConstraint(condition=models.Q(score__isnull=True) | (models.Q(score__gte=1) & models.Q(score__lte=10)),name='wi_dual_score_range_1_10')),
        migrations.AddConstraint(model_name='criteriaaxisscore',constraint=models.CheckConstraint(condition=models.Q(confidence__gte=0) & models.Q(confidence__lte=100),name='wi_dual_confidence_range_100')),
    ]
