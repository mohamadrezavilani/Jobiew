# Jobiew v2.0.24 — ورود خصوصی checkpoint و انتشار انتخابی شرکت

## وضعیت و مرزهای مسئولیت
- ZIP تجمعی خصوصی ۱۰ نوامبر ۲۰۲۶: `jobiew_gpt6_private_checkpoint_001_2840.zip`، SHA256 `d0b8782a8acd4259a001ccbe4395a490bfbdf64f4107833e036c0e2ebbed44d3`.
- SHA256 منبعِ **اعلام‌شده در خود checkpoint**: `164a31e46514ee958be67a6cf2f88f8ec9555baf80f45e7e0101592c34c482d0`. فایل اصلی منبع برای اعتبارسنجی مستقل در اختیار ابزار نیست؛ بنابراین تطبیق هویت و شواهد هر کاندید با دیتابیس مستقلِ موجود الزامی است.
- ۲٬۲۴۰ تحلیل پیشنهادی، مجموعاً ۶٬۶۹۶ محور عددی و ۶٬۷۴۴ محور فاقد شاهد. داده‌ها **تأیید معنایی و حقوق انتشار ندارند**، با برچسب `NOT_ESTABLISHED` و `publication=DISABLED`.
- هیچ اسکریپت موجود در ZIP اجرا نمی‌شود. این ZIP هرگز در GitHub، static، media یا سرویس فایل عمومی قرار نگیرد.
- واردکردن خصوصی، بازبینی معنایی، بررسی حقوقی/انتساب/استقلال و انتشار عمومی چهار کار **جدا** هستند.
- این نسخه قابلیت واردکردن خصوصی در production را تنها در دیتابیس دقیقاً `jobiew`، با آزمون SHA و مطابقت خط‌به‌خط DB و تنها با **سوییچ مستقل و موقت** مهیا می‌کند. این ابزار هیچ وضعیت source یا public را تغییر نمی‌دهد.

## استقرار کد و DB
این تغییر دارای migration افزایشی `criteria_v2.0005_criteriacompanyreleaseevent_v224` است؛ نخست بکاپ `pg_dump -Fc` و آزمون restore واقعی، بعد `migrate --plan`, سپس `migrate --noinput`, `collectstatic` و restart service.
نسخهٔ جابیو روی `/opt/jobiew` است؛ **Gunicorn باید WorkingDirectory=/opt/jobiew/backend** داشته باشد، نه `/opt/jobiew-git-candidate/backend`.

برای پنل خصوصی در `/etc/jobiew/jobiew.env`، مقادیر یکتا (بدون duplicate) به env سرویس افزوده شوند:

```dotenv
DJANGO_DEBUG=0
JOBIEW_CHECKPOINT_PUBLIC_HOST=jobiew.ir
JOBIEW_PRIVATE_CHECKPOINT_REVIEW_ENABLED=1
JOBIEW_CHECKPOINT_STAGING_ENABLED=0
JOBIEW_COMPANY_RELEASE_ONLY_ENABLED=1
JOBIEW_DUAL6_PUBLICATION_ENABLED=0
JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED=0
```

به `JOBIEW_PRIVATE_CHECKPOINT_IMPORT_ENABLED=1` در env **دائمی سرویس عمومی نیاز نیست** و بهتر است فقط برای اجرای فرمان ورود به‌صورت موقت تعریف شود.
`DJANGO_ALLOWED_HOSTS` باید `jobiew.ir` را شامل شود و Nginx روی HTTPS، `X-Forwarded-Proto: https` قابل‌اعتماد را به Django بدهد (به‌همراه `DJANGO_TRUST_PROXY=1` در پیکربندی reverse proxy صحیح). بدون HTTPS صفحهٔ خصوصی 404 می‌شود.

## انتقال محرمانهٔ checkpoint
ابتدا ZIP را از فایل ضمیمهٔ همین گفتگو روی رایانهٔ خود ذخیره کنید. از دستگاهی که به VPS SSH دارد فایل را با `scp` منتقل کنید، نه با Git و نه به public webroot:

```bash
scp jobiew_gpt6_private_checkpoint_001_2840.zip root@YOUR_SERVER_IP:/root/
```

روی سرور:

```bash
sudo install -d -m 700 -o jobiew -g jobiew /var/lib/jobiew/checkpoints
sudo mv /root/jobiew_gpt6_private_checkpoint_001_2840.zip /var/lib/jobiew/checkpoints/
sudo chown jobiew:jobiew /var/lib/jobiew/checkpoints/jobiew_gpt6_private_checkpoint_001_2840.zip
sudo chmod 600 /var/lib/jobiew/checkpoints/jobiew_gpt6_private_checkpoint_001_2840.zip
sha256sum /var/lib/jobiew/checkpoints/jobiew_gpt6_private_checkpoint_001_2840.zip
```

مقدار SHA باید با مقدار دقیق اعلام‌شده در بالا مطابقت داشته باشد؛ در غیر این صورت متوقف شوید.

## ورود خصوصی (dry-run و سپس apply با تایید صریح)
همان محیط env سرویس باید در `systemd-run` استفاده شود؛ این گزینه‌ها را از root و با همان PostgreSQL موجود اجرا کنید:

