# Jobiew — پذیرش و ورود خصوصی checkpoint نهایی v65 (شناسه‌های ۱ تا ۸٬۱۳۹)

## فایل و نتیجهٔ QA آفلاین

- فایل ورودی: `jobiew_gpt6_private_checkpoint_001_8139.zip`
- SHA256 دقیق فایل بارگذاری‌شده: `9e50f9d7b8e85a1884575f2cb72c7c72b2a8873209e7f85fabf2262349aa0e2e`
- ۷۷۹ عضو ZIP، ۳۰٬۳۹۱٬۱۴۷ بایت محتوای بازشده؛ CRC و تمام ۷۷۸ هش داخلی بررسی شده‌اند.
- ۸٬۱۳۹ شناسه در ledger؛ ۵٬۸۵۹ پیش‌نویس ۶‌محوری (۴٬۲۸۱ کاری و ۱٬۵۷۸ مصاحبه).
- ۵٬۶۹۷ پیش‌نویس دارای حداقل یک نمرهٔ عددی و ۱۶۲ پیش‌نویس تماماً `null` هستند.
- مجموع محورهای عددی ۱۹٬۴۸۰ و محورهای `null` برابر ۱۵٬۶۷۴ است.
- ۱٬۹۹۸ مورد deferred و ۲۸۲ مورد excluded هستند؛ این‌ها پیش‌نویس امتیازدهی‌شده نیستند.
- از میان ۵٬۸۵۹ پیش‌نویس، ۸ مورد duplicate دقیق علامت‌گذاری شده‌اند؛ importer آن‌ها را به‌عنوان تجربهٔ مستقل وارد نمی‌کند. سقف تعداد ردیف‌های مستقل قابل ورود ۵٬۸۵۱ است؛ تعداد واقعی insert پس از تطبیق با PostgreSQL مشخص می‌شود.
- SHA منبع اعلام‌شده در checkpoint: `164a31e46514ee958be67a6cf2f88f8ec9555baf80f45e7e0101592c34c482d0`. ZIP منبع در این تحویل همراه checkpoint نیست؛ importer تولیدی تطبیق مستقل شناسهٔ شرکت، نوع، هش محتوای منبع، هش متن بازسازی‌شده و شاهد لفظی را با ردیف‌های موجود PostgreSQL انجام می‌دهد. گزارش باید `source_db_identity_and_evidence=PREFLIGHT_PASS` را نشان دهد.

این checkpoint **خصوصی و تأییدنشده** است: `source_rights=NOT_ESTABLISHED`، انتساب شرکت `UNVERIFIED`، صحت معنایی مستقل اثبات‌نشده و انتشار `DISABLED`. ورود خصوصی نه تأیید انسانی است و نه انتشار.

## سازگاری parser

نسخهٔ v65 دارای ۷۷۹ عضو کوچک و هش‌شده است و مقدار `quality_audit.validation_scope` آن `custom_independent_structural_schema_and_verbatim_evidence` است. validator اکنون این scope مشخص را در کنار scope قدیمی می‌پذیرد و سقف تعداد اعضای ZIP را از ۵۰۰ به ۱٬۰۰۰ افزایش می‌دهد؛ محدودیت حجم ZIP و تمام کنترل‌های hash، schema، ledger و شش محور پابرجا هستند. فایل‌های `.py` داخل ZIP فقط دادهٔ آرشیوی‌اند و **هرگز اجرا نمی‌شوند**.

## استقرار parser روی Ubuntu

این تغییر فقط validator، تست و مستندات را عوض می‌کند و migration دیتابیس ندارد.

ابتدا وضعیت checkout را بررسی کنید؛ اگر تغییر محلی وجود دارد، آن را حفظ و بررسی کنید:

```bash
sudo -u jobiew git -C /opt/jobiew status --short
sudo -u jobiew git -C /opt/jobiew branch --show-current
sudo -u jobiew git -C /opt/jobiew rev-parse HEAD
sudo systemctl is-active jobiew-web
```

پس از merge شدن این اصلاح در `main` و اطمینان از clean بودن checkout:

