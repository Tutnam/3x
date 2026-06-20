import asyncio
import logging
import base64
from aiohttp import web
from datetime import datetime
from config import config
from database import get_user_by_subscription_id
from functions import get_client_links_by_email, get_client_traffic_by_email

logger = logging.getLogger(__name__)

async def handle_subscription(request):
    """
    Обработчик subscription URL endpoint
    GET /{subscription_id}
    """
    subscription_id = request.match_info.get('subscription_id')
    logger.info(f"📥 Subscription request received: {subscription_id}")
    
    if not subscription_id:
        logger.warning("⚠️ No subscription_id provided")
        return web.Response(text="Invalid subscription ID", status=400)
    
    try:
        # Получаем пользователя по subscription_id
        logger.info(f"🔍 Looking up user by subscription_id: {subscription_id}")
        user = await get_user_by_subscription_id(subscription_id)
        
        if not user:
            logger.warning(f"⚠️ Subscription not found: {subscription_id}")
            return web.Response(text="Subscription not found", status=404)
        
        logger.info(f"✅ User found: {user.telegram_id} ({user.full_name})")
        
        # Проверяем активность подписки
        logger.info(f"🔍 Checking subscription status. End date: {user.subscription_end}")
        if not user.subscription_end or user.subscription_end < datetime.utcnow():
            logger.warning(f"⚠️ Subscription expired for user {user.telegram_id}")
            return web.Response(text="Subscription expired", status=403)
        
        logger.info(f"✅ Subscription is active until {user.subscription_end}")
        
        # Проверяем наличие профиля
        if not user.vless_profile_data:
            logger.warning(f"⚠️ No profile data for user {user.telegram_id}")
            return web.Response(text="No profile configured", status=404)
        
        logger.info(f"✅ Profile data exists")

        # Парсим данные профиля, чтобы получить email клиента
        import json
        logger.info(f"🔍 Parsing profile data...")
        profile_data = json.loads(user.vless_profile_data)
        email = profile_data.get("email")
        logger.info(f"✅ Profile data parsed successfully (email: {email})")

        if not email:
            logger.warning(f"⚠️ No email in profile data for user {user.telegram_id}")
            return web.Response(text="No profile configured", status=404)

        # В v3.2.0 готовые ссылки (для всех привязанных инбаундов и протоколов)
        # генерирует сама панель — забираем их через /clients/links/{email}.
        logger.info(f"🔍 Fetching client links from 3x-UI for {email}...")
        links = await get_client_links_by_email(email)
        logger.info(f"✅ Got {len(links)} link(s) from panel")

        if not links:
            logger.warning(f"⚠️ No links returned for {email}")
            return web.Response(text="No profile configured", status=404)

        # Кодируем в base64 (стандарт subscription URL — строки через перевод строки)
        logger.info(f"🔍 Encoding to base64...")
        payload = "\n".join(links)
        encoded = base64.b64encode(payload.encode('utf-8')).decode('utf-8')
        logger.info(f"✅ Encoded successfully. Length: {len(encoded)} bytes")

        # Реальный трафик клиента — чтобы приложения показывали потребление.
        # total=0 означает «безлимит» (клиенты так и трактуют этот хедер).
        traffic = await get_client_traffic_by_email(email)
        upload = int(traffic.get("upload", 0) or 0)
        download = int(traffic.get("download", 0) or 0)
        logger.info(f"✅ Traffic for {email}: up={upload}, down={download}")

        logger.info(f"✅ Subscription served for user {user.telegram_id}")

        # Возвращаем в формате base64
        return web.Response(
            text=encoded,
            content_type='text/plain',
            charset='utf-8',
            headers={
                'Subscription-Userinfo': f'upload={upload}; download={download}; total=0; expire={int(user.subscription_end.timestamp())}',
                'Profile-Update-Interval': '24',  # Обновлять раз в 24 часа
                'Profile-Title': f'VPN - {user.full_name}'
            }
        )
        
    except Exception as e:
        logger.exception(f"🛑 Subscription error: {e}")
        return web.Response(text="Internal server error", status=500)

async def handle_health(request):
    """Liveness-проба для Docker/мониторинга: 200, если процесс жив и loop крутится."""
    return web.json_response({"status": "ok"})

async def start_subscription_server():
    """Запуск HTTP сервера для subscription URL"""
    app = web.Application()
    # /health регистрируем ДО catch-all '/{subscription_id}', иначе healthcheck
    # уйдёт в обработчик подписки и вернёт 404.
    app.router.add_get('/health', handle_health)
    app.router.add_get('/{subscription_id}', handle_subscription)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(
        runner,
        host=config.SUBSCRIPTION_HOST,
        port=config.SUBSCRIPTION_PORT
    )
    
    await site.start()
    logger.info(f"✅ Subscription server started on {config.SUBSCRIPTION_HOST}:{config.SUBSCRIPTION_PORT}")
    logger.info(f"📋 Subscription base URL: {config.SUBSCRIPTION_BASE_URL}")
    
    # Держим сервер запущенным
    while True:
        await asyncio.sleep(3600)
