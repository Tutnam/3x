#!/usr/bin/env python3
"""Разовая чистка users.db после перехода на panel-authoritative логику.

Делает:
  1. Бэкап users.db -> users.db.bak_cleanup
  2. DROP COLUMN vless_profile_id (рудимент старой логики; не используется в коде)
  3. Удаляет мусорный флаг "disabled" из JSON vless_profile_data у всех юзеров

Запускать с ОСТАНОВЛЕННЫМ ботом. Идемпотентно: повторный запуск безопасен.
"""
import sqlite3
import json
import shutil
import sys
import os

DB = os.path.join(os.path.dirname(__file__), "..", "users.db")
DB = os.path.abspath(DB)


def main():
    if not os.path.exists(DB):
        print(f"🛑 Не найдена БД: {DB}")
        sys.exit(1)

    # 1. Бэкап
    bak = DB + ".bak_cleanup"
    shutil.copy2(DB, bak)
    print(f"✅ Бэкап: {bak}")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # 2. DROP COLUMN vless_profile_id (если есть и если SQLite >= 3.35)
    cols = [r["name"] for r in cur.execute("PRAGMA table_info(users)").fetchall()]
    if "vless_profile_id" in cols:
        ver = tuple(int(x) for x in sqlite3.sqlite_version.split("."))
        if ver >= (3, 35, 0):
            cur.execute("ALTER TABLE users DROP COLUMN vless_profile_id")
            print("✅ Удалён столбец users.vless_profile_id")
        else:
            print(f"⚠️ SQLite {sqlite3.sqlite_version} < 3.35 — DROP COLUMN не поддерживается.")
            print("   Столбец оставлен в БД (в модели его уже нет, он игнорируется).")
    else:
        print("ℹ️ Столбца vless_profile_id уже нет — пропускаю.")

    # 3. Чистка флага "disabled" в JSON vless_profile_data
    rows = cur.execute(
        "SELECT id, vless_profile_data FROM users WHERE vless_profile_data IS NOT NULL"
    ).fetchall()
    cleaned = 0
    for r in rows:
        try:
            d = json.loads(r["vless_profile_data"])
        except Exception:
            continue
        if isinstance(d, dict) and "disabled" in d:
            d.pop("disabled", None)
            cur.execute(
                "UPDATE users SET vless_profile_data=? WHERE id=?",
                (json.dumps(d), r["id"]),
            )
            cleaned += 1
    print(f"✅ Убран флаг 'disabled' у {cleaned} профил(я/ей)")

    con.commit()
    con.close()
    print("✅ Готово. Если что-то не так — восстанови из бэкапа:")
    print(f"   cp {bak} {DB}")


if __name__ == "__main__":
    main()