```bash
sudo -u jobiew git -C /opt/jobiew fetch origin main
sudo -u jobiew git -C /opt/jobiew pull --ff-only origin main
sudo -u jobiew bash -c 'set -a; source /etc/jobiew/jobiew.env; set +a; cd /opt/jobiew/backend; /opt/jobiew/.venv/bin/python manage.py check'
sudo -u jobiew bash -c 'set -a; source /etc/jobiew/jobiew.env; set +a; cd /opt/jobiew/backend; /opt/jobiew/.venv/bin/python manage.py makemigrations --check --dry-run'
sudo systemctl restart jobiew-web
sudo systemctl is-active jobiew-web
```

## انتقال محرمانهٔ ZIP

ZIP را از رایانهٔ امن با SCP به سرور منتقل کنید؛ هرگز آن را در Git، GitHub، static، media یا artifact عمومی قرار ندهید:

```bash
scp jobiew_gpt6_private_checkpoint_001_8139.zip root@YOUR_SERVER_IP:/root/
sudo install -d -m 700 -o jobiew -g jobiew /var/lib/jobiew/checkpoints
sudo install -m 600 -o jobiew -g jobiew /root/jobiew_gpt6_private_checkpoint_001_8139.zip /var/lib/jobiew/checkpoints/jobiew_gpt6_private_checkpoint_001_8139.zip
sudo sha256sum /var/lib/jobiew/checkpoints/jobiew_gpt6_private_checkpoint_001_8139.zip
```

خروجی SHA باید دقیقاً برابر مقدار بالای این سند باشد.

## Gateهای لازم برای ورود خصوصی در Production

فرمان `stage_checkpoint_private_prod_v224` فقط وقتی اجرا می‌شود که همهٔ موارد زیر برقرار باشند:

- `DJANGO_DEBUG=0`
- دیتابیس Django دقیقاً PostgreSQL با نام `jobiew` و host محلی باشد.
- `JOBIEW_CHECKPOINT_PUBLIC_HOST=jobiew.ir` و دامنه در `DJANGO_ALLOWED_HOSTS` باشد.
- `JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED=1`
- `JOBIEW_COMPANY_RELEASE_ONLY_ENABLED=1`
- `JOBIEW_CHECKPOINT_STAGING_ENABLED=0`
- دو پرچم انتشار `JOBIEW_DUAL6_PUBLICATION_ENABLED` و `JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED` هر دو `0` باشند؛ یا اگر انتشار قبلاً به‌صورت مستقل فعال شده، هر دو `1` و release-only برابر `1` بماند.
- `JOBIEW_PRIVATE_CHECKPOINT_IMPORT_ENABLED=1` فقط به‌صورت موقت برای همان فرمان systemd-run تنظیم شود، نه در env دائمی سرویس.

اگر guard رد شد، env یا نام DB را برای دور زدن آن تغییر ندهید؛ ابتدا وضعیت واقعی سرویس بررسی شود.

## بکاپ و dry-run بدون نوشتن

ابتدا بکاپ قابل‌بازیابی از دیتابیس تولید بگیرید و فایل را محدود کنید:

```bash
sudo install -d -m 0750 -o root -g jobiew /var/backups/jobiew
sudo -u postgres pg_dump --format=custom --no-owner --no-acl jobiew > /var/backups/jobiew/jobiew_before_checkpoint_8139_$(date +%Y%m%d_%H%M%S).dump
sudo chown root:jobiew /var/backups/jobiew/jobiew_before_checkpoint_8139_*.dump
sudo chmod 0640 /var/backups/jobiew/jobiew_before_checkpoint_8139_*.dump
```

قبل از apply، `pg_restore --list /var/backups/jobiew/نام-فایل.dump` را اجرا و مطمئن شوید dump قابل خواندن است. در محیطی با فضای کافی، restore آزمایشی در دیتابیس جداگانه ترجیح دارد.

فرمان dry-run تمام پیش‌نویس‌های مستقل را ابتدا با PostgreSQL تطبیق می‌دهد و هیچ ردیفی نمی‌نویسد:

