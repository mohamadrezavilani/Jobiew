# Jobiew v2.0.18 — پل ورود امن خروجی ایجنت امتیازدهی

## هدف و مرزبندی

این نسخه یک **پل جداگانه و خصوصی** برای checkpointهای تجمیعی خروجی ایجنت امتیازدهی فراهم می‌کند. مسیر Import پایلوت v2.0.12 مستقل می‌ماند. حالت پیش‌فرض فقط خواندنی است؛ هیچ امتیازی به‌طور خودکار تأیید یا منتشر نمی‌شود.

- فایل‌های ZIP تجربه‌ها و checkpoint فقط در پوشه خصوصی کاربر قرار می‌گیرند و هرگز نباید در Git یا سایت عمومی آپلود شوند.
- تطبیق `experience_id`، شناسهٔ شرکت، نوع تجربه، `source_content_sha256` و SHA256 متنِ آماده‌شده با PostgreSQL محلی الزامی است.
- قبل از هر write اعتبارسنجی کاملِ کل ZIP و تمام رکوردهای انتخاب‌شده انجام می‌شود. هر ردیف هنگام درج مجدداً با قفل دیتابیس کنترل می‌شود.
- اگر برای یک تجربه نسخهٔ دیگری از همین پل موجود باشد، برنامه متوقف می‌شود؛ هیچ overwriting یا اصلاح خاموش انجام نمی‌شود.
- تحلیل‌های قدیمی v2.0.12 حذف یا بازنویسی نمی‌شوند. خروجی جدید با موتور `jobiew_gpt6_private_checkpoint_v218` جدا می‌ماند.
- متن‌های تکراری علامت‌خورده در ledger برای درج جدید کنار گذاشته می‌شوند (در خود checkpoint باقی می‌مانند).
- نمره‌ها و شواهد فقط به‌عنوان `pilot_unverified`/`unreviewed` نگهداری می‌شوند و جزو امتیاز عمومی نیستند.
- کنترل امتیازهای جدید با همان `validate_response` موتور اصلی انجام می‌شود، از جمله quote عینی، عدم نمره‌دهی در صورت نبود شاهد و شش محور درست.
- انتشار، حق بازاستفاده از منبع و تأیید انسانی هرگز از روی checkpoint یا این فرمان استنباط نمی‌شوند.

## اجرای مطالعه و پیش‌نمایش بدون تغییر دیتابیس

در PowerShell ریشهٔ پروژه روی ویندوز، بعد از نصب نسخه و قرار دادن فایل‌های خصوصی در محل امن:

```powershell
$env:DJANGO_DEBUG='1'
$env:DJANGO_SETTINGS_MODULE='workplace_insights.settings'
$env:WI_DB_ENGINE='postgresql'
$env:PYTHONPATH="$($PWD.Path)\backend"
$env:JOBIEW_DUAL6_PUBLICATION_ENABLED='0'

$source="$env:USERPROFILE\jobiew-private\chatgpt-review\jobiew_dual6_all_stories.zip"
$checkpoint="$env:USERPROFILE\jobiew-private\chatgpt-review\jobiew_gpt6_private_checkpoint_FINAL.zip"
python backend/manage.py stage_dual6_checkpoint_v218 `
  --expected-db workplace_insights_dev --source $source `
  --checkpoint $checkpoint --limit 100
```

چون فایل نهایی ایجنت هنوز دریافت نشده، نام فایل checkpoint در دستور بالا **نمونه** است. مسیر واقعی فایل تحویلی را بدهید. اگر checkpoint هنوز ناقص باشد، می‌توان پیش‌نمایش ساختاری روی آن داشت، ولی به معنی اتمام ارزیابی نیست.

## درج خصوصی (فقط بعد از تأیید خروجی و backup دیتابیس توسعه)

افزودن `--apply --acknowledge-unverified-private-data` داده را در دیتابیس `workplace_insights_dev` **می‌نویسد**. درج به‌صورت batch تا سقف ۵۰۰ رکورد انجام می‌شود؛ `--limit` و `--after-id` امکان ادامه می‌دهند. تنها پس از گزارش موفق حالت DRY_RUN و داشتن backup انجام شود. اجرای دوباره با همان مدل و متن هزینه یا درج تکراری ندارد. هیچ درخواست AI انجام نمی‌شود.