```bash
sudo systemd-run --unit=jobiew-checkpoint-dry-v224 --wait --pipe --collect \
  --uid=jobiew \
  --property=EnvironmentFile=/etc/jobiew/jobiew.env \
  --property=Environment=JOBIEW_PRIVATE_CHECKPOINT_IMPORT_ENABLED=1 \
  --working-directory=/opt/jobiew/backend \
  /opt/jobiew/.venv/bin/python manage.py stage_checkpoint_private_prod_v224 \
  --checkpoint /var/lib/jobiew/checkpoints/jobiew_gpt6_private_checkpoint_001_2840.zip \
  --expected-db jobiew \
  --expected-checkpoint-sha256 d0b8782a8acd4259a001ccbe4395a490bfbdf64f4107833e036c0e2ebbed44d3 \
  --expected-source-sha256 164a31e46514ee958be67a6cf2f88f8ec9555baf80f45e7e0101592c34c482d0 \
  --after-id 0 --limit 100
```

اگر `CUMULATIVE_PREFLIGHT_FAILED`، `SOURCE_IDENTITY_OR_CONTENT_MISMATCH`، یا `MODEL_EVIDENCE_NOT_VERBATIM` دیدید، **ادامه ندهید و منبع یا SHA را برای عبور از کنترل ویرایش نکنید**. اگر `DRY_RUN_READ_ONLY` و `PREFLIGHT_PASS` دیدید، برای همان دسته `--apply --acknowledge-unverified-private-data` را به همان فرمان اضافه کنید.

به‌ازای دسته‌های بعد، `--after-id` را از `last_candidate_id` گزارش قبلی بگذارید؛ `--limit` بین ۱ تا ۵۰۰ است. اجرای مجدد محتواهای یکسان idempotent است، تصمیم‌های انسانی قبلی را پاک نمی‌کند و **هر checkpoint جدید برای محتواهای تغییریافته به بازبینی دستی نیاز دارد**. خطای یک دسته موجب رد آن دسته و توقف فرایند می‌شود.

## صفحهٔ ادمین و انتشار شرکت
پس از ورود، با حساب staff معتبر و HTTPS:
1. `https://jobiew.ir/internal/criteria/checkpoint/` — پرونده‌های خصوصی، تجمیع هر شرکت، متن/شواهد هر محور.
2. صفحهٔ هر شرکت ← «بازبینی و تأیید گروهی امتیازهای این شرکت». همهٔ واجدشرایط انتخاب هستند؛ موارد مشکوک را از انتخاب بردارید، شواهد باقی‌مانده را واقعاً بخوانید، یادداشت و تصمیم را ثبت کنید. برای هر تجربه، رویداد حسابرسی و digest مستقل ذخیره می‌شود.
3. `/admin/experiences/experiencereviewevent/add/` — تصمیم‌های جداگانهٔ `copyright: approved`، `attribution: verified` و `independence: verified` **فقط با سند واقعی و `evidence_url` معتبر**؛ URL منبع به‌تنهایی لزوماً مجوز بازنشر نیست. وضعیت شرکت هم نیازمند `identity_status=verified` و `tech_status=verified` است. نوع هر تجربه باید در `CriteriaReviewEvent` تأیید شود. هیچ‌کدام از این وضعیت‌ها با ورود فایل یا تأیید نمره خودکار ساخته نمی‌شوند.
4. صفحهٔ هر شرکت ← «انتشار یا توقف امتیازهای تأییدشدهٔ این شرکت». ابتدا تعداد رکوردهای دارای همهٔ مدارک را نشان می‌دهد. با تأیید جداگانهٔ مالک، یک snapshot از **فقط همین تحلیل‌های دارای مدرک** منتشر می‌شود. رکوردهای جدید در بروزرسانی بعدی خودکار وارد snapshot عمومی نمی‌شوند. دکمهٔ توقف انتشار امکان برگشت دارد.
5. برای فعال‌سازی واقعی نمایش امتیازهای انتشار‌داده‌شده روی سایت، تنها **پس از بازبینی حقوقی و معنایی** دو مقدار `JOBIEW_DUAL6_PUBLICATION_ENABLED=1` و `JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED=1` را روشن کنید؛ `JOBIEW_COMPANY_RELEASE_ONLY_ENABLED=1` باید باقی بماند. حتی در این حالت فقط رویداد انتشار ثبت‌شده و امتیازهای دارای evidence و مجوز معتبر نمایش دارند. `body` کامل روایت از این راه عمومی نمی‌شود.

## مراقبت‌های عملیاتی
- انتشار روی یک VPS ۱ گیگ رم: CLI در دسته‌های ۱۰۰ تا ۵۰۰ تجربه، نه اجرای پردازش هم‌زمان. پس از هر دسته وضعیت حافظه و خطای DB بررسی شود.
- رمز ادمین قبلاً در گفتگو وارد شده: تغییر رمز و خروج نشست‌های قدیمی توصیه می‌شود.
- آرشیو ZIP حاوی محتوای خصوصی باید روی دیسک محدود به کاربر jobiew و با mode 0600 باشد.
- ریسک حقوقی و کنترل دسترسی با زدن checkbox یا داشتن URL منبع رفع نمی‌شود؛ تصمیم باید مستند و قابل دفاع باشد.
