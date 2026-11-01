# نصب Jobiew روی Ubuntu 24.04/26.04 با Nginx، Gunicorn و PostgreSQL

دستورها برای سروری تازه نوشته شده‌اند. دامنه، رمزها، مسیرها و DB را مطابق سرور خود تغییر دهید. **به‌جای اجرای کورکورانه، هر خروجی را بررسی کنید.** پیش از انتشار عمومی اجازه جمع‌آوری/بازنشر محتوای منبع و وضعیت محرمانگی بازبینی شود.

## ۱. بسته‌ها و کاربر سرویس

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip postgresql postgresql-client nginx git certbot python3-certbot-nginx
sudo adduser --system --group --home /var/lib/jobiew jobiew
sudo install -d -o jobiew -g jobiew -m 750 /opt/jobiew /var/lib/jobiew /var/lib/jobiew/data /var/lib/jobiew/reports /var/lib/jobiew/locks /var/lib/jobiew/import_staging
sudo install -d -m 755 /var/www/jobiew
sudo install -d -o jobiew -g www-data -m 755 /var/www/jobiew/static
sudo install -d -m 750 -o root -g jobiew /etc/jobiew
```

روی Ubuntu از Python 3.12+ استفاده کنید؛ در صورت نیاز `python3.12` را جایگزین `python3` کنید. PostgreSQL را روی loopback نگه دارید.

## ۲. انتقال سورس و نصب وابستگی‌ها

ZIP را فقط از سیستم امن به سرور کپی کنید. محتوای پوشه `Jobiew/` باید مستقیماً زیر `/opt/jobiew` قرار بگیرد.

```bash
# Run from extracted Jobiew directory on the server
sudo cp -a . /opt/jobiew/
sudo chown -R jobiew:jobiew /opt/jobiew
sudo -u jobiew python3 -m venv /opt/jobiew/.venv
sudo -u jobiew /opt/jobiew/.venv/bin/python -m pip install -r /opt/jobiew/requirements.txt
```

## ۳. PostgreSQL

بهترین روش برای دیتابیس فعلی، **restore از بکاپ PostgreSQL همان پروژه** است. راهنما را در `docs/DATABASE_MIGRATION_FA.md` ببینید. اگر دیتابیس کاملاً جدید و بدون داده می‌سازید:

```bash
sudo -u postgres createuser -P jobiew_app
sudo -u postgres createdb --owner=jobiew_app --encoding=UTF8 jobiew
```

از اجرای `migrate` روی دیتابیس خالی و سپس restore بی‌برنامه دیتابیس قدیمی خودداری کنید.

## ۴. فایل متغیرهای محرمانه

```bash
sudo cp /opt/jobiew/.env.example /etc/jobiew/jobiew.env
sudo chown root:jobiew /etc/jobiew/jobiew.env
sudo chmod 640 /etc/jobiew/jobiew.env
# Create a random Django secret (copy its OUTPUT to .env, do NOT commit to git):
/opt/jobiew/.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(64))'
sudo nano /etc/jobiew/jobiew.env
```

`DJANGO_SECRET_KEY`, `WI_DB_PASSWORD`, دامنه، و `DJANGO_ALLOWED_HOSTS` و `DJANGO_CSRF_TRUSTED_ORIGINS` را پر کنید. `WI_DB_ENGINE=postgresql` باید صریح باشد. `JOBIEW_CRAWLER_PERMISSION_CONFIRMED=0` را تا تأیید حق جمع‌آوری/بازنشر تغییر ندهید.

## ۵. تست و آماده‌سازی وب

```bash
sudo -u jobiew bash -c 'set -a; source /etc/jobiew/jobiew.env; set +a; cd /opt/jobiew/backend; /opt/jobiew/.venv/bin/python manage.py check'
sudo -u jobiew bash -c 'set -a; source /etc/jobiew/jobiew.env; set +a; cd /opt/jobiew/backend; /opt/jobiew/.venv/bin/python manage.py showmigrations'
# Only after successful database restore, or when initializing an intentionally empty fresh DB:
sudo -u jobiew bash -c 'set -a; source /etc/jobiew/jobiew.env; set +a; cd /opt/jobiew/backend; /opt/jobiew/.venv/bin/python manage.py migrate --noinput'
sudo -u jobiew bash -c 'set -a; source /etc/jobiew/jobiew.env; set +a; cd /opt/jobiew/backend; /opt/jobiew/.venv/bin/python manage.py collectstatic --noinput'
```

**نکته:** فایل env شامل مقادیر قابل‌اعتماد برای bash است؛ از کاراکترهای مشکل‌ساز و خطوط غیرمعتبر اجتناب کنید. در محیط حرفه‌ای بهتر است از systemd EnvironmentFile یا یک ابزار مدیریت اسرار استفاده کنید؛ دستور `source` صرفاً برای راه‌اندازی کنترل‌شده است.

## ۶. Gunicorn و Nginx

```bash
sudo cp /opt/jobiew/deploy/systemd/jobiew-web.service /etc/systemd/system/
sudo cp /opt/jobiew/deploy/nginx/jobiew.conf /etc/nginx/sites-available/jobiew
sudo sed -i 's/jobiew.example.com/YOUR_REAL_DOMAIN/g' /etc/nginx/sites-available/jobiew
sudo ln -s /etc/nginx/sites-available/jobiew /etc/nginx/sites-enabled/jobiew
sudo systemctl daemon-reload
sudo systemctl enable --now jobiew-web
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d YOUR_REAL_DOMAIN
sudo systemctl restart jobiew-web
sudo systemctl status jobiew-web
```

تا زمانی که HTTPS فعال نیست، سایت را عمومی نکنید. پس از TLS با `python manage.py check --deploy` تنظیمات را کنترل کنید. برای پس‌زمینه نقشه OpenFreeMap و CDNs مورد استفاده سایت نیز اتصال شبکه مرورگر لازم است.

## ۷. کراولر و همگام‌سازی افزایشی

همه مراحل در **همان سرور** اجرا می‌شوند. SQLite تنها به‌عنوان ذخیره اجرایی خصوصی کراولر در `/var/lib/jobiew/data/tajrobewiki.db` استفاده می‌شود؛ Django به PostgreSQL متصل است.

```bash
# Offline no-write plan
sudo -u jobiew /opt/jobiew/.venv/bin/python /opt/jobiew/scripts/run_ingest.py --show-plan
# If you brought an existing crawler SQLite data store to this host, inspect before applying:
sudo -u jobiew bash -c 'set -a; source /etc/jobiew/jobiew.env; set +a; /opt/jobiew/.venv/bin/python /opt/jobiew/scripts/run_ingest.py --mode preview'
# Run this only after inspecting the preview and existing production data:
sudo -u jobiew bash -c 'set -a; source /etc/jobiew/jobiew.env; set +a; /opt/jobiew/.venv/bin/python /opt/jobiew/scripts/run_ingest.py --mode sync-only'
```

برای اجرای کراول واقعی ابتدا مقدار `JOBIEW_CRAWLER_PERMISSION_CONFIRMED=1` را فقط پس از تأیید مجوز تنظیم کنید. سپس:

```bash
sudo cp /opt/jobiew/deploy/systemd/jobiew-ingest.service /etc/systemd/system/
sudo cp /opt/jobiew/deploy/systemd/jobiew-ingest.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start jobiew-ingest.service
sudo journalctl -u jobiew-ingest.service -n 80 --no-pager
# Only after a manually verified crawl AND PostgreSQL sync:
sudo systemctl enable --now jobiew-ingest.timer
sudo systemctl list-timers '*jobiew*'
```

Timer پیش‌فرض روزانه ۰۱:۳۰ UTC (۰۵:۰۰ تهران) با تأخیر تصادفی تا ۱۰ دقیقه است. آن را مطابق سقف درخواست مجاز منبع تغییر دهید. `systemd` از اجرای هم‌زمان یک unit جلوگیری می‌کند. فرمان sync یک قفل مستقل محلی هم دارد.

**توجه:** روی سایت منبع کد می‌تواند در برخی خطاهای سیاستی با حفظ checkpoint بازگردد؛ گزارش اجرای کراولر و شمار رکوردهای sync را واقعاً بررسی کنید. موفقیت فرمان فقط به‌معنی وجود نظر تازه نیست.

## ۸. عملیات و بکاپ

```bash
sudo systemctl status jobiew-web jobiew-ingest.timer
sudo journalctl -u jobiew-web -n 80 --no-pager
sudo journalctl -u jobiew-ingest.service -n 80 --no-pager
sudo -u postgres pg_dump --format=custom --no-owner jobiew > /var/lib/jobiew/REPLACE_WITH_SECURE_BACKUP_PATH.dump
```

برای بکاپ PostgreSQL و SQLite کراولر، زمان‌بندی مستقل و سیاست نگهداری تعریف کنید. داده واقعی یا فایل بکاپ را به Git اضافه نکنید.
