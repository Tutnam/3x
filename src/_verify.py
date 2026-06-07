import asyncio
import json
import os
import tempfile
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database
from database import User, get_all_users
from functions import XUIAPI, disable_client_by_email, enable_client_by_email

# --- Подменяем БД на временную, чтобы не трогать реальную users.db ------------
TMP_DB = tempfile.mktemp(suffix=".db")
database.engine = create_engine(f"sqlite:///{TMP_DB}")
database.Session = sessionmaker(bind=database.engine)
database.Base.metadata.create_all(database.engine)

TG_ID = 999000001


async def check_once(bot_msgs):
    """Одна итерация логики app.check_subscriptions (без сна и Telegram)."""
    now = datetime.utcnow()
    for user in await get_all_users():
        if not user.subscription_end:
            continue
        if user.subscription_end <= now and user.vless_profile_data:
            profile = json.loads(user.vless_profile_data)
            if profile.get("disabled"):
                continue
            if await disable_client_by_email(profile["email"]):
                profile["disabled"] = True
                with database.Session() as s:
                    du = s.query(User).filter_by(telegram_id=user.telegram_id).first()
                    du.vless_profile_data = json.dumps(profile)
                    du.notified = True
                    s.commit()
                bot_msgs.append(("expired", user.telegram_id))


async def main():
    # === (A) Триал: новый пользователь получает 3 дня ===
    u = await database.create_user(telegram_id=TG_ID, full_name="Trial Test")
    days = (u.subscription_end - datetime.utcnow()).total_seconds() / 86400
    print(f"(A) trial длительность: {days:.3f} дней")
    assert 2.99 < days <= 3.001, "триал != 3 дня"
    print("✅ (A) новый клиент получает ровно 3 дня пробного периода")

    # === Создаём реального тестового клиента в панели и привязываем к юзеру ===
    api = XUIAPI()
    assert await api.login()
    email = f"zz_trialtest_{TG_ID}"
    # на всякий случай удалим, если остался от прошлого прогона
    await api.delete_client(email)
    prof = await api._create_client(email, telegram_id=TG_ID)
    assert prof, "не удалось создать тестового клиента"
    cl = await api.get_client(email)
    print(f"клиент создан, enable={cl.get('enable')}")
    assert cl.get("enable") is True
    await api.close()

    # === (B) Пока подписка активна (3 дня) — клиент НЕ должен выключаться ===
    with database.Session() as s:
        du = s.query(User).filter_by(telegram_id=TG_ID).first()
        du.vless_profile_data = json.dumps(prof)
        s.commit()
    msgs = []
    await check_once(msgs)
    api = XUIAPI(); await api.login()
    cl = await api.get_client(email)
    print(f"(B) при активной подписке enable={cl.get('enable')}, уведомлений={len(msgs)}")
    assert cl.get("enable") is True, "клиент выключен при активной подписке!"
    await api.close()
    print("✅ (B) активная подписка — клиент остаётся включён")

    # === (C) Подписка истекла — бот должен выключить клиента ===
    with database.Session() as s:
        du = s.query(User).filter_by(telegram_id=TG_ID).first()
        du.subscription_end = datetime.utcnow() - timedelta(minutes=5)
        s.commit()
    msgs = []
    await check_once(msgs)
    api = XUIAPI(); await api.login()
    cl = await api.get_client(email)
    print(f"(C) после истечения enable={cl.get('enable')}, уведомлений={len(msgs)}")
    assert cl.get("enable") is False, "клиент НЕ выключен после истечения!"
    assert msgs == [("expired", TG_ID)]
    await api.close()
    print("✅ (C) подписка истекла — бот отключил клиента")

    # === (D) Идемпотентность: повторная проверка не дёргает панель снова ===
    msgs = []
    await check_once(msgs)
    print(f"(D) повторная проверка: уведомлений={len(msgs)} (ожидается 0 — флаг disabled)")
    assert msgs == []
    print("✅ (D) повторно не отключает (флаг disabled)")

    # === Очистка: удаляем тестового клиента из панели ===
    api = XUIAPI(); await api.login()
    await api.delete_client(email)
    gone = await api.get_client(email)
    await api.close()
    print("cleanup: клиент удалён из панели:", gone is None)

    print("\n✅ ВСЕ МЕХАНИЗМЫ РАБОТАЮТ")


asyncio.run(main())
os.remove(TMP_DB)
