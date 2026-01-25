import aiohttp
import uuid
import json
import logging
import random
import secrets
from config import config
from urllib.parse import urljoin
from urllib.parse import quote

logger = logging.getLogger(__name__)

def _extract_reality_from_inbound(inbound: dict) -> dict:
    try:
        stream_settings_raw = inbound.get("streamSettings") or "{}"
        stream_settings = json.loads(stream_settings_raw) if isinstance(stream_settings_raw, str) else (stream_settings_raw or {})
    except Exception:
        stream_settings = {}

    reality = stream_settings.get("realitySettings")
    if not reality and isinstance(stream_settings.get("settings"), dict):
        reality = stream_settings["settings"].get("realitySettings")
    if not isinstance(reality, dict):
        reality = {}

    short_ids = reality.get("shortIds")
    short_id = None
    if isinstance(short_ids, list) and short_ids:
        short_id = next((s for s in short_ids if isinstance(s, str) and s.strip()), None)
    elif isinstance(short_ids, str) and short_ids.strip():
        short_id = short_ids.strip()

    server_names = reality.get("serverNames")
    server_name = None
    if isinstance(server_names, list) and server_names:
        server_name = next((s for s in server_names if isinstance(s, str) and s.strip()), None)
    elif isinstance(server_names, str) and server_names.strip():
        server_name = server_names.strip()

    public_key = reality.get("publicKey") if isinstance(reality.get("publicKey"), str) else None

    return {
        "public_key": public_key,
        "short_id": short_id,
        "server_name": server_name,
    }

