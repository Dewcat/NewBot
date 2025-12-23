#!/usr/bin/env python3
"""移除battle_logs表的外键约束"""

import sqlite3
import os
import logging

def remove_battle_logs_foreign_keys():
    """移除battle_logs表的外键约束"""
    
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'dewbot.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("开始移除battle_logs表的外键约束...")
        
        # 1. 创建临时表（没有外键）
        cursor.execute("""
            CREATE TABLE battle_logs_temp (
                id INTEGER PRIMARY KEY,
                attacker_id INTEGER,
                defender_id INTEGER,
                damage INTEGER,
                skill_used INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✅ 创建临时表成功")
        
        # 2. 复制数据
        cursor.execute("""
            INSERT INTO battle_logs_temp (id, attacker_id, defender_id, damage, skill_used, timestamp)
            SELECT id, attacker_id, defender_id, damage, skill_used, timestamp
            FROM battle_logs
        """)
        print("✅ 数据复制成功")
        
        # 3. 删除原表
        cursor.execute("DROP TABLE battle_logs")
        print("✅ 删除原表成功")
        
        # 4. 重命名临时表
        cursor.execute("ALTER TABLE battle_logs_temp RENAME TO battle_logs")
        print("✅ 重命名表成功")
        
        conn.commit()
        print("✅ 移除外键约束完成！")
        
        # 5. 验证新表结构
        cursor.execute('SELECT sql FROM sqlite_master WHERE name="battle_logs"')
        result = cursor.fetchone()
        if result:
            print("\n新的建表语句:")
            print(result[0])
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    remove_battle_logs_foreign_keys()
