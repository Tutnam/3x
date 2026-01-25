#!/usr/bin/env python3
"""
Скрипт миграции базы данных для добавления поля subscription_id
Использует метод пересоздания таблицы для SQLite
"""
import sqlite3
import sys

def migrate_database():
    try:
        # Подключаемся к БД
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        
        # Проверяем, существует ли уже колонка
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'subscription_id' in columns:
            print("✅ Колонка subscription_id уже существует")
            conn.close()
            return True
        
        print("ℹ️  Начинаем миграцию...")
        
        # Шаг 1: Создаём новую таблицу с обновлённой схемой
        print("1️⃣  Создаём новую таблицу...")
        cursor.execute("""
            CREATE TABLE users_new (
                id INTEGER PRIMARY KEY,
                telegram_id INTEGER UNIQUE,
                full_name TEXT,
                username TEXT,
                registration_date TIMESTAMP,
                subscription_end TIMESTAMP,
                vless_profile_id TEXT,
                vless_profile_data TEXT,
                subscription_id TEXT UNIQUE,
                is_admin BOOLEAN,
                notified BOOLEAN
            )
        """)
        
        # Шаг 2: Копируем данные из старой таблицы
        print("2️⃣  Копируем данные из старой таблицы...")
        cursor.execute("""
            INSERT INTO users_new (
                id, telegram_id, full_name, username, registration_date,
                subscription_end, vless_profile_id, vless_profile_data,
                is_admin, notified
            )
            SELECT 
                id, telegram_id, full_name, username, registration_date,
                subscription_end, vless_profile_id, vless_profile_data,
                is_admin, notified
            FROM users
        """)
        
        # Шаг 3: Удаляем старую таблицу
        print("3️⃣  Удаляем старую таблицу...")
        cursor.execute("DROP TABLE users")
        
        # Шаг 4: Переименовываем новую таблицу
        print("4️⃣  Переименовываем новую таблицу...")
        cursor.execute("ALTER TABLE users_new RENAME TO users")
        
        conn.commit()
        print("✅ Миграция успешно завершена!")
        
        # Проверяем результат
        cursor.execute("PRAGMA table_info(users)")
        columns = [column[1] for column in cursor.fetchall()]
        print(f"📋 Колонки в таблице users: {', '.join(columns)}")
        
        # Проверяем количество записей
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]
        print(f"👥 Количество пользователей: {count}")
        
        conn.close()
        return True
        
    except sqlite3.Error as e:
        print(f"❌ Ошибка миграции: {e}")
        conn.rollback()
        return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        return False

if __name__ == "__main__":
    print("🔄 Запуск миграции базы данных...")
    
    # Создаём резервную копию
    import shutil
    try:
        shutil.copy2('users.db', 'users.db.backup')
        print("✅ Резервная копия создана: users.db.backup")
    except Exception as e:
        print(f"⚠️  Не удалось создать резервную копию: {e}")
        response = input("Продолжить без резервной копии? (y/n): ")
        if response.lower() != 'y':
            print("❌ Миграция отменена")
            sys.exit(1)
    
    # Выполняем миграцию
    if migrate_database():
        print("\n✅ Миграция завершена успешно!")
        print("Теперь можно запустить бота: python src/app.py")
        sys.exit(0)
    else:
        print("\n❌ Миграция не удалась")
        print("Восстановите БД из резервной копии: cp users.db.backup users.db")
        sys.exit(1)
