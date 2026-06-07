import aiohttp
import asyncio
import uuid
import json
import logging
import random
import secrets
from config import config
from urllib.parse import quote

logger = logging.getLogger(__name__)


def _extract_reality_from_inbound(inbound: dict) -> dict:
    """Вытаскивает Reality-параметры из streamSettings инбаунда.

    Оставлено для обратной совместимости и как fallback для generate_vless_url.
    В v3.2.0 готовые ссылки берутся напрямую у панели (/clients/links/{email}).
    """
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
    """Клиент 3x-ui API v3.2.0.

    В v3.2.0 клиент — отдельная сущность, к которой привязываются инбаунды
    (many-to-many). Управление идёт через эндпоинты /panel/api/clients/*:
    add / update / del / get / links / traffic / onlines.
    """

    def __init__(self):
        self.session = None
        self.cookie_jar = aiohttp.CookieJar(unsafe=True)  # Разрешаем небезопасные куки
        self.auth_cookies = None

    def _build_url(self, endpoint: str) -> str:
        """Построение URL для API endpoint."""
        base_url = config.XUI_API_URL.rstrip('/')
        base_path = config.XUI_BASE_PATH.strip('/')

        if base_path:
            # v3 стиль: https://domain.com/path/panel/api/endpoint
            return f"{base_url}/{base_path}/panel/api{endpoint}"
        # Fallback: https://domain.com/panel/api/endpoint
        return f"{base_url}/panel/api{endpoint}"

    async def login(self):
        """Аутентификация в 3x-ui API.

        Предпочтительный способ для v3.2.0 — API token (Bearer). Если токен не
        задан, делаем fallback на логин по username/password (cookie-сессия).
        """
        try:
            # Создаём новую сессию с общей куки-банкой
            self.session = aiohttp.ClientSession(
                cookie_jar=self.cookie_jar,
                trust_env=True  # Доверять переменным окружения для прокси
            )

            # Если есть API token — используем его (предпочтительный метод)
            if config.XUI_API_TOKEN:
                logger.info("ℹ️  Using API token for authentication")
                self.session.headers.update({
                    "Authorization": f"Bearer {config.XUI_API_TOKEN}"
                })
                logger.info("✅ API token set for authorization")
                return True

            # Иначе — логин через username/password
            auth_data = {
                "username": config.XUI_USERNAME,
                "password": config.XUI_PASSWORD
            }

            base_url = config.XUI_API_URL.rstrip('/')
            base_path = config.XUI_BASE_PATH.strip('/')

            endpoints = []
            if base_path:
                endpoints.append(f"{base_url}/{base_path}/login")
            endpoints.append(f"{base_url}/login")

            for login_url in endpoints:
                try:
                    logger.info(f"ℹ️  Trying login to {login_url} with user: {config.XUI_USERNAME}")
                    async with self.session.post(login_url, data=auth_data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            try:
                                response = await resp.json()
                                if response.get("success"):
                                    logger.info("✅ Login successful")
                                    self.auth_cookies = self.cookie_jar
                                    return True
                                logger.warning(f"⚠️ Login response not successful: {response.get('msg')}")
                                continue
                            except Exception as e:
                                logger.debug(f"JSON parse failed: {e}")
                                text = await resp.text()
                                if "success" in text.lower():
                                    logger.info("✅ Login successful (text response)")
                                    self.auth_cookies = self.cookie_jar
                                    return True
                                continue
                        else:
                            logger.debug(f"⚠️ Endpoint {login_url} returned status {resp.status}")
                            continue
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Login timeout for {login_url}, trying next...")
                    continue
                except Exception as e:
                    logger.debug(f"⚠️ Login error for {login_url}: {e}, trying next...")
                    continue

            logger.error("🛑 Login failed with username/password. Set XUI_API_TOKEN in .env (Settings → Security → API Token).")
            return False
        except Exception as e:
            logger.exception(f"🛑 Login error: {e}")
            if self.session:
                await self.session.close()
                self.session = None
            return False

    # ----------------------------------------------------------------------
    # Низкоуровневые методы API v3.2.0 (/clients/*)
    # ----------------------------------------------------------------------

    async def add_client(self, client: dict, inbound_ids: list) -> bool:
        """Создание клиента и привязка к инбаундам: POST /clients/add.

        Body: {"client": {...}, "inboundIds": [...]}.
        """
        try:
            url = self._build_url("/clients/add")
            payload = {"client": client, "inboundIds": inbound_ids}
            logger.info(f"ℹ️  Adding client {client.get('email')} → inbounds {inbound_ids}")
            async with self.session.post(url, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"🛑 Add client failed: status={resp.status}, response={text[:200]}")
                    return False
                data = await resp.json()
                success = data.get("success", False)
                if success:
                    logger.info(f"✅ Client {client.get('email')} added")
                else:
                    logger.error(f"🛑 Add client failed: {data.get('msg', 'Unknown error')}")
                return success
        except Exception as e:
            logger.exception(f"🛑 Add client error: {e}")
            return False

    async def get_client(self, email: str):
        """Получение клиента по email: GET /clients/get/{email}.

        Возвращает объект клиента (плоские поля) с дополнительным ключом
        ``inboundIds`` — списком привязанных инбаундов. None, если не найден.
        """
        try:
            url = self._build_url(f"/clients/get/{quote(email, safe='')}")
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"🛑 Get client failed: status={resp.status}, response={text[:200]}")
                    return None
                data = await resp.json()
                if not data.get("success"):
                    logger.error(f"🛑 Get client failed: {data.get('msg')}")
                    return None
                obj = data.get("obj") or {}
                client = obj.get("client") if isinstance(obj, dict) else None
                if not isinstance(client, dict):
                    logger.warning(f"⚠️ Client {email} not found")
                    return None
                client = dict(client)
                client["inboundIds"] = obj.get("inboundIds", [])
                return client
        except Exception as e:
            logger.exception(f"🛑 Get client error: {e}")
            return None

    async def update_client(self, email: str, client: dict) -> bool:
        """Обновление клиента: POST /clients/update/{email}.

        Тело — плоский объект клиента (без обёртки). Сервер заменяет строку
        целиком, поэтому передавать полный набор полей.
        """
        try:
            url = self._build_url(f"/clients/update/{quote(email, safe='')}")
            async with self.session.post(url, json=client) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"🛑 Update client failed: status={resp.status}, response={text[:200]}")
                    return False
                data = await resp.json()
                success = data.get("success", False)
                if not success:
                    logger.error(f"🛑 Update client failed: {data.get('msg', 'Unknown error')}")
                return success
        except Exception as e:
            logger.exception(f"🛑 Update client error: {e}")
            return False

    async def delete_client(self, email: str, keep_traffic: bool = False) -> bool:
        """Удаление клиента: POST /clients/del/{email}?keepTraffic=0|1."""
        try:
            keep = 1 if keep_traffic else 0
            url = self._build_url(f"/clients/del/{quote(email, safe='')}") + f"?keepTraffic={keep}"
            logger.info(f"ℹ️  Deleting client {email}")
            async with self.session.post(url, json={}) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"🛑 Delete client failed: status={resp.status}, response={text[:200]}")
                    return False
                data = await resp.json()
                success = data.get("success", False)
                if success:
                    logger.info(f"✅ Client {email} deleted")
                else:
                    logger.error(f"🛑 Delete client failed: {data.get('msg', 'Unknown error')}")
                return success
        except Exception as e:
            logger.exception(f"🛑 Delete client error: {e}")
            return False

    async def get_client_links(self, email: str) -> list:
        """Готовые ссылки клиента по всем привязанным инбаундам: GET /clients/links/{email}."""
        try:
            url = self._build_url(f"/clients/links/{quote(email, safe='')}")
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"🛑 Get client links failed: status={resp.status}, response={text[:200]}")
                    return []
                data = await resp.json()
                if data.get("success"):
                    links = data.get("obj") or []
                    return [l for l in links if isinstance(l, str) and l.strip()]
                logger.error(f"🛑 Get client links failed: {data.get('msg')}")
                return []
        except Exception as e:
            logger.exception(f"🛑 Get client links error: {e}")
            return []

    async def get_client_traffic(self, email: str) -> dict:
        """Трафик клиента: GET /clients/traffic/{email}. Возвращает {upload, download}."""
        try:
            url = self._build_url(f"/clients/traffic/{quote(email, safe='')}")
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return {"upload": 0, "download": 0}
                data = await resp.json()
                if data.get("success"):
                    obj = data.get("obj")
                    if isinstance(obj, dict):
                        return {
                            "upload": obj.get("up", 0) or 0,
                            "download": obj.get("down", 0) or 0,
                        }
        except Exception as e:
            logger.error(f"🛑 Client traffic error: {e}")
        return {"upload": 0, "download": 0}

    async def toggle_client(self, email: str, enable: bool) -> bool:
        """Включение/отключение клиента (без удаления).

        Читаем текущего клиента, выставляем enable, отправляем полный набор
        полей обратно (сервер заменяет строку целиком).
        """
        try:
            client = await self.get_client(email)
            if not client:
                logger.warning(f"⚠️ Client {email} not found, cannot toggle")
                return False

            # Убираем read-only / служебные поля, которые не входят в payload
            for ro in ("id", "createdAt", "updatedAt", "traffic", "inboundIds", "group"):
                client.pop(ro, None)

            client["enable"] = enable

            result = await self.update_client(email, client)
            if result:
                logger.info(f"✅ Client {email} {'enabled' if enable else 'disabled'}")
            return result
        except Exception as e:
            logger.exception(f"🛑 Toggle client error: {e}")
            return False

    async def set_client_subscription(self, email: str, expiry_ms: int, enable: bool = True) -> bool:
        """Синхронизация срока подписки и состояния клиента.

        Выставляет клиенту ``expiryTime`` (мс, 0=безлимит) и ``enable`` одним
        обновлением. Используется при продлении/оплате/изменении срока админом.
        """
        try:
            client = await self.get_client(email)
            if not client:
                logger.warning(f"⚠️ Client {email} not found, cannot set subscription")
                return False

            for ro in ("id", "createdAt", "updatedAt", "traffic", "inboundIds", "group"):
                client.pop(ro, None)

            client["expiryTime"] = int(expiry_ms or 0)
            client["enable"] = enable

            result = await self.update_client(email, client)
            if result:
                logger.info(f"✅ Client {email} subscription set: expiry_ms={expiry_ms}, enable={enable}")
            return result
        except Exception as e:
            logger.exception(f"🛑 Set client subscription error: {e}")
            return False

    # ----------------------------------------------------------------------
    # Инбаунды / статистика
    # ----------------------------------------------------------------------

    async def get_inbound(self, inbound_id: int):
        """Получение данных одного инбаунда: GET /inbounds/get/{id} (fallback)."""
        try:
            url = self._build_url(f"/inbounds/get/{inbound_id}")
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"🛑 Get inbound failed: status={resp.status}, response={text[:100]}")
                    return None
                data = await resp.json()
                if data.get("success"):
                    return data.get("obj")
                logger.error(f"🛑 Get inbound failed: {data.get('msg')}")
                return None
        except Exception as e:
            logger.exception(f"🛑 Get inbound error: {e}")
            return None

    async def get_all_inbound_ids(self, protocols=("vless", "vmess", "trojan", "shadowsocks")) -> list:
        """Актуальный список id инбаундов с панели: GET /inbounds/list.

        Используется для динамической привязки нового клиента ко всем инбаундам
        (чтобы при добавлении нового сервера/инбаунда ничего не править в конфиге).
        Фильтруем по клиентским протоколам, чтобы не привязывать клиента к
        служебным инбаундам (dokodemo-door, wireguard, http, socks и т.п.),
        у которых нет понятия «клиент».
        """
        try:
            url = self._build_url("/inbounds/list")
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"🛑 Get inbounds list failed: status={resp.status}, response={text[:200]}")
                    return []
                data = await resp.json()
                if not data.get("success"):
                    logger.error(f"🛑 Get inbounds list failed: {data.get('msg')}")
                    return []
                ids = []
                for ib in data.get("obj") or []:
                    if isinstance(ib, dict) and ib.get("id") is not None:
                        if protocols is None or ib.get("protocol") in protocols:
                            ids.append(ib["id"])
                return sorted(ids)
        except Exception as e:
            logger.exception(f"🛑 Get inbounds list error: {e}")
            return []

    async def get_global_stats(self) -> dict:
        """Суммарный трафик по всем инбаундам: GET /inbounds/list."""
        try:
            url = self._build_url("/inbounds/list")
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return {"upload": 0, "download": 0}
                data = await resp.json()
                if not data.get("success"):
                    return {"upload": 0, "download": 0}
                up = down = 0
                for ib in data.get("obj") or []:
                    if isinstance(ib, dict):
                        up += ib.get("up", 0) or 0
                        down += ib.get("down", 0) or 0
                return {"upload": up, "download": down}
        except Exception as e:
            logger.error(f"🛑 Global stats error: {e}")
        return {"upload": 0, "download": 0}

    async def get_online_users(self) -> int:
        """Количество онлайн-пользователей бота: POST /clients/onlines."""
        try:
            url = self._build_url("/clients/onlines")
            async with self.session.post(url) as resp:
                if resp.status != 200:
                    return 0
                data = await resp.json()
                if data.get("success"):
                    users = data.get("obj")
                    if isinstance(users, list):
                        return sum(1 for u in users if str(u).startswith("user_"))
        except Exception as e:
            logger.error(f"🛑 Online users error: {e}")
        return 0

    # ----------------------------------------------------------------------
    # Высокоуровневые операции
    # ----------------------------------------------------------------------

    async def _create_client(self, email: str, telegram_id: int = 0, expiry_ms: int = 0):
        """Общая логика создания клиента и привязки ко всем INBOUND_IDS.

        ``expiry_ms`` — момент истечения подписки в миллисекундах (Unix epoch);
        0 = безлимит. Возвращает profile_data в формате, совместимом с БД.
        """
        client_id = str(uuid.uuid4())
        sub_id = secrets.token_urlsafe(16)

        client = {
            "email": email,
            "id": client_id,        # uuid клиента (VLESS)
            "uuid": client_id,      # дублируем — панель принимает оба варианта
            "subId": sub_id,
            "flow": (config.REALITY_FLOW or ""),
            "limitIp": 0,
            "totalGB": 0,
            "expiryTime": int(expiry_ms or 0),
            "enable": True,
            "tgId": telegram_id or 0,
            "reset": 0,
        }

        # Определяем инбаунды для привязки:
        #  1) если INBOUND_IDS задан в конфиге — используем его (явное закрепление);
        #  2) иначе запрашиваем актуальный список с панели (авто-режим);
        #  3) если и это не удалось — fallback на единственный INBOUND_ID.
        inbound_ids = list(config.INBOUND_IDS or [])
        if not inbound_ids:
            inbound_ids = await self.get_all_inbound_ids()
            logger.info(f"ℹ️  Auto inbound list from panel: {inbound_ids}")
        if not inbound_ids:
            inbound_ids = [config.INBOUND_ID]

        if not await self.add_client(client, inbound_ids):
            return None

        # profile_data с прежними ключами (для обратной совместимости БД/хендлеров).
        # Reality-поля заполняем из конфига — они нужны только generate_vless_url
        # (fallback); основной путь использует ссылки от панели.
        return {
            "client_id": client_id,
            "email": email,
            "sub_id": sub_id,
            "port": int(config.VLESS_PUBLIC_PORT) if getattr(config, "VLESS_PUBLIC_PORT", 0) else 443,
            "flow": (config.REALITY_FLOW or ""),
            "encryption": config.VLESS_ENCRYPTION,
            "security": "reality",
            "remark": "",
            "sni": config.REALITY_SNI,
            "pbk": config.REALITY_PUBLIC_KEY,
            "fp": config.REALITY_FINGERPRINT,
            "sid": config.REALITY_SHORT_ID,
            "spx": config.REALITY_SPIDER_X,
        }

    async def create_vless_profile(self, telegram_id: int, expiry_ms: int = 0):
        """Создание профиля для пользователя бота (expiry_ms — срок в мс, 0=безлимит)."""
        if not await self.login():
            logger.error("🛑 Login failed before creating profile")
            return None
        email = f"user_{telegram_id}_{random.randint(1000, 9999)}"
        profile = await self._create_client(email, telegram_id=telegram_id, expiry_ms=expiry_ms)
        if profile:
            logger.info(f"✅ Created VLESS profile for user {telegram_id}, email: {email}, expiry_ms={expiry_ms}")
        else:
            logger.warning(f"⚠️ Failed to create profile for user {telegram_id}")
        return profile

    async def create_static_client(self, profile_name: str, expiry_ms: int = 0):
        """Создание статического клиента (имя = email; expiry_ms 0=безлимит)."""
        if not await self.login():
            logger.error("🛑 Login failed before creating static client")
            return None
        profile = await self._create_client(profile_name, telegram_id=0, expiry_ms=expiry_ms)
        if profile:
            logger.info(f"✅ Created static client: {profile_name}")
        else:
            logger.warning(f"⚠️ Failed to create static client: {profile_name}")
        return profile

    async def get_user_stats(self, email: str):
        """Статистика по email (совместимость со старым API хендлеров)."""
        if not await self.login():
            logger.error("🛑 Login failed before getting stats")
            return {"upload": 0, "download": 0}
        return await self.get_client_traffic(email)

    async def close(self):
        if self.session:
            await self.session.close()