class XUIAPI:
    def __init__(self):
        self.session = None
        self.cookie_jar = aiohttp.CookieJar(unsafe=True)  # Разрешаем небезопасные куки
        self.auth_cookies = None

    async def login(self):
        """Аутентификация в 3x-UI API"""
        try:
            # Создаем новую сессию с общей куки-банкой
            self.session = aiohttp.ClientSession(
                cookie_jar=self.cookie_jar,
                trust_env=True  # Доверять переменным окружения для прокси
            )
            
            auth_data = {
                "username": config.XUI_USERNAME,
                "password": config.XUI_PASSWORD
            }
            
            # Формируем URL с учетом базового пути
            base_url = config.XUI_API_URL.rstrip('/')
            # base_path = config.XUI_BASE_PATH.strip('/')
            # if base_path:
            #     base_url = f"{base_url}/{base_path}"
            login_url = f"{base_url}/login"
            
            logger.info(f"ℹ️  Trying login to {login_url} with user: {config.XUI_USERNAME}")
            
            async with self.session.post(login_url, data=auth_data) as resp:
                if resp.status != 200:
                    logger.error(f"🛑 Login failed with status: {resp.status}")
                    return False
                
                # Проверяем JSON ответ
                try:
                    response = await resp.json()
                    if response.get("success"):
                        logger.info("✅ Login successful")
                        # Сохраняем куки для последующих запросов
                        self.auth_cookies = self.cookie_jar
                        logger.debug(f"⚙️ Auth cookies: {self.auth_cookies}")
                        return True
                    else:
                        logger.error(f"🛑 Login failed: {response.get('msg')}")
                        return False
                except Exception as e:
                    logger.debug(f"JSON parse failed, trying text: {e}")
                    # Если ответ не JSON, проверяем текст
                    text = await resp.text()
                    if "success" in text.lower():
                        logger.warning("⚠️ Login successful (text response)")
                        # Сохраняем куки для последующих запросов
                        self.auth_cookies = self.cookie_jar
                        logger.debug(f"⚙️ Auth cookies: {self.auth_cookies}")
                        return True
                    logger.error(f"🛑 Login failed. Response text: {text[:100]}...")
                    return False
        except Exception as e:
            logger.exception(f"🛑 Login error: {e}")
            # Закрываем сессию при ошибке, чтобы избежать утечки ресурсов
            if self.session:
                await self.session.close()
                self.session = None
            return False

    async def get_inbound(self, inbound_id: int):
        """Получение данных инбаунда"""
        try:
            base_url = config.XUI_API_URL.rstrip('/')
            base_path = config.XUI_BASE_PATH.strip('/')
            if base_path:
                base_url = f"{base_url}/{base_path}"
            url = f"{base_url}/api/inbounds/get/{inbound_id}"
            
            logger.info(f"ℹ️  Getting inbound data from: {url}")
            logger.debug(f"⚙️ Using cookies: {self.cookie_jar}")
            
            async with self.session.get(url) as resp:
                logger.debug(f"⚙️ Response status: {resp.status}")
                logger.debug(f"⚙️ Response cookies: {resp.cookies}")
                
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"🛑 Get inbound failed: status={resp.status}, response={text[:100]}...")
                    return None
                
                try:
                    data = await resp.json()
                    if data.get("success"):
                        obj = data.get("obj")
                        if obj:
                            logger.info(f'📋 Available inbound keys: {list(obj.keys())}')
                        logger.debug(f'⚙️ Data: {str(data)}')
                        return obj
                    else:
                        logger.error(f"🛑 Get inbound failed: {data.get('msg')}")
                        return None
                except Exception as e:
                    text = await resp.text()
                    logger.error(f"🛑 Get inbound JSON parse error: {e}. Response: {text[:100]}...")
                    return None
        except Exception as e:
            logger.exception(f"🛑 Get inbound error: {e}")
            return None

    async def update_inbound(self, inbound_id: int, data: dict):
        """Обновление инбаунда"""
        try:
            base_url = config.XUI_API_URL.rstrip('/')
            base_path = config.XUI_BASE_PATH.strip('/')
            if base_path:
                base_url = f"{base_url}/{base_path}"
            url = f"{base_url}/api/inbounds/update/{inbound_id}"
            
            logger.info(f"ℹ️  Updating inbound at: {url}")
            
            async with self.session.post(url, json=data) as resp:
                if resp.status != 200:
                    logger.error(f"🛑 Update inbound failed with status: {resp.status}")
                    return False
                
                try:
                    response = await resp.json()
                    return response.get("success", False)
                except Exception as e:
                    text = await resp.text()
                    logger.debug(f"JSON parse failed: {e}, checking text response")
                    return "success" in text.lower()
        except Exception as e:
            logger.exception(f"🛑 Update inbound error: {e}")
            return False

    async def create_vless_profile(self, telegram_id: int):
        """Создание нового клиента для пользователя"""
        if not await self.login():
            logger.error("🛑 Login failed before creating profile")
            return None
        
        inbound = await self.get_inbound(config.INBOUND_ID)
        if not inbound:
            logger.error(f"🛑 Inbound {config.INBOUND_ID} not found")
            return None

        reality_params = _extract_reality_from_inbound(inbound)
        sid = reality_params.get("short_id") or config.REALITY_SHORT_ID
        pbk = reality_params.get("public_key") or config.REALITY_PUBLIC_KEY
        sni = reality_params.get("server_name") or config.REALITY_SNI
        
        try:
            settings = json.loads(inbound["settings"])
            clients = settings.get("clients", [])
            
            client_id = str(uuid.uuid4())
            email = f"user_{telegram_id}_{random.randint(1000,9999)}"
            
            # Генерируем уникальный subscription ID
            sub_id = secrets.token_urlsafe(16)
            
            # Обновленные настройки для Reality
            new_client = {
                "id": client_id,
                "flow": (config.REALITY_FLOW or ""),
                "email": email,
                "limitIp": 0,
                "totalGB": 0,
                "expiryTime": 0,
                "enable": True,
                "tgId": "",
                "subId": sub_id,  # Уникальный subscription ID
                "reset": 0,
                # Добавляем настройки для Reality
                "fingerprint": config.REALITY_FINGERPRINT,
                "publicKey": pbk,
                "shortId": sid,
                "spiderX": config.REALITY_SPIDER_X
            }
            
            clients.append(new_client)
            settings["clients"] = clients
            
            update_data = {
                "up": inbound["up"],
                "down": inbound["down"],
                "total": inbound["total"],
                "remark": inbound["remark"],
                "enable": inbound["enable"],
                "expiryTime": inbound["expiryTime"],
                "listen": inbound["listen"],
                "port": inbound["port"],
                "protocol": inbound["protocol"],
                "settings": json.dumps(settings, indent=2),
                "streamSettings": inbound["streamSettings"],
                "sniffing": inbound["sniffing"],
                # "allocate": inbound["allocate"]
            }
            
            if await self.update_inbound(config.INBOUND_ID, update_data):
                return {
                    "client_id": client_id,
                    "email": email,
                    "sub_id": sub_id,  # Возвращаем subscription ID
                    "port": inbound["port"],
                    "flow": (config.REALITY_FLOW or ""),
                    "encryption": config.VLESS_ENCRYPTION,
                    # Указываем тип безопасности как reality
                    "security": "reality",
                    "remark": inbound["remark"],
                    # Добавляем необходимые параметры для Reality
                    "sni": sni,
                    "pbk": pbk,
                    "fp": config.REALITY_FINGERPRINT,
                    "sid": sid,
                    "spx": config.REALITY_SPIDER_X
                }
            return None
        except Exception as e:
            logger.exception(f"🛑 Create profile error: {e}")
            return None

    async def create_static_client(self, profile_name: str):
        """Создание статического клиента"""
        if not await self.login():
            logger.error("🛑 Login failed before creating static client")
            return None
        
        inbound = await self.get_inbound(config.INBOUND_ID)
        if not inbound:
            logger.error(f"🛑 Inbound {config.INBOUND_ID} not found")
            return None

        reality_params = _extract_reality_from_inbound(inbound)
        sid = reality_params.get("short_id") or config.REALITY_SHORT_ID
        pbk = reality_params.get("public_key") or config.REALITY_PUBLIC_KEY
        sni = reality_params.get("server_name") or config.REALITY_SNI
        
        try:
            settings = json.loads(inbound["settings"])
            clients = settings.get("clients", [])
            
            client_id = str(uuid.uuid4())
            
            # Генерируем уникальный subscription ID
            sub_id = secrets.token_urlsafe(16)
            
            # Обновленные настройки для Reality
            new_client = {
                "id": client_id,
                "flow": (config.REALITY_FLOW or ""),
                "email": profile_name,
                "limitIp": 0,
                "totalGB": 0,
                "expiryTime": 0,
                "enable": True,
                "tgId": "",
                "subId": sub_id,  # Уникальный subscription ID
                "reset": 0,
                # Добавляем настройки для Reality
                "fingerprint": config.REALITY_FINGERPRINT,
                "publicKey": pbk,
                "shortId": sid,
                "spiderX": config.REALITY_SPIDER_X
            }
            
            clients.append(new_client)
            settings["clients"] = clients
            
            update_data = {
                "up": inbound["up"],
                "down": inbound["down"],
                "total": inbound["total"],
                "remark": inbound["remark"],
                "enable": inbound["enable"],
                "expiryTime": inbound["expiryTime"],
                "listen": inbound["listen"],
                "port": inbound["port"],
                "protocol": inbound["protocol"],
                "settings": json.dumps(settings, indent=2),
                "streamSettings": inbound["streamSettings"],
                "sniffing": inbound["sniffing"],
                # "allocate": inbound["allocate"]
            }
            
            if await self.update_inbound(config.INBOUND_ID, update_data):
                return {
                    "client_id": client_id,
                    "email": profile_name,
                    "sub_id": sub_id,  # Возвращаем subscription ID
                    "port": inbound["port"],
                    "flow": (config.REALITY_FLOW or ""),
                    "encryption": config.VLESS_ENCRYPTION,
                    # Указываем тип безопасности как reality
                    "security": "reality",
                    "remark": inbound["remark"],
                    # Добавляем необходимые параметры для Reality
                    "sni": sni,
                    "pbk": pbk,
                    "fp": config.REALITY_FINGERPRINT,
                    "sid": sid,
                    "spx": config.REALITY_SPIDER_X
                }
            return None
        except Exception as e:
            logger.exception(f"🛑 Create static client error: {e}")
            return None

    async def delete_client(self, email: str):
        """Удаление клиента по email"""
        if not await self.login():
            return False
        
        try:
            # Получаем данные инбаунда
            inbound = await self.get_inbound(config.INBOUND_ID)
            if not inbound:
                return False
            
            settings = json.loads(inbound["settings"])
            clients = settings.get("clients", [])
            
            # Фильтруем клиентов
            new_clients = [c for c in clients if c["email"] != email]
            
            # Если не было изменений
            if len(new_clients) == len(clients):
                return False
            
            settings["clients"] = new_clients
            
            # Формируем данные для обновления
            update_data = {
                "up": inbound["up"],
                "down": inbound["down"],
                "total": inbound["total"],
                "remark": inbound["remark"],
                "enable": inbound["enable"],
                "expiryTime": inbound["expiryTime"],
                "listen": inbound["listen"],
                "port": inbound["port"],
                "protocol": inbound["protocol"],
                "settings": json.dumps(settings, indent=2),
                "streamSettings": inbound["streamSettings"],
                "sniffing": inbound["sniffing"],
                # "allocate": inbound["allocate"]
            }
            
            return await self.update_inbound(config.INBOUND_ID, update_data)
        except Exception as e:
            logger.exception(f"🛑 Delete client error: {e}")
            return False
    
    async def get_user_stats(self, email: str):
        """Получение статистики по email"""
        if not await self.login():
            logger.error("🛑 Login failed before getting stats")
            return {"upload": 0, "download": 0}
        
        try:
            base_url = config.XUI_API_URL.rstrip('/')
            base_path = config.XUI_BASE_PATH.strip('/')
            if base_path:
                base_url = f"{base_url}/{base_path}"
            url = f"{base_url}/api/inbounds/getClientTraffics/{email}"
            
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return {"upload": 0, "download": 0}
                
                try:
                    data = await resp.json()
                    if data.get("success"):
                        client_data = data.get("obj")
                        if isinstance(client_data, dict):
                            return {
                                "upload": client_data.get("up", 0),
                                "download": client_data.get("down", 0)
                            }
                except Exception as e:
                    logger.debug(f"Failed to parse user stats JSON: {e}")
                    return {"upload": 0, "download": 0}
        except Exception as e:
            logger.error(f"🛑 Stats error: {e}")
        return {"upload": 0, "download": 0}
    
    async def get_global_stats(self, inbound_id: int):
        """Получение статистики по email"""
        if not await self.login():
            logger.error("🛑 Login failed before getting stats")
            return {"upload": 0, "download": 0}
        
        try:
            base_url = config.XUI_API_URL.rstrip('/')
            base_path = config.XUI_BASE_PATH.strip('/')
            if base_path:
                base_url = f"{base_url}/{base_path}"
            url = f"{base_url}/api/inbounds/get/{inbound_id}"
            
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return {"upload": 0, "download": 0}
                
                try:
                    data = await resp.json()
                    if data.get("success"):
                        client_data = data.get("obj")
                        if isinstance(client_data, dict):
                            return {
                                "upload": client_data.get("up", 0),
                                "download": client_data.get("down", 0)
                            }
                except Exception as e:
                    logger.debug(f"Failed to parse global stats JSON: {e}")
                    return {"upload": 0, "download": 0}
        except Exception as e:
            logger.error(f"🛑 Stats error: {e}")
        return {"upload": 0, "download": 0}

    async def get_online_users(self):
        if not await self.login():
            logger.error("🛑 Login failed before getting stats")
            return 0
        
        try:
            base_url = config.XUI_API_URL.rstrip('/')
            base_path = config.XUI_BASE_PATH.strip('/')
            if base_path:
                base_url = f"{base_url}/{base_path}"
            url = f"{base_url}/api/inbounds/onlines"
            
            async with self.session.post(url) as resp:
                if resp.status != 200:
                    return 0

                
                try:
                    data = await resp.json()
                    logger.debug(data)
                    online = 0
                    if data.get("success"):
                        users = data.get("obj")
                        if isinstance(users, list):
                            for user in users:
                                if str(user).startswith("user_"):
                                    online += 1
                        return online
                except Exception as e:
                    logger.debug(f"Failed to parse online users JSON: {e}")
                    return 0
        except Exception as e:
            logger.error(f"🛑 Stats error: {e}")
        return 0

    async def close(self):
        if self.session:
            await self.session.close()

