# Safe additive migration: backfill existing AI assessments as legacy9, new rows use five_v1.
from django.db import migrations, models

FIVE = [
    ('work_conditions_pressure', 'شرایط و فشار کاری'),
    ('management_environment', 'کیفیت مدیریت و محیط کاری'),
    ('growth_development', 'رشد و توسعه فردی و حرفه‌ای'),
    ('compensation_appreciation', 'جبران خدمات و فرهنگ قدردانی'),
    ('stability_security', 'ثبات و امنیت شغلی'),
]
LEGACY = [
    ('work_life_balance','تعادل کار و زندگی'),
    ('workload','سبک‌بودن فشار کاری'),
    ('compensation_fairness','تناسب حقوق با حجم کار'),
    ('market_pay_competitiveness','رقابت‌پذیری حقوق در بازار'),
    ('micromanagement','نبود مدیریت ذره‌بینی'),
    ('decision_autonomy','استقلال تصمیم‌گیری'),
    ('direct_management','کیفیت مدیر مستقیم'),
    ('career_growth','رشد و یادگیری'),
    ('job_stability','امنیت شغلی'),
]
VERSIONS = [('legacy9', '۹ معیار تاریخی - فقط سوابق'), ('five_v1', '۵ معیار جدید')]

class Migration(migrations.Migration):
    dependencies = [('assessments', '0002_aihumanreviewevent')]
    operations = [
        migrations.AddField(
            model_name='aiassessment', name='criteria_version',
            field=models.CharField(max_length=16, choices=VERSIONS, default='legacy9'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='aiassessment', name='criteria_version',
            field=models.CharField(max_length=16, choices=VERSIONS, default='five_v1'),
        ),
        migrations.AlterField(model_name='aidimension', name='key',
            field=models.CharField(max_length=60, choices=FIVE + LEGACY)),
        migrations.AlterField(model_name='ratingsnapshot', name='dimension',
            field=models.CharField(max_length=60, choices=FIVE + LEGACY)),
    ]
