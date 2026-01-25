import asyncio
import sys
sys.path.insert(0, 'src')

from database import get_user_by_subscription_id
from datetime import datetime

async def test():
    subscription_id = "nVWKHDpd7tFmtuhAXo4vbw"
    
    print(f"Тестирую subscription_id: {subscription_id}")
    
    user = await get_user_by_subscription_id(subscription_id)
    
    if not user:
        print("❌ Пользователь не найден")
        return
    
    print(f"✅ Пользователь найден: {user.telegram_id}")
    print(f"   Имя: {user.full_name}")
    print(f"   subscription_end: {user.subscription_end}")
    print(f"   Тип subscription_end: {type(user.subscription_end)}")
    print(f"   vless_profile_data: {user.vless_profile_data is not None}")
    
    # Проверяем активность подписки
    if not user.subscription_end:
        print("❌ subscription_end пустой")
    else:
        now = datetime.utcnow()
        print(f"   Текущее время: {now}")
        print(f"   Подписка активна: {user.subscription_end > now}")
        
        if user.subscription_end < now:
            print("❌ Подписка истекла")
        else:
            print("✅ Подписка активна")

if __name__ == "__main__":
    asyncio.run(test())