بازبینی نتایج درج‌شده با دسترسی superuser/staff مجاز، `DJANGO_DEBUG=1`، `JOBIEW_PRIVATE_PILOT_DASHBOARD_ENABLED=1` و `JOBIEW_DUAL6_PUBLICATION_ENABLED=0`، از نشانی:

`http://127.0.0.1:8000/internal/criteria/checkpoint/`

در این صفحه شرکت‌ها و دو دستهٔ شش‌معیاری از هم جدا هستند. جزئیات پرونده‌ها نیز staff-only هستند. `null` صفر محسوب نمی‌شود.

## آزمون‌ها و محدودیت‌های باقی‌مانده

- تست مستقل pure Python: ۹ تست (در محیط ساخت بسته اجرا شده).
- بررسی کامل QA روی checkpoint شناسه‌های ۱ تا ۶۴۰: PASS (۵۵۵ خروجی، ۱۶۶۶ نمرهٔ عددی)؛ این **سنجش مستقل کیفیت معنایی نیست**.
- تست‌های یکپارچه Django (DB/testclient) هنگام نصب روی ویندوز اجرا می‌شوند؛ در محیط توسعهٔ بسته Django نصب نبود.
- هنوز خروجی نهایی ایجنت دوم دریافت نشده و PostgreSQL محلی/Production در دسترس این بسته نبوده است.
- این نسخه صفحهٔ عمومی یا استقرار Ubuntu را تغییر نمی‌دهد. پس از تأیید کاربر و اثبات حق استفاده/اعتبار داده‌ها، مسیر انتشار جداگانه بررسی می‌شود.

## اصلاحات سخت‌سازی بستهٔ بازبینی‌شده (۹ نوامبر ۲۰۲۶)

این نسخهٔ اصلاح‌شده با کاندید اولیه متفاوت است. کنترل‌های اضافه‌شده:

1. همهٔ اعضای ZIP، فایل‌های هش و یکتا بودن نام‌ها کنترل می‌شوند؛ ZIP ناشناس، عضو اضافی، checksum ناقص، JSON دارای کلید تکراری و ادعای تکراری بودن بدون تطبیق SHA رد می‌شوند. اندازهٔ آرشیو و شمار اعضا قبل از خواندن محتوای فشرده محدود است.
2. اجرای مجدد فقط اگر شش نمره/شاهد/توضیح **عیناً** با رکورد موجود مطابق باشند idempotent است. تغییر source، شرکت، نوع، مدل/نسخه، تصمیم، یا امتیاز conflict است؛ رکورد قدیمی v212 حذف یا بازنویسی نمی‌شود.
3. برای حالت `--apply` دو پرچم `--expected-source-sha256` و `--expected-checkpoint-sha256` **اجباری** است. آن‌ها را از کانال معتبر مستقل (نه صرفاً از محتوای ZIP) بررسی و وارد کنید. بدون آن‌ها فقط dry-run مجاز است.
4. نمایش خصوصی در محیط محلی DEBUG به رفتار قبلی متکی است؛ مسیر جدید staging با DEBUG=False به احراز هویت staff، HTTPS، دامنهٔ اختصاصی و دو پرچم اختصاصی نیاز دارد. هیچ تغییر عمومی در شرکت‌ها انجام نمی‌شود.
5. ابزار نمونه‌گیری کور و قطعی `criteria_v2.checkpoint_sampling_v218` ایجاد شد تا محورهای دارای عدد و `null` مستقل نمونه‌برداری شوند. این نمونه‌برداری اعتبار معنایی را اثبات نمی‌کند.
6. صفحهٔ شرکت، لینک جزئیات حداکثر ۱۰۰ تجربهٔ یکتا را نشان می‌دهد؛ نمایش متن همچنان فقط به بازبین دارای دسترسی مجاز محدود است.

### نمونهٔ Apply پس از دریافت ZIP واقعی و احراز حق نگهداری خصوصی

