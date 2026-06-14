import uuid
from src.models.database import get_connection
from src.models.session_dao import touch_session

def add_message(session_id, role, content):
    conn = get_connection()
    try:
        msg_id = str(uuid.uuid4())
        conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES (?, ?, ?, ?)", 
                     (msg_id, session_id, role, content))
        conn.commit()
        touch_session(session_id) # 每次发消息都更新会话时间
        return msg_id
    finally:
        conn.close()

def get_messages_by_session(session_id):
    conn = get_connection()
    try:
        cursor = conn.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at ASC", 
                              (session_id,))
        messages = [dict(row) for row in cursor.fetchall()]
        return messages
    finally:
        conn.close()

def delete_messages_by_session(session_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()