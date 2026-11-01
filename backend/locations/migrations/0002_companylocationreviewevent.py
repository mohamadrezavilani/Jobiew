# Generated for Django 6.1; additive review log only.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('locations', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='CompanyLocationReviewEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('decision', models.CharField(max_length=20, choices=[
                    ('verified', 'مکان تأیید شد'), ('rejected', 'مکان رد شد'),
                    ('unverified', 'تأیید مکان لغو شد')])),
                ('address', models.TextField(blank=True)),
                ('latitude', models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)),
                ('longitude', models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)),
                ('evidence_url', models.URLField(blank=True, max_length=1500)),
                ('rationale', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('company', models.ForeignKey(to='companies.company', on_delete=django.db.models.deletion.PROTECT,
                                              related_name='location_review_events')),
                ('reviewer', models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT,
                                               related_name='location_review_events')),
            ],
            options={'ordering': ['-created_at', '-pk']},
        ),
    ]
