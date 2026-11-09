# Jobiew v2.0.16 — پذیرش فنی خصوصی؛ نه تأیید حقوقی یا محصول منتشرشده

## خروجی این نسخه

- صفحهٔ خصوصی مرور مجموع موقت شش معیار برای هر شرکت، به تفکیک کار و مصاحبه
- شمارش هر تجربه حداکثر یک‌بار در هر معیار، رد تحلیل تکراری/قدیمی و `null` به‌جای صفر
- کنترل یکپارچگی شواهد و متن و وضعیت source
- دستور ممیزی خواندنی `verify_dual6_pilot_v216` برای دیتابیس محلی
- تست‌های دسترسی، عدم انتشار، جداسازی شرکت‌ها، `null`، و رکوردهای stale

هیچ نمرهٔ `pilot_unverified` تأییدشده به حساب نمی‌آید. کفایت تعداد نمونه در نمای آزمایشی فقط شاخص *تعداد* است، نه دقت و اعتبار نمره، استقلال تجربه یا مجوز استفاده. **این نتیجه به سایت عمومی راه نمی‌یابد**.

## نصب و تست

از ریشهٔ پروژه، PowerShell:

```powershell
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\jobiew_v216_windows.zip" -DestinationPath "$env:TEMP\jobiew_v216_pkg" -Force
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:TEMP\jobiew_v216_pkg\jobiew_v216_windows\install_v216_windows.ps1" -RepoRoot "$($PWD.Path)" -Push
```

پیش‌نیاز: شاخهٔ `feature/jobiew-dual6-v215-bounded-bulk` روی commit `f670272beaeab486a5f6d7c3bb1896d928ce066b` و working tree تمیز. هنگام نصب صرفاً DB تست موقتی ساخته و حذف می‌شود. هیچ Migration تازه ندارد.

## اجرای گزارش پذیرش بدون نوشتن

```powershell
$env:DJANGO_DEBUG = '1'
$env:DJANGO_SETTINGS_MODULE = 'workplace_insights.settings'
$env:WI_DB_ENGINE = 'postgresql'
$env:PYTHONPATH = "$($PWD.Path)\backend"
$env:JOBIEW_DUAL6_PUBLICATION_ENABLED = '0'
python backend/manage.py verify_dual6_pilot_v216 --expected-db workplace_insights_dev
```

گزارش صرفاً اعداد و وضعیت مسدودکننده را برمی‌گرداند، نه روایت‌ها یا نقل‌قول‌های خصوصی. محدودیت به Windows و DB نام‌گذاری‌شدهٔ محلی صرفاً محافظ کاربردی است؛ تونل به Production را قابل‌تشخیص نمی‌کند.

## دیدن مجموع آزمایشی هر شرکت

```powershell
$env:JOBIEW_PRIVATE_PILOT_DASHBOARD_ENABLED='1'
python backend/manage.py runserver 127.0.0.1:8000
```

آدرس: `http://127.0.0.1:8000/internal/criteria/pilot/`؛ با حساب مدیر مجاز وارد شو، روی نام شرکت کلیک کن. به‌جز حساب staff دارای مجوزهای مشخص، هیچ‌کس اجازهٔ مشاهده ندارد. این قابلیت با `DEBUG=0` یا هنگام فعال بودن انتشار امتیاز عمومی به‌طور کامل بسته است.

## وضعیت تحویل کل محصول

- پیاده‌سازی ۶+۶، کفایت داده، پایلوت ۴۰ تجربه، پردازش bounded، آزمون و صفحهٔ داخلی: آمادهٔ پذیرش فنی
- امتیازدهی همهٔ ۸۱۳۹ تجربه: **انجام نشده**؛ ۸۰ مورد از محدودهٔ طول خارج‌اند و ۴۰ مورد پایلوت دارند
- مجوز استفاده، تأیید انتساب و طبقه‌بندی منابع: **۸۱۳۹ مورد در وضعیت تأییدنشده**
- مرجع کیفیت انسانی مستقل: هنوز موجود نیست
- امتیاز عمومی: غیرفعال و نباید فعال شود تا شرایط جداگانه احراز شوند
- شاخهٔ توسعه در GitHub است؛ Ubuntu production بدون تغییر

این مرزبندی عمداً به‌جای اعلام نادرست «پروژه تمام شد» است.
