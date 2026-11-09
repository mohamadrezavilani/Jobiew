# Jobiew v2.0.13 — صفحهٔ فقط‌خواندنی پایلوت خصوصی ۶+۶

این مرحله نمایشی است؛ هیچ تحلیل AI تازه‌ای اجرا نمی‌شود، هیچ دیتابیسی از طریق کد نصب تغییر نمی‌کند، هیچ امتیازی تأیید یا منتشر نمی‌شود و هیچ متن خصوصی به GitHub منتقل نمی‌شود.

## دامنه

- مسیر فهرست: `/internal/criteria/pilot/`
- مسیر جزئیات: `/internal/criteria/pilot/<analysis_id>/`
- صرفاً `CriteriaAnalysis`های دارای `review_status=pilot_unverified` و `raw_payload.engine=jobiew_private_assistant_pilot_v212` نمایش داده می‌شوند.
- جستجو بر اساس نوع کاری/مصاحبه و شناسه شرکت، شمار نمره‌دار و null، صفحه‌بندی و شش شاهد دقیق برای هر تجربه موجود است.
- تغییر هش منبع، محتوای شاهد، نسخه، رد حقوق استفاده یا تکراری‌شدن تجربه موجب هشدار و پنهان شدن متن فعلی در نمایش جزئیات می‌شود.
- وضعیت کپی‌رایت `pending` و انتساب `unverified` به **approved** تغییر نمی‌کنند. نمایش خصوصی **مجوز انتشار نیست**.
- میانگین شرکت محاسبه نمی‌شود؛ هر تجربه از شرکت مستقل است و نباید از کل ۴۰ متن به‌عنوان امتیاز یک شرکت استفاده کرد.
- ثبت هیچ بررسی انسانی یا score approval انجام نمی‌شود. صف v2.0.9 به‌طور عمدی `pilot_unverified`ها را تأیید نمی‌کند.
- صفحه HTML به‌صورت خودکار از قالب‌های Django escape می‌شود. از اشتراک‌گذاری اسکرین‌شات‌های حاوی متن خصوصی خودداری کنید.

## قفل‌های امنیتی

برای باز شدن این نما، **همهٔ شروط** لازم‌اند:

1. `DJANGO_DEBUG=1` (فقط محیط توسعه)
2. `JOBIEW_PRIVATE_PILOT_DASHBOARD_ENABLED=1` (پیش‌فرض خاموش)
3. `JOBIEW_DUAL6_PUBLICATION_ENABLED=0`
4. کاربر فعال، `is_staff` و دارای مجوزهای `experiences.view_publicexperience`، `criteria_v2.view_criteriaanalysis` و `criteria_v2.view_criteriaaxisscore` (superuser محلی کافی است)

صفحه `GET` است؛ `POST` غیرفعال. پاسخ‌ها `no-store`, `noindex`, `no-referrer` و CSP دارند. مسیرهای عمومی و دیتابیس Production تغییر نمی‌کنند.

## تست و اجرا روی ویندوز

از ریشه Git پروژه، پس از نصب بسته و موفق شدن تست‌های آن، برای **مشاهدهٔ محلی**:

```powershell
$env:DJANGO_DEBUG='1'
$env:WI_DB_ENGINE='postgresql'
$env:JOBIEW_PRIVATE_PILOT_DASHBOARD_ENABLED='1'
$env:JOBIEW_DUAL6_PUBLICATION_ENABLED='0'
$env:DJANGO_SETTINGS_MODULE='workplace_insights.settings'
$env:PYTHONPATH="$($PWD.Path)\backend"
python backend/manage.py runserver 127.0.0.1:8000
```

برای مشاهده به `http://127.0.0.1:8000/admin/login/?next=/internal/criteria/pilot/` بروید و با حساب superuser **محلی** وارد شوید؛ سپس `http://127.0.0.1:8000/internal/criteria/pilot/` را باز کنید. اگر قبلاً سرور Django در پورت 8000 روشن است، سرور موازی راه نیندازید؛ متغیر محیطی جدید باید در پردازش همان سرور موجود باشد.

## نکتهٔ پذیرش

تست‌های این نسخه با دیتابیس تست SQLite ایزوله اجرا می‌شوند؛ اعمال Migration جدید یا ارسال داده نیاز نیست. این نما **جایگزین ممیزی کیفیت مستقل یا تأیید منبع** نیست. امتیازهای پایلوت در PostgreSQL توسعه باقی می‌مانند، اما بدون ارتقای وضعیت.
