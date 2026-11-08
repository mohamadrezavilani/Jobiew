# ابزار خزندهٔ شرکت‌ها داخل Jobiew

`TajrobeWiki_Marathon_v7.pyz` و کد خوانای متناظر آن داخل این پوشه نگهداری می‌شوند؛ حذف Downloads روی آنها اثری ندارد.

**دیتابیس و checkpoint خزنده منتقل نمی‌شوند.** رانر پروژه در فایل ریشه `Run_Company_Marathon.ps1`، به طور پیش‌فرض `../TestProject/tajrobewiki_crawler` را می‌یابد و از همان پیشرفت قبلی استفاده می‌کند. اگر مسیر متفاوت است `-CrawlerRoot` بدهید.

در ریشه پروژهٔ Jobiew در PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Run_Company_Marathon.ps1 -CheckOnly
# فقط با مجوز معتبر منبع و پس از بازبینی خروجی وضعیت
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Run_Company_Marathon.ps1 -Run -PermissionConfirmed
```

برای محل متفاوت: `-CrawlerRoot 'C:\PATH\tajrobewiki_crawler'`. برای پایتون متفاوت: `-PythonPath 'C:\PATH\python.exe'`.

خزنده دارای بررسی هش سخت‌گیرانهٔ `crawl_site.py` است. اگر آن را نپذیرفت، فایل را بازنویسی یا بررسی هش را حذف نکنید؛ نسخهٔ واقعی crawler را برای بررسی فراهم کنید.

نشانگر توقف بین دو پنجره: `reports/company_marathon_v7/continuous/pause.txt` در پوشهٔ runtime قدیمی. Ctrl+C پنجرهٔ اجرا را متوقف می‌کند. لاگ‌ها/دیتابیس خصوصی را به Git یا بستهٔ سورس اضافه نکنید.

برای انتشار بعدی:

```powershell
python .\scripts\release_windows.py --root .
```

خروجی جدید، فایل رانر و pyz را نیز همراه سورس بسته‌بندی می‌کند، اما **هیچ دیتابیس یا credential** را اضافه نمی‌کند.
