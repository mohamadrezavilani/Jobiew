# جابیو v2.0.22 — استقرار آزمایشی، بازبینی گروهی و انتشار مشروط

## ۱. مرزبندی ضروری

- **سایت روی دامنه عمومی با طراحی تازه:** فقط `JOBIEW_HOMEPAGE_PUBLIC_ENABLED=1` و با سوییچ `JOBIEW_DUAL6_PUBLICATION_ENABLED=0` نمایش داده شود. این کار به فایل checkpoint نیازی ندارد و فعلاً هیچ امتیاز GPT-6 نشان نمی‌دهد.
- **نمره‌های ۲٬۲۴۰ تجربه:** فقط روی **PostgreSQL آزمایشی جداگانه** و دامنهٔ خصوصی HTTPS/VPN همراه با staff review قابل مشاهده‌اند. به دیتابیس تولید یا دایرکتوری `static/` کپی نشوند.
- **تأیید گروهی خصوصی:** روی صفحهٔ شرکت در `/internal/criteria/checkpoint/` گزینهٔ «بازبینی گروهی» دیده می‌شود. هر تجربه، شش محور، نمره و شاهد را جداگانه دارد. تصمیم یکجا فقط با تأیید بازبین از مشاهدهٔ شواهد و توضیح، یک رویداد حسابرسی برای هر مورد ثبت می‌کند. موارد نامعتبر کنار گذاشته می‌شوند. null هرگز صفر نیست.
- **انتشار واقعی نمره‌ها:** همزمان به دو سوییچ `JOBIEW_DUAL6_PUBLICATION_ENABLED=1` و `JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED=1` نیاز دارد و فقط تحلیل‌های دارای receipt دست‌نخورده، بازبینی شش محور، تصمیم قطعی دسته‌بندی، مجوز دارای رویداد مستند، انتساب/استقلال تأییدشده و شرکت تأییدشده می‌توانند در صفحهٔ **جزئیات شرکت** ظاهر شوند. پیش از ممیزی حقوق/کیفیت و تأیید جداگانهٔ انتشار، این دو سوییچ صفر بمانند. سوییچ‌های staging و publication نباید روی یک سرویس فعال باشند.

## ۲. دستورات ایمن برای نخستین مشاهدهٔ طراحی روی سرور Ubuntu

ابتدا آدرس دامنهٔ واقعی، مسیر مخزن و نام سرویس را با فرمان‌های **صرفاً خواندنی** بررسی کنید (مقادیر نمونه در پروژه لزوماً محیط شما نیستند):

```bash
sudo systemctl status jobiew-web --no-pager
sudo -u jobiew git -C /opt/jobiew status --short
sudo -u jobiew git -C /opt/jobiew branch --show-current
sudo -u jobiew git -C /opt/jobiew rev-parse HEAD
sudo nginx -t
```

اگر مسیر مخزن واقعاً `/opt/jobiew` و checkout از شاخهٔ `main` است، **فقط پس از بکاپ و اطمینان از نبود تغییر محلی**:

```bash
sudo -u jobiew git -C /opt/jobiew fetch origin main
sudo -u jobiew git -C /opt/jobiew pull --ff-only origin main
# از مسیر موجود venv و service اطمینان حاصل کنید
sudo -u jobiew bash -c 'cd /opt/jobiew/backend && /opt/jobiew/.venv/bin/python manage.py check'
sudo -u jobiew bash -c 'cd /opt/jobiew/backend && /opt/jobiew/.venv/bin/python manage.py makemigrations --check --dry-run'
```

این نسخه migration جدید **صرفاً افزایشی** برای receipt خصوصی دارد. اجرای `migrate` روی تولید قبل از بررسی بکاپ، `showmigrations`، طرح rollback و آزمون restore ممنوع است؛ ابتدا همان فرایند در staging مستقل باید پاس شود. بعد از آن `migrate --noinput` را با محیط امن درست هر سرور اجرا کنید.

در `/etc/jobiew/jobiew.env` متعلق به همان سرویس **تولیدی** (نه در Git) تنها برای نمایش صفحهٔ تازه:

```dotenv
DJANGO_DEBUG=0
JOBIEW_HOMEPAGE_PUBLIC_ENABLED=1
JOBIEW_DUAL6_PUBLICATION_ENABLED=0
JOBIEW_GPT6_APPROVED_PUBLICATION_ENABLED=0
JOBIEW_CHECKPOINT_STAGING_ENABLED=0
JOBIEW_CHECKPOINT_IMPORT_STAGING_ENABLED=0
```

پس از پشتیبان‌گیری از فایل env و کنترل `check --deploy`، با مسیرهای واقعی:

```bash
sudo -u jobiew bash -c 'cd /opt/jobiew/backend && /opt/jobiew/.venv/bin/python manage.py collectstatic --noinput'
sudo systemctl restart jobiew-web
sudo systemctl status jobiew-web --no-pager
sudo journalctl -u jobiew-web -n 60 --no-pager
```

`GET /` طراحی جدید را نشان می‌دهد و `GET /companies/` همچنان فهرست سابق است. این چک به معنی موفقیت staging امتیازها نیست. برای **بازگشت فوری**، `JOBIEW_HOMEPAGE_PUBLIC_ENABLED=0` و restart همان سرویس؛ نسخه قبلی صفحه اول بازمی‌گردد.

## ۳. پنل خصوصی امتیازها روی staging

- یک سرویس Gunicorn و Nginx **مستقل** (پورت، env file و هاست جدا)، یک PostgreSQL **جدا** با نام منتهی به `_staging` و restore از دادهٔ مجاز/آزمایشی تهیه کنید. هرگز staging را با DB تولید متصل نکنید. دامنه staging پشت VPN/allowlist با گواهی HTTPS معتبر باشد.
- فایل ZIP خصوصی را فقط با انتقال رمزنگاری‌شده به مسیر خارج از Git، static، رسانهٔ عمومی و artifactهای CI منتقل کنید. فایل را در مخزن commit نکنید.
- برای staging `DJANGO_DEBUG=0`، `DJANGO_ALLOWED_HOSTS=staging.example.test`، `JOBIEW_CHECKPOINT_STAGING_ENABLED=1`، `JOBIEW_CHECKPOINT_STAGING_HOST=staging.example.test`، `JOBIEW_CHECKPOINT_PUBLIC_HOST=www.example.test`، `JOBIEW_PRIVATE_PILOT_DASHBOARD_ENABLED=0`، `JOBIEW_CHECKPOINT_IMPORT_STAGING_ENABLED=1` و هر دو سوییچ publication صفر باشند. میزبان عمومی نباید با `ALLOWED_HOSTS` قابل قبول باشد.
- در همان محیط staging، با SHAهای واقعیِ مستقل checkpoint و source، فرمان dry-run `python manage.py stage_checkpoint_staging_v222 --checkpoint /path/private.zip --expected-db jobiew_staging --expected-checkpoint-sha256 ... --expected-source-sha256 ... --after-id 0 --limit 100` اجرا کنید؛ پس از بکاپ، بررسی منبع و گزارش، همان فرمان به‌علاوهٔ `--apply --acknowledge-unverified-private-data` فقط روی DB staging مجاز است. از `last_candidate_id` برای دستهٔ بعد استفاده کنید. **نسخهٔ اصلی source ZIP باید مستقل مطابقت داده شود.**
- حساب staff دارای مجوزهای `experiences.view_publicexperience`، `criteria_v2.view_criteriaanalysis`، `criteria_v2.view_criteriaaxisscore` و برای ثبت گروهی `criteria_v2.add_criteriascorereviewevent` لازم است.
- مسیرهای خصوصی: `/internal/criteria/checkpoint/`، سپس شرکت، سپس «بازبینی گروهی». از `/admin/criteria_v2/criteriaanalysis/` نیز پیوند هر شرکت قابل استفاده است. بعد از تأیید، در ادمین وضعیت تحلیل‌ها `approved` یا `no_evaluable_scores` خواهد شد، اما هنوز انتشار عمومی رخ نداده است.

## ۴. کنترل نهایی قبل از انتشار نمره

بازبین باید روایت و سند هر محور را بررسی کند؛ تأیید گروهی هرگز جایگزین این بررسی نیست. حقوق پردازش/نگهداری/بازنشر باید جدا و **برای هر منبع** در رویدادهای قابل حسابرسی ثبت شود. انتساب شرکت و استقلال، تصمیم شناسایی نوع تجربه، آزمون صحت معنایی نمونه‌ها، خطر سوگیری داده و حداقل کفایت شش محور باید بررسی شوند. تا رفع این گیت‌ها **فقط طراحی سایت عمومی** قابل نمایش است، نه نمره‌های checkpoint. فعال‌سازی انتشار امتیازها فقط بعد از تأیید جداگانهٔ مالک و ممیزی کامل انجام می‌شود.

## ۵. نسخه و rollback

این تغییر یک migration افزایشی `criteria_v2.0004_checkpointapprovalreceipt_v222` دارد؛ عملیات bulk در تراکنش اتمیک، CSRF، شرط SHA/نسخه و token تغییرناپذیری انجام می‌شود. برگشت رابط با خاموش‌کردن سوییچ‌ها ممکن است؛ حذف migration را روی دیتابیس حاوی receipt بدون طرح نگهداری/بکاپ داده انجام ندهید. در صورت خطا ابتدا دسترسی private و سوییچ انتشار را صفر و سرویس را restart کنید. **این سند گزارش اجرای واقعی سرور نیست.**