```powershell
# نمونه؛ نام ZIPها و مقدار SHAها باید از خروجی بررسی‌شدهٔ همان فایل واقعی گرفته شوند.
python backend/manage.py stage_dual6_checkpoint_v218 `
  --expected-db workplace_insights_dev `
  --source "$env:USERPROFILE\jobiew-private\chatgpt-review\jobiew_dual6_all_stories.zip" `
  --checkpoint "$env:USERPROFILE\jobiew-private\chatgpt-review\FINAL_CHECKPOINT.zip" `
  --expected-source-sha256 <64-hex-reviewed-source-sha> `
  --expected-checkpoint-sha256 <64-hex-reviewed-checkpoint-sha> `
  --limit 100 --apply --acknowledge-unverified-private-data
```

`FINAL_CHECKPOINT.zip` و هش‌های زاویه‌دار placeholder هستند. این فرمان در محیط فعلی اجرا نشده است. قبل از Apply: از PostgreSQL توسعه بکاپ بگیرید و restore آن را روی دیتابیس دورریختنی امتحان کنید؛ انطباق حقوق پردازش داخلی را مستقل بررسی کنید. ورود خصوصی، تأیید معنایی یا موافقت بازنشر نیست.

### پیش‌نمایش staging با DEBUG=False (فقط روی میزبان خصوصی HTTPS)

پیش‌نمایش همچنان در مسیر `/internal/criteria/checkpoint/` است، اما حالت staging از داشبورد قدیمی جدا می‌شود. پیکربندی نمونه:

```env
DJANGO_DEBUG=0
JOBIEW_DUAL6_PUBLICATION_ENABLED=0
JOBIEW_CHECKPOINT_STAGING_ENABLED=1
JOBIEW_CHECKPOINT_STAGING_HOST=private-staging.example.invalid
```

`private-staging.example.invalid` نمونه است؛ باید با نام میزبان واقعی و غیرعمومی جایگزین شود و در `DJANGO_ALLOWED_HOSTS` قرار گیرد. reverse proxy باید HTTPS با گواهی معتبر و headerهای proxy امن داشته باشد، ترجیحاً با کنترل دسترسی شبکه‌ای/VPN. حساب بازبین باید `is_staff` و سه Permission مربوط به مشاهدهٔ تجربه/تحلیل/محور را داشته باشد. اگر پرچم staging فعال نباشد یا host/HTTPS نخواند، مسیر بسته است؛ **هیچ‌گاه این پرچم را روی میزبان عمومی Production فعال نکنید.**

### نمونه‌گیری برای QA معنایی مستقل

```powershell
$env:PYTHONPATH="$($PWD.Path)\backend"
python -m criteria_v2.checkpoint_sampling_v218 `
  --source "PRIVATE_SOURCE.zip" --checkpoint "PRIVATE_CHECKPOINT.zip" `
  --out-dir "$env:USERPROFILE\jobiew-private\semantic-qa" --per-stratum 5
```

خروجی فقط شناسهٔ تجربه، نوع و کلید محور را به داور کور می‌دهد؛ پیشنهاد نمره را نمایش نمی‌دهد. بازبین باید مستقل از خروجی GPT-6 متنِ مجاز را بخواند و وجود/ارتباط شاهد، علامت عدد یا null و تعادل موارد مثبت/منفی را قضاوت کند. سپس با پیشنهادهای ذخیره‌شده مقایسه و خطاها را در سطح محور گزارش کند. **نمونهٔ کوچک برای سنجش خطای آماری در کل ۸۱۳۹ تجربه کافی نیست**؛ طرح نمونه و حجم آن باید قبل از تصمیم انتشار نهایی شود.

### محدودیت تأییدشده

پکیج در این نوبت فقط تست مستقل Python و کامپایل Python را گذرانده است. تست Django در GitHub/Windows، PostgreSQL واقعی، race واقعی و استقرار HTTPS هنوز اجرا نشده‌اند. خطا در هر ردیف import، transaction همان ردیف را برمی‌گرداند اما ردیف‌های قبلی batch ممکن است درج شده باشند؛ rollback کل batch ادعا نمی‌شود. با اجرای دوباره می‌توان پس از ممیزی دقیق ادامه داد.
