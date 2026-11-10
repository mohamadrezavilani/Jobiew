# Jobiew v2.0.27 — تبدیل واقعی صفحات اجرایی ادمین از پنج معیار به ۶+۶

## مشکل گزارش‌شده در شیپور
بعد از ورود ۲٬۲۳۴ پیشنهاد GPT-6 و بازبینی خصوصی ۴۰ پروندهٔ شیپور، صفحهٔ «متن تجربه» زیر `/admin/companies/company/<id>/experiences/<experience-id>/` هنوز جدول `five_v1`، لینک «بررسی پنج معیار و انتشار AI» و «Claude پنج شاخص» را ارائه می‌کرد. این باعث می‌شد کاربر امتیازهای تاریخی را با مدل فعال اشتباه بگیرد.

## نتیجه
- صفحهٔ متن هر تجربه اکنون **فقط مدل GPT-6 ۶معیاری مختص نوع همان تجربه** را از `criteria_v2.CriteriaAnalysis` (engine `jobiew_gpt6_private_checkpoint_v218`) و `CriteriaAxisScore` می‌خواند. `work` از شش محور شرایط کاری و `interview` از شش محور مستقل مصاحبه استفاده می‌کند؛ امتیاز قدیمی `AiAssessment(five_v1)` به‌هیچ‌وجه وارد رابط جدید نمی‌شود.
- شش شاهد و توضیح فقط وقتی قابل نمایش‌اند که بازبین مجاز و HTTPS در محیط خصوصی تأیید شوند و اعتبار تحلیل در مقایسه با source hash و وضعیت receipt برقرار باشد. در صورت تغییر منبع/نمره، هیچ محور از تحلیل مشکوک نمایش داده نمی‌شود.
- اگر تجربه‌ای هنوز checkpoint ندارد (مثلاً ممکن است شناسهٔ ۷۴۸۳ چنین باشد؛ از خود شناسه نمی‌توان نتیجه گرفت)، صریحاً «هنوز تحلیل GPT-6 ثبت نشده» نمایش داده می‌شود؛ **هیچ تبدیل، میانگین‌گیری یا fallback به پنج معیار قدیمی انجام نمی‌شود**.
- لیست تجربه‌های هر شرکت، ستون وضعیت GPT-6 و لینک «متن و شش معیار» دارد. صفحات عمومی فقط لینک‌های **مدیرانِ دارای مجوز** به پنل جدید ۶+۶ را نشان می‌دهند، نه مقایسه/پیش‌نمایش پنج معیار. پرچم انتشار نمره همچنان از `criteria_v2.sufficiency_v208` با حقوق و source receipts محافظت می‌شود.
- امتیاز منبع از ۵ مربوط به **امتیاز ثبت‌شده در سایت مبدأ** بوده نه پنج معیار AI؛ در صفحهٔ مرور شش‌معیاری حذف شد ولی در دیتابیس تاریخی دست‌نخورده باقی ماند.
- جداول `assessments.AiAssessment`، `AiDimension` و migrationهای تاریخی و مسیرهای پژوهشی قدیمی به‌منظور یکپارچگی ارجاعات، گزارش و audit نگهداری می‌شوند اما **دیگر در مسیر عملیاتی جدید نمایش داده نمی‌شوند**. حذف فیزیکی این جداول یا تغییر migrationها یک کار مستقل، پرریسک و غیرضروری است.
- فقط ۲٬۲۳۴ تجربهٔ checkpoint در مقایسه با ۸٬۱۳۹ تجربهٔ منبع در مرحلهٔ قبلی وارد شده‌اند. تجربه‌هایی که GPT-6 ندارند خودکار امتیاز نخواهند گرفت و برای تحلیل نیازمند checkpointهای بعدی هستند.
- ۳۹ مانع منتشرنشدن نمره‌های شیپور در بررسی منبع (copyright/attribution/independence/classification) **هنوز مستقل و واقعی‌اند**. بازبینی شش محور و تأیید خود شرکت مجوز حقوقی برای بازنشر متن یا نمره ایجاد نمی‌کند. فرم صفحهٔ انتشار همچنان باید با مدارک واقعی تکمیل شود.

## استقرار
این نسخه به migration جدید، import مجدد checkpoint یا تغییر env انتشار احتیاج ندارد. ابتدا CI نسخهٔ مرج‌شده را بررسی کنید. سپس:
```bash
set -euo pipefail
sudo -u jobiew git -C /opt/jobiew fetch origin main
sudo -u jobiew git -C /opt/jobiew pull --ff-only origin main
sudo systemd-run --unit="jobiew-v227-check-$(date +%s)" --wait --pipe --collect \
 --uid=jobiew --property=EnvironmentFile=/etc/jobiew/jobiew.env \
 --working-directory=/opt/jobiew/backend /bin/bash -c \
 '/opt/jobiew/.venv/bin/python manage.py check && /opt/jobiew/.venv/bin/python manage.py makemigrations --check --dry-run && /opt/jobiew/.venv/bin/python manage.py collectstatic --noinput'
sudo systemctl restart jobiew-web
```
`WorkingDirectory` سرویس `jobiew-web` باید `/opt/jobiew/backend` باشد. بعد از به‌روزرسانی، صفحهٔ یک تجربهٔ شیپور را از `/admin/companies/company/<company-id>/experiences/<experience-id>/` ببینید. اگر آن تجربه در ZIP نبوده باشد، «هنوز تحلیل GPT-6 ثبت نشده» و نه جدول پنج معیار دیده می‌شود.

## تست‌ها
Django SQLite + PostgreSQL تست‌های رسمی معیارهای مجزای work/interview، عدم نمایش five_v1 حتی با وجود legacy DB record، دسترسی محدود به بازبین مجاز، نبود پیشنهاد، تغییر content hash، عدم دسترسی به تجربهٔ شرکت دیگر، و عدم نشت محتوا در سایت عمومی را اجرا می‌کند. هیچ دادهٔ خصوصی کاربر یا کلید سرویس وارد CI نمی‌شود.
