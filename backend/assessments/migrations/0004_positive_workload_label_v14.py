"""v14: change display label/choices only; NO data migration or score inversion."""
from django.db import migrations, models

FIVE = [
    ('work_conditions_pressure', 'تعادل کار و زندگی و تناسب حجم کار'),
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

class Migration(migrations.Migration):
    dependencies = [('assessments', '0003_five_criteria_version')]
    operations = [
        migrations.AlterField('aidimension', 'key',
            models.CharField(max_length=60, choices=FIVE + LEGACY)),
        migrations.AlterField('ratingsnapshot', 'dimension',
            models.CharField(max_length=60, choices=FIVE + LEGACY)),
    ]
