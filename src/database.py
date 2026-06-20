from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, func, or_
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timedelta
import logging
import os
import glob
import sqlite3

logger = logging.getLogger(__name__)

DB_PATH = 'users.db'

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    full_name = Column(String)
    username = Column(String)
    registration_date = Column(DateTime, default=datetime.utcnow)
    subscription_end = Column(DateTime)
    vless_profile_data = Column(String)
    subscription_id = Column(String, unique=True)  # Уникальный ID для subscription URL
    is_admin = Column(Boolean, default=False)
    notify_stage = Column(Integer, default=0)  # 0=нет, 1=за 3д, 2=за 24ч, 3=истекло (#17)

class StaticProfile(Base):
    __tablename__ = 'static_profiles'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    vless_url = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Payment(Base):
    """Запись об успешной оплате (для учёта выручки, #18).

    Раньше платежи нигде не сохранялись — только уведомление админу. Теперь
    каждый successful_payment пишется сюда. telegram_charge_id уникален —
    защита от повторной доставки платежа Telegram (идемпотентность)."""
    __tablename__ = 'payments'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, index=True)
    amount = Column(Integer)                      # в рублях (final_price)
    currency = Column(String, default='RUB')
    months = Column(Integer)
    payload = Column(String)
    telegram_charge_id = Column(String, unique=True)
    provider_charge_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

engine = create_engine('sqlite:///users.db', echo=False)
Session = sessionmaker(bind=engine)

async def init_db():
    Base.metadata.create_all(engine)
    logger.info("✅ Database tables created")


def backup_database(backup_dir: str = "backups", keep: int = 7) -> str:
    """Создаёт согласованную копию users.db через SQLite backup API
    (безопасно даже при активной записи) и оставляет последние `keep` копий.

    Возвращает путь к созданному бэкапу. Запускать через asyncio.to_thread —
    операция блокирующая.
    """
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d")
    dest = os.path.join(backup_dir, f"users.db.{stamp}")

    src = sqlite3.connect(DB_PATH)
    try:
        dst = sqlite3.connect(dest)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    # Ротация: оставляем только `keep` самых свежих бэкапов
    backups = sorted(glob.glob(os.path.join(backup_dir, "users.db.*")))
    for old in backups[:-keep]:
        try:
            os.remove(old)
        except OSError as e:
            logger.warning(f"⚠️ Failed to remove old backup {old}: {e}")

    return dest

async def get_user(telegram_id: int):
    with Session() as session:
        return session.query(User).filter_by(telegram_id=telegram_id).first()

async def get_user_by_subscription_id(subscription_id: str):
    """Получение пользователя по subscription ID"""
    with Session() as session:
        return session.query(User).filter_by(subscription_id=subscription_id).first()

async def create_user(telegram_id: int, full_name: str, username: str = None, is_admin: bool = False):
    with Session() as session:
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            username=username,
            subscription_end=datetime.utcnow() + timedelta(days=3),
            is_admin=is_admin
        )
        session.add(user)
        session.commit()
        logger.info(f"✅ New user created: {telegram_id}")
        return user

async def delete_user_profile(telegram_id: int):
    with Session() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            user.vless_profile_data = None
            user.notify_stage = 0
            session.commit()
            logger.info(f"✅ User profile deleted: {telegram_id}")

async def get_all_users(with_subscription: bool = None):
    with Session() as session:
        query = session.query(User)
        if with_subscription is not None:
            if with_subscription:
                query = query.filter(User.subscription_end > datetime.utcnow())
            else:
                query = query.filter(or_(User.subscription_end == None, User.subscription_end <= datetime.utcnow()))
        return query.all()

async def create_static_profile(name: str, vless_url: str):
    with Session() as session:
        profile = StaticProfile(name=name, vless_url=vless_url)
        session.add(profile)
        session.commit()
        logger.info(f"✅ Static profile created: {name}")
        return profile

async def get_static_profiles():
    with Session() as session:
        return session.query(StaticProfile).all()

async def get_user_stats():
    with Session() as session:
        total = session.query(func.count(User.id)).scalar()
        with_sub = session.query(func.count(User.id)).filter(User.subscription_end > datetime.utcnow()).scalar()
        without_sub = total - with_sub
        return total, with_sub, without_sub


# --------------------------------------------------------------------------
# Платежи / выручка (#18)
# --------------------------------------------------------------------------

async def record_payment(telegram_id: int, amount: int, months: int, payload: str,
                         telegram_charge_id: str = None, provider_charge_id: str = None,
                         currency: str = 'RUB'):
    """Сохраняет успешный платёж. Идемпотентно по telegram_charge_id.

    Возвращает (payment, is_new): is_new=False, если платёж с таким
    telegram_charge_id уже записан (повторная доставка Telegram) — вызывающий
    код по этому флагу НЕ начисляет время/бонусы повторно."""
    with Session() as session:
        if telegram_charge_id:
            existing = session.query(Payment).filter_by(telegram_charge_id=telegram_charge_id).first()
            if existing:
                logger.info(f"ℹ️  Payment {telegram_charge_id} already recorded, skipping")
                return existing, False
        payment = Payment(
            telegram_id=telegram_id,
            amount=amount,
            currency=currency,
            months=months,
            payload=payload,
            telegram_charge_id=telegram_charge_id,
            provider_charge_id=provider_charge_id,
        )
        session.add(payment)
        session.commit()
        session.refresh(payment)
        session.expunge(payment)
        logger.info(f"✅ Payment recorded: {telegram_id} {amount}{currency} ({months}m)")
        return payment, True


async def get_revenue_stats() -> dict:
    """Сводка выручки: за сегодня, за текущий месяц и за всё время (сумма + кол-во)."""
    now = datetime.utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with Session() as session:
        def _sum(q):
            return int(q.with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar() or 0)
        def _cnt(q):
            return int(q.with_entities(func.count(Payment.id)).scalar() or 0)
        all_q = session.query(Payment)
        month_q = session.query(Payment).filter(Payment.created_at >= month_start)
        day_q = session.query(Payment).filter(Payment.created_at >= day_start)
        return {
            "today_total": _sum(day_q), "today_count": _cnt(day_q),
            "month_total": _sum(month_q), "month_count": _cnt(month_q),
            "all_total": _sum(all_q), "all_count": _cnt(all_q),
        }