async def create_vless_profile(telegram_id: int):
    api = XUIAPI()
    try:
        return await api.create_vless_profile(telegram_id)
    finally:
        await api.close()

async def create_static_client(profile_name: str):
    api = XUIAPI()
    try:
        return await api.create_static_client(profile_name)
    finally:
        await api.close()

async def delete_client_by_email(email: str):
    api = XUIAPI()
    try:
        return await api.delete_client(email)
    finally:
        await api.close()

async def get_global_stats():
    api = XUIAPI()
    try:
        return await api.get_global_stats(config.INBOUND_ID)
    finally:
        await api.close()

async def get_online_users():
    api = XUIAPI()
    try:
        return await api.get_online_users()
    finally:
        await api.close()

async def get_user_stats(email: str):
    api = XUIAPI()
    try:
        return await api.get_user_stats(email)
    finally:
        await api.close()

def generate_vless_url(profile_data: dict) -> str:
    remark = profile_data.get('remark', '')
    email = profile_data['email']
    fragment = f"{remark}-{email}" if remark else email
    spx_raw = profile_data.get("spx") or config.REALITY_SPIDER_X or "/"
    spx = quote(spx_raw, safe="")
    flow = (profile_data.get("flow") or config.REALITY_FLOW or "").strip()
    flow_part = f"&flow={flow}" if flow else ""
    pbk = profile_data.get("pbk") or config.REALITY_PUBLIC_KEY
    fp = profile_data.get("fp") or config.REALITY_FINGERPRINT
    sni = profile_data.get("sni") or config.REALITY_SNI
    sid = profile_data.get("sid") or config.REALITY_SHORT_ID
    encryption = profile_data.get("encryption") or config.VLESS_ENCRYPTION

    host = (config.VLESS_PUBLIC_HOST or "").strip() or config.XUI_HOST
    port = int(config.VLESS_PUBLIC_PORT) if getattr(config, "VLESS_PUBLIC_PORT", 0) else int(profile_data["port"])
    
    return (
        f"vless://{profile_data['client_id']}@{host}:{port}"
        f"?type=tcp&encryption={encryption}&security=reality"
        f"&pbk={pbk}"
        f"&fp={fp}"
        f"&sni={sni}"
        f"&sid={sid}"
        f"&spx={spx}"
        f"{flow_part}"
        f"#{fragment}"
    )