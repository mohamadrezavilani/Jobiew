# Jobiew — برگهٔ پذیرش staging خصوصی صفحهٔ اول v2.0.19

> این سند راهنمای اجرای کنترل‌شده است؛ **هیچ اقدامی روی سرور واقعی در این بسته انجام نشده است.** ادغام PR یا موفقیت CI به‌معنی آمادگی عمومی/حقوقی یا مجوز deploy نیست.

## ۱. جداسازی محیط

برای staging از **دامنهٔ مستقل، پایگاه‌دادهٔ جدا با محتوای مصنوعی یا مجاز، حساب کاربری staff اختصاصی و گواهی HTTPS معتبر** استفاده کنید. میزبان باید پشت VPN/allowlist باشد. اتصال staging به دیتابیس تولیدی و فعال‌سازی flagهای staging روی Nginx/Gunicorn تولیدی ممنوع است.

جدول پیشنهادی (مقادیر ساختگی‌اند؛ رمز و دیتابیس واقعی در گیت قرار نمی‌گیرند):

```dotenv
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=stage.example.test
DJANGO_CSRF_TRUSTED_ORIGINS=https://stage.example.test
DJANGO_TRUST_PROXY=1
DJANGO_SECURE_SSL_REDIRECT=1
WI_DB_ENGINE=postgresql
JOBIEW_HOMEPAGE_PREVIEW_ENABLED=1
JOBIEW_HOMEPAGE_STAGING_ENABLED=1
JOBIEW_HOMEPAGE_STAGING_HOST=stage.example.test
JOBIEW_HOMEPAGE_PUBLIC_HOST=www.example.test
JOBIEW_DUAL6_PUBLICATION_ENABLED=0
JOBIEW_DUAL6_PAID_ENABLED=0
JOBIEW_CHECKPOINT_STAGING_ENABLED=0
JOBIEW_CRAWLER_PERMISSION_CONFIRMED=0
```

تنظیمات واقعی `DJANGO_SECRET_KEY`، `WI_DB_*`، `JOBIEW_STATIC_ROOT` را با روش مجاز موجود پروژه در secret store مستقل staging قرار دهید. `DJANGO_ALLOWED_HOSTS` باید staging را شامل شود، `*` و میزبان production را شامل نشود. HTTPS از reverse proxy قابل‌اعتماد باید به Django منتقل شود؛ هدر Forwarded از اینترنت عمومی نباید بدون پاک‌سازی توسط Nginx مورد اعتماد باشد.

## ۲. آزمون‌های لازم

۱. روی شاخهٔ ثابت‌شده و commit مشخص `python manage.py check`, `python manage.py check --deploy` و `python manage.py makemigrations --check --dry-run` را اجرا و خروجی‌ها را ثبت کنید. **در این تغییر نباید migration جدید وجود داشته باشد.**
۲. با `JOBIEW_HOMEPAGE_PREVIEW_ENABLED=0`، مسیر `/internal/homepage-preview/` باید 404 باشد. با روشن‌بودن gate ولی بدون login باید 403 (یا redirect توسط راهکار احراز هویت بیرونی) و برای کاربر معمولی 403 شود؛ حساب staff دارای `companies.view_company` فقط روی میزبان staging و HTTPS امکان مشاهده دارد.
۳. `JOBIEW_HOMEPAGE_PUBLIC_HOST` تهی یا برابر staging، میزبان درخواست متفاوت، اتصال HTTP، وجود `*` یا میزبان تولید در `ALLOWED_HOSTS` و `JOBIEW_DUAL6_PUBLICATION_ENABLED=1` هر کدام باید دسترسی را قطع کنند.
۴. جست‌وجوی فارسی، حالت کاری/مصاحبه، ترتیب بیشترین تعداد/نام، فیلترهای دارای تجربه و شرکت‌های تأییدشده، نتیجهٔ خالی و صفحه‌بندی را با رکوردهای **مصنوعی** امتحان کنید. امتیاز آزمایشی ۶+۶، متن خام منبع و نام رکوردهای مردود نباید در HTML ظاهر شوند.
۵. شمارندهٔ کارت‌ها با **تجربه‌های قابل فهرست عمومی در صفحهٔ جزئیات** سازگار باشد؛ نمونه‌های `copyright_review=blocked`، `company_attribution_status=rejected`، `independence_status=duplicate` و URL غیر HTTP(S) نباید شمرده شوند.
۶. در نبود نقطهٔ تأییدشده، نقشه پیام خالی معتبر نشان دهد و هیچ درخواست MapLibre/Unpkg برای اسکریپت و استایل نقشه ارسال نشود. با یک نقطهٔ تأییدشده، نقشه و لینک کارت همان شرکت فعال شود. خطای API یا CDN باید فهرست شرکت‌ها را قابل استفاده نگه دارد.
۷. روی viewportهای ۳۲۰، ۳۹۰، ۷۶۸ و ۱۴۴۰ پیکسل، عدم اسکرول افقی، عملکرد صفحه‌بندی، ناوبری با Tab، حفظ فوکوس داخل drawer، بسته‌شدن با Escape، بازگشت فوکوس، کاهش حرکت و حالت عدم دسترسی نقشه را بازبینی کنید.
۸. هدرهای `Cache-Control: private, no-store`، `X-Robots-Tag: noindex`، `Referrer-Policy: no-referrer` و `Content-Security-Policy` را کنترل کنید؛ در frontend هیچ `CriteriaAnalysis` یا checkpoint خوانده نمی‌شود.

## ۳. دستورالعمل توقف و بازگشت

- در مشکل دسترسی یا اطلاعات ناصحیح، `JOBIEW_HOMEPAGE_PREVIEW_ENABLED=0` و سرویس **staging** را reload/restart کنید؛ `/` قبلی اساساً عوض نشده است.
- برای بازگردانی کد، commit شاخهٔ staging را به SHA تأییدشده قبلی برگردانید؛ تغییر اسکیمای دیتابیس نداریم. دادهٔ واقعی را بازگردانی نکنید مگر پس از آزمون restore مستقل.
- CI و staging را PASS ثبت کنید، اما تصمیم جایگزینی `/` را **صرفاً با تأیید صریح مالک و بررسی حقوق داده‌ها/کیفیت محتوا** بگیرید. نمره‌های `pilot_unverified` و رویدادهای بدون تأیید، public نیستند.

## ۴. وضعیت تا این مرحله

- CI GitHub SQLite + PostgreSQL synthetic: ارزیابی مجدد پس از هر commit ضروری است.
- محیط staging HTTPS واقعی: **انجام نشده** (آدرس/دسترسی به سرور در اختیار این عامل نیست).
- مرورگر واقعی staging با حساب staff: **انجام نشده**.
- deploy و تغییر صفحه عمومی: **انجام نشده**.