```bash
sudo systemd-run --unit="jobiew-checkpoint-v65-dry-$(date +%s)" --wait --pipe --collect \
  --uid=jobiew \
  --property=EnvironmentFile=/etc/jobiew/jobiew.env \
  --property=Environment=JOBIEW_PRIVATE_CHECKPOINT_IMPORT_ENABLED=1 \
  --working-directory=/opt/jobiew/backend \
  /opt/jobiew/.venv/bin/python manage.py stage_checkpoint_private_prod_v224 \
  --checkpoint /var/lib/jobiew/checkpoints/jobiew_gpt6_private_checkpoint_001_8139.zip \
  --expected-db jobiew \
  --expected-checkpoint-sha256 9e50f9d7b8e85a1884575f2cb72c7c72b2a8873209e7f85fabf2262349aa0e2e \
  --expected-source-sha256 164a31e46514ee958be67a6cf2f88f8ec9555baf80f45e7e0101592c34c482d0 \
  --after-id 0 --limit 100 --all-batches --max-total 10000
```

انتظار می‌رود:
- `mode=DRY_RUN_READ_ONLY`
- `checkpoint_reviewed=5859`
- `checked_in_batch=5851`
- `duplicate_source_skipped_in_scan=8`
- `checkpoint_numeric=19480`
- `checkpoint_abstentions=15674`
- `source_db_identity_and_evidence=PREFLIGHT_PASS` (در گزارش‌های فرمان دسته‌ای، نبود این فیلد به‌تنهایی خطا نیست؛ خطاهای preflight باید با exit code غیرصفر متوقف شوند)
- `publication=DISABLED`

اگر خطای source mismatch، quote mismatch، archive validation یا guard دریافت شد، **هیچ apply نکنید** و متن/هش را برای عبور از کنترل تغییر ندهید. تعداد `would_insert` و `previously_staged` به وضعیت واقعی DB وابسته است.

## Apply فقط پس از بررسی dry-run و بکاپ

همان فرمان را با دو پرچم زیر اجرا کنید:

```bash
  --apply --acknowledge-unverified-private-data
```

یعنی کل فرمان dry-run را عیناً تکرار کنید و این دو گزینه را به انتهای آن بیفزایید. `--all-batches` همهٔ تطبیق‌ها را پیش از اولین نوشتن انجام می‌دهد؛ ثبت هر تحلیل در تراکنش مستقل و idempotent است. اگر یک خطای غیرمنتظره پس از تعدادی insert رخ دهد، تعداد commitشده در پیام خطا گزارش می‌شود و اجرای مجدد امن است.

## کنترل پس از ورود

با همان EnvironmentFile و کاربر سرویس، تعداد تحلیل‌ها، شش محور و وضعیت خصوصی را بررسی کنید:

```bash
sudo systemd-run --unit="jobiew-checkpoint-v65-verify-$(date +%s)" --wait --pipe --collect \
  --uid=jobiew \
  --property=EnvironmentFile=/etc/jobiew/jobiew.env \
  --working-directory=/opt/jobiew/backend \
  /opt/jobiew/.venv/bin/python manage.py shell -c "from django.db.models import Count; from criteria_v2.models import CriteriaAnalysis, CriteriaAxisScore; q=CriteriaAnalysis.objects.filter(raw_payload__engine='jobiew_gpt6_private_checkpoint_v218'); print({'analyses':q.count(),'axis_rows':CriteriaAxisScore.objects.filter(analysis__in=q).count(),'bad_axis_count':q.annotate(n=Count('axis_scores')).exclude(n=6).count(),'numeric_axes':CriteriaAxisScore.objects.filter(analysis__in=q,score__isnull=False).count(),'null_axes':CriteriaAxisScore.objects.filter(analysis__in=q,score__isnull=True).count(),'pilot_unverified':q.filter(review_status='pilot_unverified').count(),'publication_disabled':q.filter(raw_payload__publication='DISABLED').count()})"
```

برای ۵٬۸۵۱ تحلیل مستقل تازه، در صورت نبود مورد قبلی از همین engine، انتظار می‌رود ۵٬۸۵۱ تحلیل، ۳۵٬۱۰۶ محور، ۱۹٬۴۸۰ محور عددی و ۱۵٬۶۲۶ محور null ثبت شوند. تعداد واقعی باید با `inserted`، `previously_staged` و وضعیت قبل از اجرا تطبیق داده شود. هیچ تحلیل یا محور به‌طور خودکار approved نمی‌شود؛ تمام محورها `unreviewed` و تمام تحلیل‌ها `pilot_unverified` می‌مانند. پرچم‌های انتشار تغییر نمی‌کنند.
