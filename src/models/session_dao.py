import uuid
from datetime import datetime
from src.models.database import get_connection

def create_session(title="新对话"):
    conn = get_connection()
    try:
        session_id = str(uuid.uuid4())
        conn.execute("INSERT INTO sessions (id, title) VALUES (?, ?)", (session_id, title))
        conn.commit()
        return session_id
    finally:
        conn.close()

def get_all_sessions():
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT id, title, updated_at FROM sessions ORDER BY updated_at DESC")
        sessions = [dict(row) for row in cursor.fetchall()]
        return sessions
    finally:
        conn.close()

def delete_session(session_id):
    conn = get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = ON") # 开启外键约束，级联删除消息
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()

def update_session_title(session_id, title):
    conn = get_connection()
    try:
        conn.execute("UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?", 
                     (title, datetime.now(), session_id))
        conn.commit()
    finally:
        conn.close()

def touch_session(session_id):
    """更新会话的最后活跃时间，使其排在列表最前面"""
    conn = get_connection()
    try:
        conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", 
                     (datetime.now(), session_id))
        conn.commit()
    finally:
        conn.close()

def get_session_by_id(session_id):
    """获取单个会话的详细信息（包含 system_prompt）"""
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT id, title, system_prompt, updated_at FROM sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def update_system_prompt(session_id, system_prompt):
    """更新指定会话的系统指令"""
    conn = get_connection()
    try:
        conn.execute("UPDATE sessions SET system_prompt = ? WHERE id = ?", (system_prompt, session_id))
        conn.commit()
    finally:
        conn.close()