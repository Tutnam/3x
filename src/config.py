import os
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from typing import List, Dict

load_dotenv()

class Config(BaseModel):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMINS: List[int] = Field(default_factory=list)
    XUI_API_URL: str = os.getenv("XUI_API_URL", "http://localhost:54321")
    XUI_BASE_PATH: str = os.getenv("XUI_BASE_PATH", "/panel")
    XUI_USERNAME: str = os.getenv("XUI_USERNAME", "admin")
    XUI_PASSWORD: str = os.getenv("XUI_PASSWORD", "admin")
    XUI_HOST: str = os.getenv("XUI_HOST", "your-server.com")
    XUI_SERVER_NAME: str = os.getenv("XUI_SERVER_NAME", "domain.com")
    VLESS_PUBLIC_HOST: str = os.getenv("VLESS_PUBLIC_HOST", "")
    VLESS_PUBLIC_PORT: int = Field(default=os.getenv("VLESS_PUBLIC_PORT", ""))
    PAYMENT_TOKEN: str = os.getenv("PAYMENT_TOKEN", "")
    INBOUND_ID: int = Field(default=os.getenv("INBOUND_ID", 1))
    REALITY_PUBLIC_KEY: str = os.getenv("REALITY_PUBLIC_KEY", "")
    REALITY_FINGERPRINT: str = os.getenv("REALITY_FINGERPRINT", "chrome")
    REALITY_SNI: str = os.getenv("REALITY_SNI", "example.com")
    REALITY_SHORT_ID: str = os.getenv("REALITY_SHORT_ID", "1234567890")
    REALITY_SPIDER_X: str = os.getenv("REALITY_SPIDER_X", "/")
    REALITY_FLOW: str = os.getenv("REALITY_FLOW", "")
    VLESS_ENCRYPTION: str = os.getenv("VLESS_ENCRYPTION", "none")
    
    # Настройки subscription сервера
    SUBSCRIPTION_HOST: str = os.getenv("SUBSCRIPTION_HOST", "0.0.0.0")
    SUBSCRIPTION_PORT: int = Field(default=os.getenv("SUBSCRIPTION_PORT", 35635))
    SUBSCRIPTION_BASE_URL: str = os.getenv("SUBSCRIPTION_BASE_URL", "http://localhost:35635")

    # Настройки цен и скидок
    PRICES: Dict[int, Dict[str, int]] = {
        1: {"base_price": 150, "discount_percent": 0},
        3: {"base_price": 450, "discount_percent": 10},
        6: {"base_price": 900, "discount_percent": 20},
        12: {"base_price": 1800, "discount_percent": 30}
    }

    @field_validator('ADMINS', mode='before')
    def parse_admins(cls, value):
        if isinstance(value, str):
            return [int(admin) for admin in value.split(",") if admin.strip()]
        return value or []
    
    @field_validator('INBOUND_ID', mode='before')
    def parse_inbound_id(cls, value):
        if isinstance(value, str):
            return int(value)
        return value or 15

    @field_validator('VLESS_PUBLIC_PORT', mode='before')
    def parse_vless_public_port(cls, value):
        if value is None:
            return 0
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return 0
            return int(value)
        return int(value) if value else 0
    
    @field_validator('SUBSCRIPTION_PORT', mode='before')
    def parse_subscription_port(cls, value):
        if value is None:
            return 35635
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return 35635
            return int(value)
        return int(value) if value else 35635
    
    def calculate_price(self, months: int) -> int:
        """Вычисляет итоговую стоимость с учетом скидки"""
        if months not in self.PRICES:
            return 0
        
        price_info = self.PRICES[months]
        base_price = price_info["base_price"]
        discount_percent = price_info["discount_percent"]
        
        discount_amount = (base_price * discount_percent) // 100
        return base_price - discount_amount

config = Config(
    ADMINS=os.getenv("ADMINS", ""),
    INBOUND_ID=os.getenv("INBOUND_ID", 15)
)

def validate_config():
    """Проверяет наличие обязательных переменных окружения"""
    errors = []
    
    if not config.BOT_TOKEN:
        errors.append("BOT_TOKEN - токен Telegram бота")
    
    if not config.XUI_API_URL or config.XUI_API_URL == "http://localhost:54321":
        errors.append("XUI_API_URL - URL панели 3x-UI")
    
    if not config.XUI_HOST or config.XUI_HOST == "your-server.com":
        errors.append("XUI_HOST - адрес VPN сервера")
    
    if not config.REALITY_PUBLIC_KEY:
        errors.append("REALITY_PUBLIC_KEY - публичный ключ Reality")
    
    if errors:
        print("\n" + "="*50)
        print("❌ ОШИБКА КОНФИГУРАЦИИ")
        print("="*50)
        print("\nНе заданы обязательные переменные окружения:")
        for error in errors:
            print(f"  • {error}")
        print("\nПроверьте файл .env и добавьте недостающие значения.")
        print("Пример можно найти в .env.example")
        print("="*50 + "\n")
        raise SystemExit(1)

# Выполняем валидацию при импорте модуля
validate_config()