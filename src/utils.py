"""Общие утилиты, переиспользуемые в нескольких модулях.

Сюда вынесены мелкие хелперы, которые раньше дублировались между app.py и
handlers.py (например, конвертация срока подписки панели ↔ datetime).
"""
from datetime import datetime, timezone

# Зеркало «безлимита»: панель кодирует его как expiryTime == 0, а в БД бота
# мы храним конкретную дальнюю дату, чтобы сравнения дат работали единообразно.
UNLIMITED_END = datetime(2099, 1, 1)


def _ms_to_dt(ms):
    """Unix epoch в мс → naive-UTC datetime. 0/пусто → дальняя дата (безлимит)."""
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        ms = 0
    if ms <= 0:
        return UNLIMITED_END
    return datetime.utcfromtimestamp(ms / 1000)


def _to_epoch_ms(dt) -> int:
    """Naive-UTC datetime → Unix epoch в миллисекундах (0, если dt пуст)."""
    if not dt:
        return 0
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
