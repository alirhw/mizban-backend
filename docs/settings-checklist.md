# چک‌لیست تنظیمات اولیه - میزبان (Miz Ban)

این چک‌لیست را یک بار، قبل از اولین Feature، کامل کن.

## متغیرهای محیطی (`.env`)
- [ ] فایل `.env` از روی `.env.example` ساخته شده و در `.gitignore` هست؛ هرگز Commit نمی‌شود و ایجنت‌ها هرگز نمی‌خوانندش.
- [ ] `SECRET_KEY` مقدار واقعی و تصادفی دارد (در محیط production بدون آن سرور اصلاً بالا نمی‌آید - عمدی است).
- [ ] `DATABASE_URL` به PostgreSQL اشاره می‌کند (SQLite فقط برای اجرای بدون سرویس در توسعه است؛ تست رقابت رزرو فقط روی PostgreSQL معتبر است).
- [ ] `REDIS_URL` و `CACHE_URL` درست‌اند؛ Redis فقط برای OTP و متادیتای ونیو است - وضعیت اسلات‌ها هرگز کش نمی‌شود.
- [ ] کلیدهای واقعی پیامک (`SMS_API_KEY`) و درگاه پرداخت فقط در `.env` هستند؛ در توسعه فقط کلیدهای تست درگاه.

## سرویس‌ها
- [ ] یا با Docker: `docker compose up --build` و هر سه سرویس (db, redis, web) سالم‌اند؛ یا لوکال: PostgreSQL و Redis در حال اجرا هستند.
- [ ] `python manage.py migrate` بدون خطا اجرا شده (اولین Migration مدل کاربر accounts ساخته شده است).
- [ ] `GET http://127.0.0.1:8000/api/v1/healthz` پاسخ `{"status": "ok", "db": true, "redis": true}` می‌دهد.
- [ ] مستندات API در `http://127.0.0.1:8000/api/v1/docs` باز می‌شود.

## کیفیت پایه
- [ ] `python manage.py check` بدون خطا.
- [ ] `pytest -q` سبز است (دو تست fail-first رزرو و اسلات عمداً Skip هستند تا تسک‌های T-010 تا T-012 انجام شوند).
- [ ] `./check-contract.sh` یک بار اجرا شده و `api/openapi.snapshot.json` ساخته و Commit شده است.

## امنیت و پول
- [ ] هیچ کلید واقعی (پیامک، درگاه، Sentry) داخل گیت نیست؛ فقط placeholder در `.env.example`.
- [ ] Migrationهای اپ‌های `bookings` و `wallets` قبل از اعمال روی هر محیط مشترک، بازبینی انسانی می‌خواهند.
- [ ] مبالغ همه‌جا تومانِ صحیح (integer) هستند؛ float برای پول ممنوع.
