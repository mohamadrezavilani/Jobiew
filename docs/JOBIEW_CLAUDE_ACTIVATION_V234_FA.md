# Jobiew v2.0.34 — فعال‌سازی Claude شش‌معیاری روی سرور

این نسخه ابزار تنظیم سرور را به قابلیت موجود v2.0.33 اضافه می‌کند. قابلیت مقایسهٔ خصوصی GPT-6 و Claude، صفحهٔ نمایش نتیجه و migration مربوط در نسخهٔ قبل وجود دارند. هیچ کلید API، هزینه یا نتیجهٔ ارزیابی در Git ذخیره نمی‌شود. انتشار در GitHub به‌تنهایی تنظیمات سرور را تغییر نمی‌دهد.

## آماده‌سازی

۱. اگر یک کلید Anthropic در گفتگو یا جای عمومی نوشته شده، آن را در https://platform.claude.com/settings/keys لغو و کلید تازه بسازید. کلید جدید را در گفتگو، خط فرمان یا GitHub ننویسید.
۲. از PostgreSQL و فایل /etc/jobiew/jobiew.env بکاپ داشته باشید. پیش از هر اجرا، به یاد داشته باشید متن تجربه به Anthropic ارسال می‌شود و ممکن است شامل اطلاعات شناسایی‌کننده باقی‌مانده باشد؛ فقط با تأیید آگاهانهٔ مدیر اجرا کنید.
۳. آخرین نسخه را روی سروری که سرویس jobiew-web دارد دریافت کنید. اگر وضعیت Git تغییرات محلی نشان داد، پیش از Pull آن‌ها را بررسی کنید.

~~~bash
sudo -u jobiew git -C /opt/jobiew status --short
sudo -u jobiew git -C /opt/jobiew pull --ff-only origin main
sudo systemd-run --unit="jobiew-claude-check-$(date +%s)" --wait --pipe --collect \
  --uid=jobiew --property=EnvironmentFile=/etc/jobiew/jobiew.env \
  --working-directory=/opt/jobiew/backend /bin/bash -e -c \
  '/opt/jobiew/.venv/bin/python manage.py check && /opt/jobiew/.venv/bin/python manage.py migrate --noinput && /opt/jobiew/.venv/bin/python manage.py collectstatic --noinput'
~~~

## فعال‌سازی تعاملی

~~~bash
sudo python3 /opt/jobiew/scripts/enable_claude_six_v234.py --limit 20
~~~

ابزار کلید تازه را در ورودی مخفی درخواست می‌کند؛ آن را فقط همان‌جا Paste کنید. عدد ۲۰ سقف کل درخواست‌های ثبت‌شده در دیتابیس است؛ تعداد اجراهای موفق و ناموفق در همهٔ شرکت‌ها. این سقف روزانه نیست و بین ۱ تا ۱۰۰ قابل تنظیم است. مدل پیش‌فرض claude-sonnet-5-5 است.

ابزار تنظیمات ANTHROPIC_API_KEY، JOBIEW_CLAUDE_SIX_ENABLED=1، JOBIEW_CLAUDE_SIX_LIMIT=20 و JOBIEW_CLAUDE_SIX_MODEL=claude-sonnet-5-5 را فقط در /etc/jobiew/jobiew.env می‌نویسد؛ از فایل قبلی بکاپ root-only با دسترسی 0600 در همان پوشه می‌گیرد و فایل جدید را با دسترسی 0640 حفظ می‌کند. کلید را چاپ نمی‌کند و هیچ درخواست هزینه‌داری نمی‌فرستد.

بعد از آن:

~~~bash
sudo systemctl restart jobiew-web
sudo systemctl is-active jobiew-web
sudo python3 /opt/jobiew/scripts/enable_claude_six_v234.py --status
~~~

خروجی وضعیت باید enabled: 1، limit: 20، model: claude-sonnet-5-5 و key_present: yes باشد. وجود کلید به‌معنای معتبر بودن یا داشتن اعتبار مالی در حساب نیست. اگر سرویس بالا نیامد، خروجی sudo journalctl -u jobiew-web -n 80 --no-pager را بررسی کنید؛ فایل env را نفرستید.

## مسیر کار در ادمین

https://jobiew.ir/admin/ → میز کار شرکت‌ها → تجربه‌ها → «بررسی اختیاری با Claude».

اجرای پولی برای هر تحلیل خصوصی و معتبر شش‌معیاری GPT-6، با دسترسی criteria_v2.add_criteriaclaudecomparison و یک تأیید صریح در فرم (ارسال متن به Anthropic و هزینهٔ احتمالی) مجاز است. تأیید حقوق انتشار عمومی یا ثبت رویداد حقوق منبع پیش‌شرط مقایسهٔ خصوصی Claude نیست. این مقایسه هیچ مجوز انتشار یا تصمیم انسانی ایجاد نمی‌کند. برای هر تحلیل یک درخواست مجاز است، اجرای ناموفق به‌صورت خودکار تکرار نمی‌شود، و نمره‌های GPT-6 و وضعیت انتشار تغییر نمی‌کنند.

## محدودهٔ انتشار

این نسخه کد، تست و راهنمای فعال‌سازی را در GitHub منتشر می‌کند. بدون دسترسی اجرایی به خود سرور، گذاشتن کلید در EnvironmentFile و Restart سرویس ممکن نیست. صحت کلید تازه، موجودی حساب و اتصال API فقط با اجرای واقعی روی سرور مشخص می‌شود.
