#!/usr/bin/env python3
"""Миграция БД под фичи монетизации/удержания (#17 напоминания, #11 рефералка).

Добавляет в таблицу users новые колонки через ALTER TABLE ADD COLUMN
(поддерживается всеми версиями SQLite). Идемпотентно: повторный запуск
безопасен (каждая колонка добавляется только если её ещё нет).

Новые ТАБЛИЦЫ (payments, promo_codes, promo_redemptions) создаёт сам бот в
init_db() при старте — здесь они не нужны.

Запускать с ОСТАНОВЛЕННЫМ ботом из корня проекта:
    python migrate_features.py
"""
import os
import sys
import shutil
import sqlite3

DB = os.path.join(os.path.dirname(__file__), "users.db")
DB = os.path.abspath(DB)

# колонка -> SQL-определение для ADD COLUMN
NEW_COLUMNS = {
    "notify_stage": "INTEGER DEFAULT 0",            # #17: 0/1/2/3 стадии напоминаний
    "referred_by": "INTEGER",                       # #11: telegram_id пригласившего
    "referral_bonus_granted": "BOOLEAN DEFAULT 0",  # #11: бонус за первую оплату выдан
}


def main():
    if not os.path.exists(DB):
        print(f"🛑 Не найдена БД: {DB}")
        sys.exit(1)

    bak = DB + ".bak_features"
    shutil.copy2(DB, bak)
    print(f"✅ Бэкап: {bak}")

    con = sqlite3.connect(DB)
    cur = con.cursor()

    existing = {r[1] for r in cur.execute("PRAGMA table_info(users)").fetchall()}

    for col, ddl in NEW_COLUMNS.items():
        if col in existing:
            print(f"ℹ️  Колонка users.{col} уже есть — пропускаю")
            continue
        cur.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
        print(f"✅ Добавлена колонка users.{col} ({ddl})")

    # Бэкфилл notify_stage из старого флага notified (если он есть):
    # кто уже получал предупреждение за 24ч → стадия 2, чтобы не слать повторно.
    if "notified" in existing and "notify_stage" not in existing:
        cur.execute("UPDATE users SET notify_stage = CASE WHEN notified THEN 2 ELSE 0 END")
        print(f"✅ Бэкфилл notify_stage из notified для {cur.rowcount} строк")

    con.commit()
    con.close()
    print("✅ Готово. Если что-то не так — восстанови из бэкапа:")
    print(f"   cp {bak} {DB}")


if __name__ == "__main__":
    main()
