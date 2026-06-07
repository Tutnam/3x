import asyncio
from datetime import datetime, timedelta, timezone
from functions import XUIAPI


def to_ms(dt):
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


async def main():
    api = XUIAPI()
    assert await api.login()
    email = "zz_expirytest_777222"
    await api.delete_client(email)  # на случай остатка

    try:
        # 1. создание с триалом 3 дня
        exp3 = to_ms(datetime.utcnow() + timedelta(days=3))
        prof = await api._create_client(email, telegram_id=999000002, expiry_ms=exp3)
        assert prof, "create failed"
        cl = await api.get_client(email)
        got = cl.get("expiryTime")
        print(f"(1) создан с expiryTime={got}, ожидалось≈{exp3}, diff={abs(got-exp3)}ms")
        assert abs(got - exp3) < 5000, "expiry при создании не совпал"
        assert cl.get("enable") is True
        print("✅ (1) новый клиент создаётся с ограничением 3 дня")

        # 2. продление до +30 дней
        exp30 = to_ms(datetime.utcnow() + timedelta(days=30))
        assert await api.set_client_subscription(email, exp30, enable=True)
        cl = await api.get_client(email)
        print(f"(2) после продления expiryTime={cl.get('expiryTime')}, enable={cl.get('enable')}")
        assert abs(cl.get("expiryTime") - exp30) < 5000
        assert cl.get("enable") is True
        print("✅ (2) продление меняет срок в панели")

        # 3. истечение: срок в прошлом + enable=False
        exppast = to_ms(datetime.utcnow() - timedelta(minutes=5))
        assert await api.set_client_subscription(email, exppast, enable=False)
        cl = await api.get_client(email)
        print(f"(3) после истечения expiryTime={cl.get('expiryTime')}, enable={cl.get('enable')}")
        assert cl.get("enable") is False
        print("✅ (3) истечение: срок в прошлом и клиент выключен")

    finally:
        await api.delete_client(email)
        gone = await api.get_client(email)
        await api.close()
        print("cleanup: удалён из панели:", gone is None)

    print("\n✅ УПРАВЛЕНИЕ ВРЕМЕНЕМ РАБОТАЕТ")


asyncio.run(main())
