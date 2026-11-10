# جابیو v2.0.25 — پنل یکپارچه بررسی شرکت و تشخیص خطای CSRF

## وضعیت واقعی
در ۱۰ نوامبر ۲۰۲۶، ورود خصوصی checkpoint به دیتابیس `jobiew` طبق گزارش سرور موفق شد: از ۲٬۲۴۰ پیشنهاد، ۶ مورد تکراری کنار گذاشته شد و **۲٬۲۳۴ تحلیل جدید** به وضعیت `pilot_unverified` وارد شدند. هیچ موردی خودکار تأیید یا منتشر نشد.

## رابط تازه
- `https://jobiew.ir/admin/`: خانهٔ متمرکز ادمین. سوابق و جداول قدیمی صرفاً از منو پنهان می‌شوند و **نه از دیتابیس یا URL حذف**.
- `https://jobiew.ir/admin/companies/company/checkpoints/`: فهرست شرکت‌هایی که checkpoint خصوصی دارند، شمارندهٔ در انتظار، بازبینی‌شده، فاقد شاهد، لینک تأیید گروهی و انتشار/توقف.
- از فهرست شرکت‌ها و صفحهٔ هر شرکت هم دکمهٔ مستقیم «تأیید گروهی GPT-6» و «انتشار/توقف» موجود است.
- `/admin/companies/company/<company_id>/checkpoint/bulk/`: فرم Django Admin، با CSRF فعال، کوکی تأیید و آدرس same-origin.
- `/admin/companies/company/<company_id>/checkpoint/release/`: تصمیم مستقل انتشار. تنها نمره‌های دارای شواهد شش‌محوری، بازبینی انسانی و مستندات حقوق/انتساب/استقلال واجد شرایط‌اند.
- مسیرهای پیشین `/internal/criteria/checkpoint/` همچنان برقرار و خصوصی هستند، اما بهترین مسیر کاری از ادمین است.

## رفع و تشخیص خطای 403
هیچ‌گونه `csrf_exempt`، خاموش‌کردن CSRF، تغییر کوکی به insecure یا `DEBUG=1` انجام نمی‌شود. درخواست‌های POST همچنان با `CsrfViewMiddleware` و `admin_site.admin_view` اعتبارسنجی می‌شوند؛ نمایش GET کوکی CSRF را تضمین می‌کند. فرم با same-origin می‌فرستد.
در صورت 403، صفحهٔ فارسی کد خطای غیرمحرمانه مثل `COOKIE_NOT_SET`، `TOKEN_MISSING`، `ORIGIN_MISMATCH` یا `REFERER_MISMATCH` نشان می‌دهد. `journalctl -u jobiew-web -n 80 --no-pager | grep JOBIEW_CSRF_REJECTED` دستهٔ خطا و حالت HTTPS را بدون توکن، رمز، کوکی یا متن خصوصی گزارش می‌کند. با این کد می‌توان علت واقعی در مرورگر/ CDN را رفع کرد. قبلاً `CSRF_TRUSTED_ORIGINS` و `SECURE_PROXY_SSL_HEADER` درست گزارش شده‌اند؛ برای رفع کورکورانه هیچ متغیر امنیتی را عوض نکنید.

## استقرار کم‌خطر
`main` را روی `/opt/jobiew` با `sudo -u jobiew git -C /opt/jobiew pull --ff-only origin main` به‌روز کنید، پس از بکاپ / سلامت سرویس. `WorkingDirectory=/opt/jobiew/backend` را کنترل کنید؛ تغییرات v225 فقط قالب‌ها و مسیرهای ادمین است و migration جدید ندارد. سپس به‌کمک env فایل systemd:
```bash
sudo systemd-run --unit="jobiew-v225-check-$(date +%s)" --wait --pipe --collect \
  --uid=jobiew --property=EnvironmentFile=/etc/jobiew/jobiew.env \
  --working-directory=/opt/jobiew/backend /bin/bash -c \
  '/opt/jobiew/.venv/bin/python manage.py check && /opt/jobiew/.venv/bin/python manage.py makemigrations --check --dry-run && /opt/jobiew/.venv/bin/python manage.py migrate --plan && /opt/jobiew/.venv/bin/python manage.py collectstatic --noinput'
sudo systemctl restart jobiew-web
```
در صورت موفقیت، ادمین را در پنجرهٔ جدید مرورگر باز کنید و وارد شوید تا کوکی/توکن تازه ساخته شود. سوییچ‌های انتشار فعلی را **بدون تغییر** بگذارید. هیچ ZIP دوباره وارد نمی‌شود.

## احتیاط
تأیید گروهی شش محور همان تأیید مجوز بازنشر نیست؛ وضعیت `source_rights=NOT_ESTABLISHED` با کلیک تبدیل به مجوز نمی‌شود. اگر مدرک واقعی وجود ندارد، صفحهٔ انتشار باید نتیجه را صفر یا غیرقابل انتشار نشان دهد. برای checkpointهای بعدی نیز تأییدها و رویداد انتشار شرکت قبلی به‌صورت خودکار به تجربه‌های تازه سرایت نمی‌کنند.

## علت کشف‌شده در تست HTTPS
نسخهٔ قبلی `_private` به همهٔ صفحات `Referrer-Policy: no-referrer` می‌داد. روی مرورگرهایی که برای فرم same-origin، `Origin` نمی‌فرستند، این هدر باعث نرسیدن `Referer` در POST می‌شد و Django به‌درستی با کد CSRF 403 رد می‌کرد. نسخه v225 برای **فقط دو صفحهٔ فرم‌دار** (تأیید گروهی و انتشار/توقف) هدر `Referrer-Policy: same-origin` می‌فرستد؛ روی صفحات گزارش فقط‌خواندنی همچنان `no-referrer` باقی می‌ماند. سیاست same-origin به سایتی بیرون از جابیو هیچ ارجاعی نمی‌دهد. تست end-to-end با `enforce_csrf_checks=True` باید GET کوکی و POST بدون Origin ولی دارای Referer را قبول کند و Origin خارجی را رد کند.
