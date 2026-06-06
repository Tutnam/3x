import json
import asyncio
import logging
import warnings
import coloredlogs
from config import config
from aiogram import Bot, Dispatcher
from handlers import setup_handlers
from datetime import datetime, timedelta
from functions import delete_client_by_email, disable_client_by_email
from database import Session, User, init_db, get_all_users, delete_user_profile
from subscription_server import start_subscription_server

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Настройка логирования
coloredlogs.install(level='info')
logger = logging.getLogger(__name__)

async def check_subscriptions(bot: Bot):
    """Проверка статуса подписок"""
    while True:
        try:
            now = datetime.utcnow()
            users = await get_all_users()
            
            for user in users:
                if not user.subscription_end:
                    continue
                # Проверка за 1 день до окончания
                if user.subscription_end - now < timedelta(days=1) and user.subscription_end >= now and not user.notified:
                    try:
                        await bot.send_message(
                            user.telegram_id,
                            "⚠️ Ваша подписка истекает через 24 часа! Продлите подписку, чтобы сохранить доступ."
                        )
                        # Помечаем как уведомленного
                        with Session() as session:
                            db_user = session.query(User).filter_by(telegram_id=user.telegram_id).first()
                            if db_user:
                                db_user.notified = True
                                session.commit()
                    except Exception as e:
                        logger.warning(f"⚠️ Notification error: {e}")
                
                # Проверка истечения подписки
                if user.subscription_end <= now and user.vless_profile_data:
                    try:
                        profile = json.loads(user.vless_profile_data)
                        # Пропускаем если уже отключали
                        if profile.get("disabled"):
                            continue
                        
                        # Отключаем клиента в инбаунде (не удаляем)
                        success = await disable_client_by_email(profile["email"])
                        if success:
                            # Помечаем профиль как отключённый
                            profile["disabled"] = True
                            with Session() as session:
                                db_user = session.query(User).filter_by(telegram_id=user.telegram_id).first()
                                if db_user:
                                    db_user.vless_profile_data = json.dumps(profile)
                                    db_user.notified = True
                                    session.commit()
                            
                            await bot.send_message(
                                user.telegram_id,
                                "❌ Ваша подписка истекла! VPN профиль отключён. Продлите подписку, чтобы восстановить доступ."
                            )
                        else:
                            logger.warning(f"⚠️ Failed to disable client {profile['email']}")
                    except Exception as e:
                        logger.warning(f"⚠️ Disable error: {e}")
        except Exception as e:
            logger.warning(f"⚠️ Subscription check error: {e}")
        
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
        asyncio.create_task(check_subscriptions(bot))
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