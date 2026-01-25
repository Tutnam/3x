import asyncio
import logging
import base64
from aiohttp import web
from datetime import datetime
from config import config
from database import get_user_by_subscription_id
from functions import XUIAPI, generate_vless_url

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
        
        # Парсим данные профиля
        import json
        logger.info(f"🔍 Parsing profile data...")
        profile_data = json.loads(user.vless_profile_data)
        logger.info(f"✅ Profile data parsed successfully")
        
        # Получаем актуальные настройки из 3x-UI
        logger.info(f"🔍 Connecting to 3x-UI API...")
        api = XUIAPI()
        try:
            login_success = await api.login()
            logger.info(f"🔍 Login result: {login_success}")
            
            if login_success:
                logger.info(f"🔍 Fetching inbound {config.INBOUND_ID}...")
                inbound = await api.get_inbound(config.INBOUND_ID)
                
                if inbound:
                    logger.info(f"✅ Inbound data received")
                    # Обновляем параметры Reality из актуальных настроек
                    from functions import _extract_reality_from_inbound
                    reality_params = _extract_reality_from_inbound(inbound)
                    
                    # Обновляем профиль актуальными данными
                    profile_data['port'] = inbound['port']
                    profile_data['sni'] = reality_params.get('server_name') or config.REALITY_SNI
                    profile_data['pbk'] = reality_params.get('public_key') or config.REALITY_PUBLIC_KEY
                    profile_data['sid'] = reality_params.get('short_id') or config.REALITY_SHORT_ID
                    profile_data['remark'] = inbound.get('remark', profile_data.get('remark', ''))
                    logger.info(f"✅ Profile data updated with current inbound settings")
                else:
                    logger.warning(f"⚠️ Could not fetch inbound, using cached profile data")
            else:
                logger.warning(f"⚠️ Login failed, using cached profile data")
        except Exception as api_error:
            logger.error(f"🛑 API error: {api_error}", exc_info=True)
        finally:
            await api.close()
        
        # Генерируем VLESS URL с актуальными настройками
        logger.info(f"🔍 Generating VLESS URL...")
        vless_url = generate_vless_url(profile_data)
        logger.info(f"✅ VLESS URL generated: {vless_url[:50]}...")
        
        # Кодируем в base64 (стандарт для subscription URL)
        logger.info(f"🔍 Encoding to base64...")
        encoded = base64.b64encode(vless_url.encode('utf-8')).decode('utf-8')
        logger.info(f"✅ Encoded successfully. Length: {len(encoded)} bytes")
        
        logger.info(f"✅ Subscription served for user {user.telegram_id}")
        
        # Возвращаем в формате base64
        return web.Response(
            text=encoded,
            content_type='text/plain',
            charset='utf-8',
            headers={
                'Subscription-Userinfo': f'upload=0; download=0; total=0; expire={int(user.subscription_end.timestamp())}',
                'Profile-Update-Interval': '24',  # Обновлять раз в 24 часа
                'Profile-Title': f'VPN - {user.full_name}'
            }
        )
        
    except Exception as e:
        logger.exception(f"🛑 Subscription error: {e}")
        return web.Response(text="Internal server error", status=500)

async def start_subscription_server():
    """Запуск HTTP сервера для subscription URL"""
    app = web.Application()
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
