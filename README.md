# Jobiew | جابیو

پلتفرم پژوهشی تحلیل تجربه‌های کاری و معرفی شرکت‌ها، به‌همراه کراولر مستقل و همگام‌ساز افزایشی با PostgreSQL.

**مبنای پروژه:** نسخه فعلی Django و TajrobeWiki crawler در فایل `Jobiew_Source_Snapshot.zip` ارائه‌شده در ۱ نوامبر ۲۰۲۶. این بسته **کد است**؛ دیتابیس واقعی ۶٬۳۱۲ تجربه کاری و تاریخچه ارزیابی‌ها در فایل سورس موجود نبود و باید جداگانه منتقل شود.

## ساختار

```text
Jobiew/
├── backend/            # Django app (internal Python package workplace_insights retained)
├── crawler/            # source crawler + offline parser regression tests
├── scripts/            # one-shot ingestion orchestrator
├── deploy/
│   ├── nginx/           # reverse proxy
│   └── systemd/         # Gunicorn and scheduled crawl+sync
├── docs/               # deployment, data migration, release checks
├── tests/              # offline orchestration tests
├── .env.example
├── .gitignore
└── requirements.txt
```

## چرا پکیج داخلی هنوز workplace_insights نام دارد؟

نام برند و مخزن **Jobiew** است. برای حفظ Migrationها، شناسه اپلیکیشن‌های Django، جدول‌های موجود و importهای صدها فایل، نام پکیج داخلی Django موقتاً تغییر نکرده است. این تصمیم مانع شکستن سابقه امتیازدهی و PostgreSQL در مهاجرت می‌شود.

## شروع سریع توسعه محلی

Python 3.12+، PostgreSQL برای حالت واقعی لازم است. تنها برای توسعه/تست می‌توان SQLite محلی را فعال کرد.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DJANGO_DEBUG=1 WI_DB_ENGINE=sqlite
python backend/manage.py migrate
python backend/manage.py runserver
```

## بررسی‌های اجراشده پیش از تحویل

- بررسی نحوی Python کل سورس: موفق.
- تست آفلاین کراولر: **۴۲ تست موفق**.
- تست فرمان هماهنگ‌کننده اجرا: **۵ تست موفق**.
- اجرای `python manage.py check`، تست‌های Django با PostgreSQL و اجرای واقعی شبکه‌ای در این محیط انجام نشده‌اند (وابستگی Django / سرور PostgreSQL اینجا در دسترس نبود). اجرای آن‌ها روی Ubuntu الزامی است.
- به‌دلیل حذف ایمن اطلاعات محرمانه توسط Collector، تنظیمات Django و اتصال PostgreSQL از متغیرهای محیطی بازسازی شده‌اند؛ تنظیمات شخصی Windows قبلی به نسخه جدید منتقل نشده است.

## شروع انتشار

1. `docs/DEPLOY_UBUNTU_FA.md` را بخوانید و Ubuntu/PostgreSQL/HTTPS را تنظیم کنید.
2. با `docs/DATABASE_MIGRATION_FA.md` دیتابیس واقعی قبلی را با `pg_dump/pg_restore` منتقل کنید؛ **بدون این کار، داده‌های موجود و نمره‌های AI در سرور جدید نیستند**.
3. فرمان `python scripts/run_ingest.py --show-plan` هیچ تغییر داده‌ای ایجاد نمی‌کند.
4. پس از احراز حق کراول و چند اجرای دستی موفق، `jobiew-ingest.timer` را فعال کنید.

## محدودیت صریح

کراولر فقط مطالب منبع را با رعایت robots و توقف روی محدودیت‌ها دریافت می‌کند؛ به‌طور خودکار امتیاز AI تولید یا منتشر نمی‌کند. ثبت امتیازهای پنج‌معیاری و هر نوع انتشار، کنترل‌های قبلی و فرایند بازبینی خود را دارند. اعداد پژوهشی تا کسب شرایط انتشار عمومی نمی‌شوند.

اطلاعات واقعی، فایل `.env`، رمزها و فایل‌های خروجی/بکاپ نباید در Git ثبت شوند. تصاویر فعلی از Snapshot حفظ شده‌اند؛ اصالت، مجوز استفاده مجدد و حق نمایش آن‌ها پیش از انتشار عمومی باید بررسی شود.
