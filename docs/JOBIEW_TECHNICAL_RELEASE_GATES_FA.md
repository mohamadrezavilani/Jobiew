# مسیر پذیرش، QA و انتشار امن Jobiew ۶+۶

نسخه: کاندید اصلاحی v2.0.18؛ همهٔ وضعیت‌ها برای ۹ نوامبر ۲۰۲۶ و به‌جز آنچه «PASS» ذکر شده، نیازمند آزمون محیط واقعی‌اند.

## مرزهای غیرقابل‌ادغام

- `source_rights`: مستندکردن حق کپی، پردازش، ذخیرهٔ داخلی و بازنشر، چهار موضوع مجزا.
- `source_identity`: شرکت تأییدشده، نوع تجربهٔ تأییدشده، وضعیت استقلال/duplicate و SHA فعلی.
- `technical_stage`: ثبت خصوصی `pilot_unverified` از checkpoint و شش نمره `unreviewed`؛ نه review و نه publication.
- `semantic_quality`: مجموعهٔ کنترل مستقل برای هر محور، blind review، خطا و پرچم موارد مردود/بدون شاهد.
- `publication`: مسیر promotion مجزا، append-only review event، پرچم public کنترل‌شده، بکاپ و تأیید مالک.

هیچ‌یک از این مرزها از تأیید مرحلهٔ دیگر استنباط نمی‌شود. ۴۰ run v212 پاک نمی‌شوند. الگوریتم انتخاب run باید موتور/زمان/سلامت/تکرار را با قاعدهٔ صریح تعیین کند؛ import تازه از v218 به‌تنهایی اولویت public ایجاد نمی‌کند.

## ماتریس تست

| سناریو | انتظار | وضعیت این بسته |
| --- | --- | --- |
| ساختار ZIP، SHA، quote، null، missing/extra files، JSON تکراری | reject یا PASS قابل بازتولید | PASS - تست synthetic pure |
| conflict run، تغییر score پس از stage، تفاوت kind/company، عدم تکرار پیشنهاد | fail-closed | بخش pure PASS؛ DB اجرا نشده |
| حفظ ۴۰ پایلوت و بدون overwrite | قفل منطقی و دو engine مستقل | کد دارد؛ Django real pending |
| staff permission، HTTPS hostname، DEBUG=False و publication flag | فقط staging امن | کد و testclient تعریف شده؛ pending |
| کفایت مستقل ۰، ۱–۵، ۶+، null بدون صفر | صحیح برای هر نوع/محور | کد پایهٔ v216؛ regression pending |
| PostgreSQL واقعی + import مجدد + هم‌زمانی + rollback ردیف | عدم اعوجاج | pending |
| گواهی HTTPS/Nginx، Gunicorn، static، صفحهٔ عمومی بدون نشت | PASS | pending |
| مرجع مستقل semantic/حقوق منبع | documented release gates | NOT ESTABLISHED |
| backup و آزمون restore | restore موفق روی دیتابیس جدا | pending |

## برنامهٔ staging قابل‌مشاهده برای مالک

1. شاخهٔ candidate را روی کپی مخزن تمیز نصب و تست کنید؛ در صورت عدم PASS هیچ Merge نکنید.
2. قبل از هر write، digestهای منبع و checkpoint نهایی، ledger و گزارش QA را بدون خروج متن در لاگ بررسی کنید.
3. پس از تعیین حق نگهداری/پردازش و آزمایش restore بکاپ توسعه، فقط روی PostgreSQL توسعه با پین SHAها و حد ۱۰۰ رکورد import کنید؛ سپس گزارشِ تعداد قبلی/جدید و آزمون بدون تغییر public را ذخیره کنید.
4. یک میزبان اختصاصی non-public staging پشت HTTPS/VPN با `DEBUG=0` و staff permissions آماده کنید. فقط دادهٔ مجاز منتقل شود. مسیر `/internal/criteria/checkpoint/`، صفحهٔ شرکت و جزییات شش محور را بررسی کنید.
5. حالات بدون خروجی، کار-only، مصاحبه-only، mixed، شش-null، duplicate، stale، blocked، ابزار دسترسی غیرstaff و POST تست شوند.
6. یافته‌ها، خطاهای معنایی و حقوقی را قبل از تصمیم «قابل‌انتشار» در گزارش جداگانه ثبت کنید؛ تأیید صفحه از طرف مالک به‌تنهایی اثبات مجوز داده‌ها نیست.

## انتشار Ubuntu — فقط پس از تأیید صریح مالک و رفع Gateها

- ثبت SHA commit و tag، migration plan، `env` diff، مکانیزم rollback، و نسخهٔ نصب‌شدهٔ فعلی؛ Production را صرفاً `v2.0.16 main` فرض نکنید.
- روی Ubuntu از PostgreSQL (`pg_dump --format=custom`) و فایل‌های لازم بکاپ نسخه‌دارِ کنترل‌شده بگیرید؛ **restore روی دیتابیس موقت** و آزمون شمارش/کلیدها الزامی است.
- `DJANGO_DEBUG=0`، staging flag صفر، `JOBIEW_DUAL6_PUBLICATION_ENABLED=0` تا release gate؛ مدل پولی و مدل محلی نصب/فعال نمی‌شود.
- migration روی staging، `manage.py check --deploy`، `makemigrations --check`، تست regressions، بررسی symlink/static، HTTPS، سرویس systemd، Nginx، healthcheck و سطح دسترسی log/backup.
- با تأیید انتشار، deployment transaction-like عملیاتی: وضعیت فعلی ثبت، توقف writeهای حساس، migration سازگار/قابل بازگشت، deploy با release directory، تست smoke، باز کردن ترافیک و مانیتورینگ پس از انتشار.
- rollback کد به release قبلی و در صورت migration نامتوافق، restore بکاپ با طرح قطع/وصل writeها؛ تا قبل از restore از جلوگیری از حذف داده‌های جدید اطمینان حاصل شود.
- هیچ متن منبع، checkpoint یا dump خصوصی وارد Git/static/public media/CI artifact عمومی نشود.

**مسدودکننده‌های فعلی:** checkpoint نهایی، دسترسی به PostgreSQL توسعه، آزمون نصب روی Windows/Django، staging واقعی HTTPS، تأیید مالک، مجوز حقوقی و داوری معنایی مستقل. طراحی صفحهٔ اول خارج از فاز است.
