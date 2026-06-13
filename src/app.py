import json
import asyncio
import logging
import warnings
import coloredlogs
from config import config
from aiogram import Bot, Dispatcher
from handlers import setup_handlers
from datetime import datetime, timedelta
from functions import get_clients_list
from database import Session, User, init_db, get_all_users, delete_user_profile
from subscription_server import start_subscription_server

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Настройка логирования
coloredlogs.install(level='info')
logger = logging.getLogger(__name__)

UNLIMITED_END = datetime(2099, 1, 1)  # зеркало безлимита (expiryTime == 0)


def _ms_to_dt(ms):
    """Unix epoch в мс → naive-UTC datetime. 0/пусто → дальняя дата (безлимит)."""
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        ms = 0
    if ms <= 0:
        return UNLIMITED_END
    return datetime.utcfromtimestamp(ms / 1000)


async def sync_subscriptions(bot: Bot):
    """Зеркалит срок подписки из панели (источник правды) в БД бота и шлёт
    предупреждение за 24 часа до истечения.

    Бот НЕ отключает клиентов — этим занимается сама панель по expiryTime.
    Ручные правки срока в панели также подхватываются этим циклом."""
    while True:
        try:
            # 1) Тянем актуальные сроки клиентов из панели
            clients = await get_clients_list()
            by_email = {c.get("email"): c for c in clients if c.get("email")}

            now = datetime.utcnow()

            # 2) Зеркалим срок панели → subscription_end для юзеров с профилем
            for user in await get_all_users():
                if not user.vless_profile_data:
                    continue
                try:
                    profile = json.loads(user.vless_profile_data)
                except Exception:
                    continue
                client = by_email.get(profile.get("email"))
                if client is None:
                    continue
                new_end = _ms_to_dt(client.get("expiryTime"))
                with Session() as session:
                    db_user = session.query(User).filter_by(telegram_id=user.telegram_id).first()
                    if not db_user:
                        continue
                    changed = False
                    if db_user.subscription_end != new_end:
                        db_user.subscription_end = new_end
                        changed = True
                    # Срок далеко (>1 дня) — снимаем флаг, чтобы снова предупредить
                    if new_end - now > timedelta(days=1) and db_user.notified:
                        db_user.notified = False
                        changed = True
                    if changed:
                        session.commit()

            # 3) Предупреждение за 24ч (для всех: профильных — по зеркалу,
            #    триальных без профиля — по их subscription_end в БД)
            for user in await get_all_users():
                if not user.subscription_end or user.notified:
                    continue
                if timedelta(0) < user.subscription_end - now < timedelta(days=1):
                    try:
                        await bot.send_message(
                            user.telegram_id,
                            "⚠️ Ваша подписка истекает через 24 часа! Продлите подписку, чтобы сохранить доступ."
                        )
                        with Session() as session:
                            db_user = session.query(User).filter_by(telegram_id=user.telegram_id).first()
                            if db_user:
                                db_user.notified = True
                                session.commit()
                    except Exception as e:
                        logger.warning(f"⚠️ Notification error: {e}")
        except Exception as e:
            logger.warning(f"⚠️ Subscription sync error: {e}")

        await asyncio.sleep(3600)

async def update_admins_status():
    """Обновляет статус администраторов в базе данных"""
    with Session() as session:
        # Сбрасываем статус администратора у всех пользователей
        session.query(User).update({User.is_admin: False})
        
        # Устанавливаем статус администратора для пользователей из config.ADMINS
        for admin_id in config.ADMINS:
            user = session.query(User).filter_by(telegram_id=admin_id).first()
            if user:
                user.is_admin = True
            else:
                # Если администратора нет в базе, создаем запись
                new_admin = User(
                    telegram_id=admin_id,
                    full_name=f"Admin {admin_id}",
                    is_admin=True,
                    subscription_end=datetime.utcnow()
                )
                session.add(new_admin)
        
        session.commit()
    logger.info("✅ Admin status updated in database")

async def main():
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    
    try:
        await init_db()
        logger.info("✅ Database initialized")

        # Обновляем статус администраторов
        await update_admins_status()
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")
        return
    
    try:
        setup_handlers(dp)
        logger.info("✅ Handlers registered")
    except Exception as e:
        logger.error(f"❌ Handler registration error: {e}")
        return
    
    # Запускаем фоновые задачи
    try:
        asyncio.create_task(sync_subscriptions(bot))
        asyncio.create_task(start_subscription_server())
        logger.info("✅ Background tasks started")
    except Exception as e:
        logger.error(f"❌ Background tasks failed to start: {e}")
    
    logger.info("ℹ️  Starting bot...")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Bot start error: {e}")
        return

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Stopping bot...")
        exit(0)
    except Exception as e:
        logger.error(f"❌ Main loop error: {e}")
        exit(1)