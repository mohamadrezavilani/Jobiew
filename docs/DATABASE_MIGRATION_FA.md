# انتقال دیتابیس فعلی Windows به PostgreSQL سرور Jobiew

**بسته سورس شامل داده نیست.** برای حفظ ۶٬۳۱۲ نظر، نمره‌های five_v1، تاییدهای کارکنان و تاریخچه اصلاحیه‌ها باید خود PostgreSQL فعلی منتقل شود. صرف اجرای کراولر، سوابق امتیازدهی را بازسازی نمی‌کند.

## روش پیشنهادی

1. اجرای ویرایش داده‌ها و کراول روی دیتابیس محلی را موقتاً متوقف کنید؛ از انتشار یا دریافت داده جدید در زمان بکاپ خودداری شود.
2. با نسخه متناسب با PostgreSQL محلی `pg_dump --format=custom` بکاپ بگیرید (از همان DB تنظیم‌شده در Windows، نه SQLite کراولر). رمز را تعاملی وارد کنید و در Git/دستورات ذخیره نکنید.
3. بکاپ را با `scp` و اتصال رمزگذاری‌شده به سرور انتقال دهید؛ روی سرور به محیط غیرعمومی قرار دهید.
4. روی سرور PostgreSQL یک دیتابیس خالی با مالک `jobiew_app` ایجاد کنید. قبل از restore در آن Migration اجرا نکنید.
5. restore نمونه:

```bash
# On server; adjust FILE and user to your real deployment.
pg_restore --no-owner --no-acl --exit-on-error --single-transaction \
  --host=127.0.0.1 --username=jobiew_app --dbname=jobiew \
  /var/lib/jobiew/private-restore.dump
```

6. فایل خصوصی `.env` را مطابق DB جدید تنظیم کنید. `python backend/manage.py migrate --noinput` را بعد از restore اجرا کنید (نه قبل از آن).
7. وضعیت و شمار رکوردها، اصلاحیه‌های فعال و کنترل‌های انتشار را با دیتابیس محلی مقایسه کنید:

```bash
cd /opt/jobiew/backend
# with correct environment loaded
../.venv/bin/python manage.py five_criteria_status_v7
../.venv/bin/python manage.py check
../.venv/bin/python manage.py showmigrations
```

## وضعیت SQLite کراولر

اگر checkpoint و صف تاریخی کراولر را هم می‌خواهید، پوشه `data/tajrobewiki.db` و فایل‌های WAL/SHM آن را با توقف ایمن کراولر یا SQLite backup API جداگانه انتقال دهید، و در `/var/lib/jobiew/data/tajrobewiki.db` بگذارید. **فقط کپی‌کردن فایل SQLite در حال استفاده بدون WAL ممکن است داده را از دست بدهد.** برای شروع تمیز می‌توانید از دیتابیس کراولر تازه استفاده کنید؛ اما ممکن است صفحات قبلی دوباره واکشی شوند و باید محدودیت‌های منبع را رعایت کنید.

همگام‌ساز `sync_crawler_live` برای ردیف‌های جدید URL یکتا را به‌روز می‌کند؛ این عملیات نه AI scoring است و نه Migration کامل امتیازها. گزارش‌های `reports/crawler_sync_v34` را پس از نخستین اجرای سرور بررسی کنید.
