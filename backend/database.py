import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

# FIX: connection pool вместо нового подключения на каждый запрос
# minconn=2: всегда держим 2 соединения открытыми
# maxconn=10: максимум 10 одновременных запросов
_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=DATABASE_URL,
            cursor_factory=RealDictCursor,
        )
    return _pool

def get_db():
    """Берёт соединение из пула. Вернуть через release_db()."""
    return get_pool().getconn()

def release_db(conn):
    """Возвращает соединение обратно в пул."""
    get_pool().putconn(conn)

def init_db():
    try:
        conn = get_db()
        cur = conn.cursor()
        print("✅ Подключение к базе данных успешно!")
        cur.close()
        release_db(conn)
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")