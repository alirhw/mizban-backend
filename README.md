# Miz Ban - بک‌اند میزبان

پلتفرم دوسویه رزرو بصری میز کافه و رستوران روی عکس‌های پانورامای ۳۶۰ درجه:
مشتری داخل عکس ۳۶۰ درجه می‌چرخد، میز را از روی پین انتخاب می‌کند و رزرو می‌کند؛
صاحب ونیو فضاها، میزها و اشتراکش را مدیریت می‌کند.
این مخزن فقط **بک‌اند** است (Django 5.2 + Django Ninja، معماری Modular Monolith).
فرانت‌اند Next.js فاز جداگانه بعدی است و این‌جا scaffold نشده است.

## نقشه پوشه‌ها

```
config/          تنظیمات (base/development/production)، API مرکزی نینجا، Celery، URLها
core/            ابزارهای مستقل از دامنه: خطاها و envelope استاندارد، تبدیل جلالی، صفحه‌بندی
apps/
  accounts/      کاربر سفارشی (ورود با موبایل + OTP)، نقش‌ها: CUSTOMER / VENUE_OWNER / ADMIN
  venues/        ونیوها، ساعت کاری، آیتم‌های طراحی، اشتراک
  panoramas/     فضاها، عکس‌های ۳۶۰ درجه، پین میزها (+ تسک Celery فشرده‌سازی)
  scheduling/    موتور تولید اسلات ۹۰ دقیقه + ۳۰ دقیقه فاصله (BR-001/BR-002)
  bookings/      رزرو، قفل ۱۰ دقیقه‌ای دیتابیس، ماشین وضعیت رزرو (+ managers)
  billing/       درگاه پرداخت، تراکنش‌ها، رسید دوقسمتی
  wallets/       کیف پول داخلی و دفتر تراکنش (برگشت وجه کنسلی فقط به کیف پول)
  reviews/       امتیاز و نظر بعد از اتمام رزرو
specs/           قالب Spec/Design/Tasks و اولین فیچر پرشده: 001-booking-lock
api/             اسنپ‌شات قرارداد OpenAPI (با check-contract.sh مقایسه می‌شود)
```

## قدم ۳ - راه‌اندازی قدم‌به‌قدم

### گزینه الف) لوکال با venv
```bash
python -m venv .venv
source .venv/bin/activate        # ویندوز: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

### گزینه ب) با Docker
```bash
cp .env.example .env
docker compose up --build
```

### بعد از بالا آمدن
- مستندات API: http://127.0.0.1:8000/api/v1/docs
- سلامت سرویس: http://127.0.0.1:8000/api/v1/healthz
- اجرای تست‌ها: `pytest -q`
- چک قرارداد API: `./check-contract.sh`

نکته توسعه: اگر `DATABASE_URL` ست نشده باشد، تنظیمات development به‌صورت
خودکار روی SQLite می‌افتد تا `check` و تست‌ها بدون سرویس اجرا شوند؛ ولی
**تست رقابت رزرو فقط روی PostgreSQL معتبر است** (SQLite قفل ردیفی ندارد).

## نکته‌های صادقانه این پک

- مدل کاربر سفارشی (`accounts.User` با شماره موبایل و نقش) ساخته و Migration
  اولیه‌اش گرفته شده، چون باید قبل از هر مدل دیگری وجود داشته باشد.
- بقیه مدل‌های دامنه (Venue، TablePin، Booking و ...) عمداً ساخته نشده‌اند؛
  آن‌ها تسک‌های T-005 به بعدِ سند معماری خودت هستند و هر کدام Spec جدا دارند.
- دو تست fail-first به‌صورت Skip در پک هست تا وقتی تسک‌هایشان برسد:
  تست رقابت دو رزرو هم‌زمان (`apps/bookings/tests/test_booking_race.py`،
  منتظر T-011/T-012) و تست قانون اسلات‌ها
  (`apps/scheduling/tests/test_slot_rules.py`، منتظر T-010).
- قانون‌های معماری ARCH-001 تا ARCH-006 و قوانین کسب‌وکار BR-001 تا BR-005
  در `AGENTS.md` آمده‌اند؛ قبل از هر کاری آن فایل را بخوان.
