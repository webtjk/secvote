import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    try:
        conn = get_db()
        cur = conn.cursor()
        print("✅ Подключение к базе данных успешно!")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")