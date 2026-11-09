# Jobiew v2.0.12 — اتصال امن پایلوت ۴۰تایی به دیتابیس توسعه

## دلیل

۴۰ روایت به‌صورت نمونه‌گیری خصوصی انتخاب شده و دستیار ChatGPT آن‌ها را از نظر ۶+۶ ارزیابی کرده است. خروجی صرفاً **پیشنهاد امتیاز** است؛ معادل مرجع انسانی مستقل یا تأیید کیفیت مدل نیست.

همهٔ تجربه‌های دیتابیس توسعه در مرحلهٔ قبلی `copyright_review=pending` و `company_attribution_status=unverified` بودند. این مرحله وضعیت آن‌ها را تغییر نمی‌دهد و انتشار عمومی ایجاد نمی‌کند.

## فرایند

فرمان `import_dual6_pilot_v212` به چهار دلیل محافظه‌کارانه طراحی شده است:

1. برای هر `case_id` نگاشت خصوصی `source_experience_id` را الزام می‌کند؛ داستان `stories.json` را با متن تولیدشده از رکورد کنونی Django، **عیناً** مقایسه می‌کند. هیچ نگاشت حدسی به شرکت نداریم.
2. خروجی AI را بر اساس اعتبارسنجی سختگیرانه موتور v207 بررسی می‌کند. شش معیار اجباری؛ شاهد مستقیم و `null` واقعی.
3. فقط روی Windows و PostgreSQL توسعهٔ مشخص با نام پایان‌یافته به `_dev`، با `DEBUG=1` و `JOBIEW_DUAL6_PUBLICATION_ENABLED=0` اجرا می‌شود. این حفاظت جای بررسی تنظیمات تونل دیتابیس توسط توسعه‌دهنده را نمی‌گیرد.
4. فرمان پیش‌فرض کاملاً خواندنی است. فقط `--apply --acknowledge-unapproved-private-pilot` رکوردهای جدید `CriteriaAnalysis` و شش `CriteriaAxisScore` مربوط را به‌صورت اتمیک اضافه می‌کند؛ همه `pilot_unverified`/`unreviewed` هستند و در نمای عمومی یا صف تأیید انسانی v209 قرار نمی‌گیرند. در تکرار اجرا رکورد قبلی دوباره درج نمی‌شود.

**هیچ** `CriteriaReviewEvent`، `CriteriaScoreReviewEvent`، مجوز حقوقی، تأیید AI یا امتیاز منتشرشده ایجاد نمی‌شود. Migration ندارد؛ از ساختار موجود استفاده می‌کند. فقط منشأ و هش‌ها در `raw_payload` قرار می‌گیرند، نه متن کامل. نقل‌قول‌های شواهد در جدول خصوصی معیارها ذخیره می‌شوند.

## اجرای ویندوز بعد از نصب بسته

فایل‌های خصوصی `stories.json` و `mapping_private.json` باید در `C:\Users\Administrator\jobiew-private\pilot-v211` موجود باشند. فایل ZIP نتایج قبلی را از Downloads داخل پوشهٔ خصوصی Extract کنید:

```powershell
$pilot=Join-Path $env:USERPROFILE 'jobiew-private\pilot-v211'
Expand-Archive -LiteralPath (Join-Path $env:USERPROFILE 'Downloads\jobiew_40_scored_pilot_v211_bundle.zip') -DestinationPath (Join-Path $pilot 'assistant_private') -Force
$env:DJANGO_SETTINGS_MODULE='workplace_insights.settings'
$env:DJANGO_DEBUG='1'
$env:WI_DB_ENGINE='postgresql'
$env:PYTHONPATH="$($PWD.Path)\backend"
$env:JOBIEW_DUAL6_PUBLICATION_ENABLED='0'
python backend/manage.py import_dual6_pilot_v212 --stories "$pilot\stories.json" --mapping "$pilot\mapping_private.json" --predictions "$pilot\assistant_private\jobiew_predictions_assistant_v211.json" --expected-db workplace_insights_dev
```

برای ثبت اختیاریِ پیشنهادها در همان دیتابیس **توسعه** پس از پیش‌نمایش، همان فرمان را با دو سوییچ انتهایی زیر تکرار کنید:

```text
--apply --acknowledge-unapproved-private-pilot
```

توصیه می‌شود پیش از هر درج، نام دیتابیس، وجود هرگونه SSH tunnel روی `127.0.0.1` و وضعیت نسخهٔ داده بررسی شود. این راهنما مجوز استفاده از دادهٔ دارای وضعیت `pending` نیست و تأیید منبع باید مستقل انجام شود.

## پذیرش

- ۱۲ تست مستقل آفلاین + ۴ تست Django با DB آزمایشی.
- تست‌های رگرسیون v209، v208 و v211؛ `manage.py check`، `makemigrations --check`.
- هرگز فایل خصوصی داستان‌ها، نگاشت یا خروجی شواهد را به GitHub اضافه نکنید.
- مدل به هیچ API خارجی متصل نمی‌شود، هیچ فرآیند پرداخت یا کرالر اجرا نمی‌شود، Production بدون تغییر است.