# --------------------------------------------------------------------------
# Публичные функции-обёртки (контракт для handlers.py / app.py / subscription_server.py)
# --------------------------------------------------------------------------

async def create_vless_profile(telegram_id: int, expiry_ms: int = 0):
    api = XUIAPI()
    try:
        return await api.create_vless_profile(telegram_id, expiry_ms=expiry_ms)
    finally:
        await api.close()


async def create_static_client(profile_name: str, expiry_ms: int = 0):
    api = XUIAPI()
    try:
        return await api.create_static_client(profile_name, expiry_ms=expiry_ms)
    finally:
        await api.close()


async def set_client_subscription_by_email(email: str, expiry_ms: int, enable: bool = True):
    """Синхронизировать срок (мс) и состояние клиента в панели."""
    api = XUIAPI()
    try:
        if not await api.login():
            return False
        return await api.set_client_subscription(email, expiry_ms, enable=enable)
    finally:
        await api.close()


async def delete_client_by_email(email: str):
    api = XUIAPI()
    try:
        if not await api.login():
            return False
        return await api.delete_client(email)
    finally:
        await api.close()


async def enable_client_by_email(email: str):
    api = XUIAPI()
    try:
        if not await api.login():
            return False
        return await api.toggle_client(email, enable=True)
    finally:
        await api.close()


async def disable_client_by_email(email: str):
    api = XUIAPI()
    try:
        if not await api.login():
            return False
        return await api.toggle_client(email, enable=False)
    finally:
        await api.close()


async def get_global_stats():
    api = XUIAPI()
    try:
        if not await api.login():
            return {"upload": 0, "download": 0}
        return await api.get_global_stats()
    finally:
        await api.close()


async def get_online_users():
    api = XUIAPI()
    try:
        if not await api.login():
            return 0
        return await api.get_online_users()
    finally:
        await api.close()


async def get_user_stats(email: str):
    api = XUIAPI()
    try:
        return await api.get_user_stats(email)
    finally:
        await api.close()


async def get_client_links_by_email(email: str) -> list:
    """Готовые ссылки клиента (все инбаунды/протоколы) от панели v3.2.0."""
    api = XUIAPI()
    try:
        if not await api.login():
            return []
        return await api.get_client_links(email)
    finally:
        await api.close()


def generate_vless_url(profile_data: dict) -> str:
    """Ручная сборка VLESS-URL (Reality) — fallback.

    Основной путь в v3.2.0 — ссылки от панели (get_client_links_by_email).
    Оставлено для совместимости/аварийного случая, когда панель недоступна.
    """
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
