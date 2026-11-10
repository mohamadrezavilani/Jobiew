# Jobiew v2.0.21 — ورود مرحله‌ای checkpoint تجمعی GPT-6 به پایگاه‌دادهٔ **خصوصی**

این قابلیت تنها برای محیط توسعهٔ محلی Windows و PostgreSQL با `DJANGO_DEBUG=1` و دیتابیس دارای پسوند `_dev` طراحی شده است. **هیچ امتیازی منتشر، تأیید یا به کاربر عمومی نمایش داده نمی‌شود.** ابزار، اسکریپت‌های `build_v...py` و `manual_notes_*.py` داخل آرشیو را هرگز اجرا نمی‌کند؛ فقط دادهٔ JSON و هش تمام ۱۴۴ فایل را می‌سنجد.

## وضعیت بستهٔ دریافت‌شده در ۱۰ نوامبر ۲۰۲۶

- ZIP خصوصی: `jobiew_gpt6_private_checkpoint_001_2840.zip` — SHA256: `d0b8782a8acd4259a001ccbe4395a490bfbdf64f4107833e036c0e2ebbed44d3`
- SHA256 آرشیو منبع که در checkpoint اعلام شده: `164a31e46514ee958be67a6cf2f88f8ec9555baf80f45e7e0101592c34c482d0` — برای نوشتن **باید این SHA را مستقلاً با export واقعی منبع مطابقت دهید**.
- ۸٬۱۳۹ رکورد در دفترچه؛ ۲٬۲۴۰ پیش‌نویس ارزیابی (۱٬۰۹۲ کاری و ۱٬۱۴۸ مصاحبه)؛ ۶٬۶۹۶ نمرهٔ عددی، ۶٬۷۴۴ مورد فاقد شاهد و ۱۲۱ روایت دقیقاً تکراری.
- `source_rights=NOT_ESTABLISHED`, `publication=DISABLED`, `independent_semantic_accuracy_established=false`.

**تفاوت مهم:** ابزار قبلی v2.0.18 نیاز به فایل ZIP منبع و قالب ZIP پنج‌فایلی داشت. ابزار تازه ZIP تجمعی بزرگ با مجموعهٔ یادداشت‌ها، تاریخچه و manifest کامل را می‌پذیرد، ولی برای هر تجربه، هویت شرکت/نوع تجربه، هش محتوای منبع، هش روایت بازسازی‌شده و شاهد لفظی را با **دیتابیس واقعی توسعه** تطبیق می‌دهد. نسخهٔ خصوصی به دیتابیس واقعی یا staging این گفتگو وارد **نشده**؛ تست‌ها صرفاً روی داده‌های مصنوعی انجام شده‌اند.

## مراحل ایمن روی Windows dev

۱. قبل از نوشتن هر رکورد، از PostgreSQL توسعه بکاپ بگیرید، تست بازگردانی به دیتابیس جدا انجام دهید و تعداد تحلیل‌های قبلی را ثبت کنید. کاربری که فرمان را اجرا می‌کند باید اجازهٔ قانونی نگهداری/پردازش خصوصی این داده‌ها را داشته باشد. فایل checkpoint را بیرون از مخزن Git و `static/` نگه دارید.

۲. روی سیستم توسعهٔ PostgreSQL با نام واقعی دیتابیس، تنظیمات پروژه و v2.0.21:

```powershell
$env:DJANGO_DEBUG='1'
$env:WI_DB_ENGINE='postgresql'
$env:JOBIEW_DUAL6_PUBLICATION_ENABLED='0'
python backend/manage.py check
python backend/manage.py stage_cumulative_checkpoint_v221 `
  --checkpoint 'C:\SECURE\jobiew_gpt6_private_checkpoint_001_2840.zip' `
  --expected-db workplace_insights_dev `
  --expected-source-sha256 164a31e46514ee958be67a6cf2f88f8ec9555baf80f45e7e0101592c34c482d0 `
  --expected-checkpoint-sha256 d0b8782a8acd4259a001ccbe4395a490bfbdf64f4107833e036c0e2ebbed44d3 `
  --after-id 0 --limit 100
```

این **dry-run** است؛ هیچ چیزی ذخیره نمی‌شود. اگر `SOURCE_IDENTITY_OR_CONTENT_MISMATCH` یا `MODEL_EVIDENCE_NOT_VERBATIM` نشان داده شد، متوقف شوید؛ هش‌ها یا متن را برای عبور از کنترل تغییر ندهید.

۳. فقط پس از بررسی گزارش dry-run، بکاپ موفق، و اجازهٔ نگهداری خصوصی، **همان فرمان** را با دو گزینهٔ زیر اجرا کنید:

```powershell
  --apply --acknowledge-unverified-private-data
```

۴. برای ۱۰۰ مورد بعد، مقدار `--after-id` را برابر `last_candidate_id` خروجی قرار دهید و dry-run را مجدداً تکرار کنید. با تمام‌شدن آخرین مورد، `would_insert=0` و batch بعدی خالی خواهد شد. اجرای مجدد همان رکوردها نباید `inserted` تازه بسازد. ۴۰ run آزمایشی قبلی و وضعیت حقوقی انتشار هیچ‌گاه تغییر نمی‌کنند.

۵. برای checkpoint نهایی ۸٬۱۳۹ تجربه، **از ابتدا** دوباره همان روند را با دو SHA تازه و `--after-id 0` تکرار کنید؛ چون run_id به محتوا گره خورده است، رکوردهای بدون تغییر با وضعیت `existing` کنار گذاشته می‌شوند. هر اختلاف/تعارض نیازمند بازبینی دستی است و به‌صورت خودکار overwrite نمی‌شود.

## چرا هنوز نمی‌توان نمره‌ها را به عموم نشان داد؟

گزارش ساختاری سالم است، اما تعداد واقعی رکوردهای شرکت‌ها، حقوق منابع، انتساب شرکت، استقلال روایت‌ها و صحت نمره‌های هر محور هنوز بازبینی مستقل نشده‌اند. این ابزار *فقط* `pilot_unverified` و شش محور `unreviewed` می‌نویسد؛ از پایگاه‌دادهٔ development به‌صورت خودکار به production یا آدرس عمومی انتقال نمی‌دهد. فقط با گیت مجزای human review و تأیید حقوقی می‌توان نتایج منتخب را منتشر کرد.

## تست

```bash
(cd backend && python -m unittest criteria_v2.test_checkpoint_cumulative_v221 -v)
(cd backend && DJANGO_DEBUG=1 WI_DB_ENGINE=sqlite python manage.py test criteria_v2.test_checkpoint_cumulative_db_v221 --noinput)
```

هیچ تغییری در schema/migration و هیچ تماس مدل پولی یا API خارجی وجود ندارد. CI از دیتابیس‌های موقتی مصنوعی استفاده می‌کند.