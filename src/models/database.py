import sqlite3
import os
import sys

# 【修复】判断是否为 PyInstaller 打包环境
if getattr(sys, 'frozen', False):
    # 如果是打包后的 exe，BASE_DIR 为 exe 所在目录
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 如果是开发环境，BASE_DIR 为项目根目录
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

DB_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DB_DIR, 'chat.db')

def get_connection():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row 
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
        )
    ''')
    
    # 【核心新增】数据迁移：检查并添加 system_prompt 字段，兼容旧数据库
    cursor.execute("PRAGMA table_info(sessions)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'system_prompt' not in columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN system_prompt TEXT DEFAULT ''")
        
    conn.commit()
    conn.close()

# 程序启动时自动初始化
init_db()