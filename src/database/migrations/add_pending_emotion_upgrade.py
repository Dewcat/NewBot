"""
添加pending_emotion_upgrade字段
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database.db_connection import get_db_connection
import logging

logger = logging.getLogger(__name__)

def upgrade():
    """添加pending_emotion_upgrade字段到characters表"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 检查字段是否已存在
        cursor.execute("PRAGMA table_info(characters)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'pending_emotion_upgrade' not in columns:
            cursor.execute("""
                ALTER TABLE characters 
                ADD COLUMN pending_emotion_upgrade INTEGER DEFAULT 0
            """)
            logger.info("已添加pending_emotion_upgrade字段")
        else:
            logger.info("pending_emotion_upgrade字段已存在")
        
        conn.commit()
        return True
        
    except Exception as e:
        logger.error(f"添加pending_emotion_upgrade字段失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    upgrade()
