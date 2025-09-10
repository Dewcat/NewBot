#!/usr/bin/env python3
"""
验证数据库清空状态
"""
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from database.db_connection import get_db_connection

def check_database_status():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 检查各表的记录数量
    tables_to_check = [
        'characters',
        'skills',
        'character_status_effects',
        'character_emotion_effects',
        'emotion_level_history',
        'emotion_coin_log'
    ]
    
    print("=== 数据库状态检查 ===")
    for table in tables_to_check:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"{table}: {count} 条记录")
        except Exception as e:
            print(f"{table}: 检查失败 - {e}")
    
    conn.close()

if __name__ == "__main__":
    check_database_status()
