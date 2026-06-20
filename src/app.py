import os
import json
import asyncio
import logging
import warnings
import coloredlogs
from config import config
from aiogram import Bot, Dispatcher
from aiogram.types import FSInputFile
from handlers import setup_handlers
from datetime import datetime, timedelta
from functions import get_clients_list
from database import Session, User, init_db, get_all_users, delete_user_profile, backup_database, get_user_stats
from subscription_server import start_subscription_server
from utils import _ms_to_dt, UNLIMITED_END, reminder_target_stage

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Настройка логирования
coloredlogs.install(level='info')
logger = logging.getLogger(__name__)

# Тексты ступенчатых напоминаний (#17) по стадиям notify_stage
REMINDER_TEXTS = {
    1: "⏳ Ваша подписка истекает через 3 дня. Продлите заранее, чтобы не потерять доступ.",
    2: "⚠️ Ваша подписка истекает через 24 часа! Продлите подписку, чтобы сохранить доступ.",
    3: "🛑 Ваша подписка истекла. Продлите её, чтобы восстановить доступ к VPN.",
}


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
                    # Срок далеко (>3 дней, т.е. продлили) — сбрасываем стадию
                    # напоминаний, чтобы заново предупредить в следующем цикле
                    if new_end - now > timedelta(days=3) and db_user.notify_stage:
                        db_user.notify_stage = 0
                        changed = True
                    if changed:
                        session.commit()

            # 3) Ступенчатые напоминания: за 3 дня, за 24ч и в момент истечения.
            #    notify_stage хранит последнюю отправленную стадию (1/2/3),
            #    чтобы не дублировать и слать каждое окно ровно один раз.
            for user in await get_all_users():
                if not user.subscription_end:
                    continue
                target_stage = reminder_target_stage(user.subscription_end - now, user.notify_stage)
                if target_stage is None:
                    continue
                try:
                    await bot.send_message(user.telegram_id, REMINDER_TEXTS[target_stage])
                    with Session() as session:
                        db_user = session.query(User).filter_by(telegram_id=user.telegram_id).first()
                        if db_user:
                            db_user.notify_stage = target_stage
                            session.commit()
                    await asyncio.sleep(0.05)  # rate-limit рассылки напоминаний
                except Exception as e:
                    logger.warning(f"⚠️ Notification error: {e}")
        except Exception as e:
            logger.warning(f"⚠️ Subscription sync error: {e}")

        await asyncio.sleep(3600)

async def _send_backup_to_admins(bot: Bot, path: str):
    """Off-site копия: отправляет файл бэкапа всем админам в Telegram.

    Локальный бэкап умрёт вместе с сервером — копия в ЛС админа переживёт."""
    try:
        total, with_sub, _ = await get_user_stats()
    except Exception:
        total = with_sub = "?"
    caption = (
        "💾 Бэкап БД\n"
        f"Файл: {os.path.basename(path)}\n"
        f"Юзеров: {total} (с подпиской: {with_sub})"
    )
    document = FSInputFile(path)
    for admin_id in config.ADMINS:
        try:
            await bot.send_document(admin_id, document, caption=caption)
        except Exception as e:
            logger.warning(f"⚠️ Не удалось отправить бэкап админу {admin_id}: {e}")


async def backup_db_loop(bot: Bot):
    """Раз в сутки делает резервную копию users.db с ротацией на 7 дней и, если
    включено (BACKUP_TO_TG), отправляет свежий дамп админам в Telegram.

    Бэкап нужен потому, что БД бота — единственный источник правды по триальным
    подпискам (которых нет в панели)."""
    while True:
        try:
            path = await asyncio.to_thread(backup_database)
            logger.info(f"💾 Database backup created: {path}")
            if config.BACKUP_TO_TG and config.ADMINS:
                await _send_backup_to_admins(bot, path)
        except Exception as e:
            logger.warning(f"⚠️ Database backup error: {e}")
        await asyncio.sleep(24 * 60 * 60)


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
        asyncio.create_task(backup_db_loop(bot))
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