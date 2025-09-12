#!/usr/bin/env python3
"""移除所有外键约束并清理角色数据"""

import sqlite3
import os

def remove_all_foreign_keys_and_cleanup():
    """移除所有外键约束并清理角色数据"""
    
    db_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'simplebot.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("=== 开始数据库重构 ===")
        
        # 1. 移除character_skills表的外键
        print("\n1. 重构character_skills表...")
        
        cursor.execute("""
            CREATE TABLE character_skills_temp (
                character_id INTEGER,
                skill_id INTEGER,
                PRIMARY KEY (character_id, skill_id)
            )
        """)
        
        cursor.execute("""
            INSERT INTO character_skills_temp (character_id, skill_id)
            SELECT character_id, skill_id FROM character_skills
        """)
        
        cursor.execute("DROP TABLE character_skills")
        cursor.execute("ALTER TABLE character_skills_temp RENAME TO character_skills")
        print("✅ character_skills表外键移除完成")
        
        # 2. 重构character_status_effects表
        print("\n2. 重构character_status_effects表...")
        
        cursor.execute("""
            CREATE TABLE character_status_effects_temp (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                effect_type TEXT NOT NULL,
                effect_name TEXT NOT NULL,
                intensity INTEGER NOT NULL DEFAULT 1,
                duration INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            INSERT INTO character_status_effects_temp 
            (id, character_id, effect_type, effect_name, intensity, duration, created_at)
            SELECT id, character_id, effect_type, effect_name, intensity, duration, created_at
            FROM character_status_effects
        """)
        
        cursor.execute("DROP TABLE character_status_effects")
        cursor.execute("ALTER TABLE character_status_effects_temp RENAME TO character_status_effects")
        print("✅ character_status_effects表外键移除完成")
        
        # 3. 重构character_emotion_effects表
        print("\n3. 重构character_emotion_effects表...")
        
        cursor.execute("""
            CREATE TABLE character_emotion_effects_temp (
                id INTEGER PRIMARY KEY,
                character_id INTEGER NOT NULL,
                effect_type TEXT NOT NULL,
                effect_name TEXT NOT NULL,
                intensity INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            INSERT INTO character_emotion_effects_temp 
            (id, character_id, effect_type, effect_name, intensity, created_at)
            SELECT id, character_id, effect_type, effect_name, intensity, created_at
            FROM character_emotion_effects
        """)
        
        cursor.execute("DROP TABLE character_emotion_effects")
        cursor.execute("ALTER TABLE character_emotion_effects_temp RENAME TO character_emotion_effects")
        print("✅ character_emotion_effects表外键移除完成")
        
        # 4. 重构emotion_level_history表
        print("\n4. 重构emotion_level_history表...")
        
        cursor.execute("""
            CREATE TABLE emotion_level_history_temp (
                id INTEGER PRIMARY KEY,
                character_id INTEGER NOT NULL,
                old_level INTEGER NOT NULL,
                new_level INTEGER NOT NULL,
                upgrade_type TEXT NOT NULL,
                positive_coins INTEGER NOT NULL DEFAULT 0,
                negative_coins INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            INSERT INTO emotion_level_history_temp 
            (id, character_id, old_level, new_level, upgrade_type, positive_coins, negative_coins, created_at)
            SELECT id, character_id, old_level, new_level, upgrade_type, positive_coins, negative_coins, created_at
            FROM emotion_level_history
        """)
        
        cursor.execute("DROP TABLE emotion_level_history")
        cursor.execute("ALTER TABLE emotion_level_history_temp RENAME TO emotion_level_history")
        print("✅ emotion_level_history表外键移除完成")
        
        # 5. 重构emotion_coin_log表
        print("\n5. 重构emotion_coin_log表...")
        
        cursor.execute("""
            CREATE TABLE emotion_coin_log_temp (
                id INTEGER PRIMARY KEY,
                character_id INTEGER NOT NULL,
                positive_coins INTEGER NOT NULL DEFAULT 0,
                negative_coins INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL,
                total_after INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            INSERT INTO emotion_coin_log_temp 
            (id, character_id, positive_coins, negative_coins, source, total_after, created_at)
            SELECT id, character_id, positive_coins, negative_coins, source, total_after, created_at
            FROM emotion_coin_log
        """)
        
        cursor.execute("DROP TABLE emotion_coin_log")
        cursor.execute("ALTER TABLE emotion_coin_log_temp RENAME TO emotion_coin_log")
        print("✅ emotion_coin_log表外键移除完成")
        
        # 6. 清理角色数据（保留ID=1的米拉库尔和ID=41的乌露泽）
        print("\n6. 清理角色数据...")
        
        # 获取要删除的角色ID列表
        cursor.execute("SELECT id FROM characters WHERE id NOT IN (1, 41)")
        characters_to_delete = [row[0] for row in cursor.fetchall()]
        
        if characters_to_delete:
            print(f"将删除 {len(characters_to_delete)} 个角色...")
            
            # 删除相关的数据
            placeholders = ','.join(['?' for _ in characters_to_delete])
            
            # 删除角色技能关联
            cursor.execute(f"DELETE FROM character_skills WHERE character_id IN ({placeholders})", 
                          characters_to_delete)
            
            # 删除角色状态效果
            cursor.execute(f"DELETE FROM character_status_effects WHERE character_id IN ({placeholders})", 
                          characters_to_delete)
            
            # 删除角色情感效果
            cursor.execute(f"DELETE FROM character_emotion_effects WHERE character_id IN ({placeholders})", 
                          characters_to_delete)
            
            # 删除情感等级历史
            cursor.execute(f"DELETE FROM emotion_level_history WHERE character_id IN ({placeholders})", 
                          characters_to_delete)
            
            # 删除情感硬币日志
            cursor.execute(f"DELETE FROM emotion_coin_log WHERE character_id IN ({placeholders})", 
                          characters_to_delete)
            
            # 删除战斗日志
            cursor.execute(f"DELETE FROM battle_logs WHERE attacker_id IN ({placeholders}) OR defender_id IN ({placeholders})", 
                          characters_to_delete + characters_to_delete)
            
            # 最后删除角色本身
            cursor.execute(f"DELETE FROM characters WHERE id IN ({placeholders})", 
                          characters_to_delete)
            
            print(f"✅ 成功删除 {len(characters_to_delete)} 个角色及其相关数据")
        else:
            print("✅ 无需删除角色")
        
        conn.commit()
        print("\n=== 数据库重构完成 ===")
        
        # 7. 验证结果
        print("\n7. 验证重构结果...")
        
        # 检查剩余角色
        cursor.execute("SELECT id, name, character_type FROM characters ORDER BY id")
        remaining_chars = cursor.fetchall()
        print("剩余角色:")
        for char in remaining_chars:
            print(f"  ID: {char[0]}, 名称: {char[1]}, 类型: {char[2]}")
        
        # 检查外键约束
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall() if row[0] != 'sqlite_sequence']
        
        print("\n外键检查:")
        for table in tables:
            cursor.execute(f"SELECT sql FROM sqlite_master WHERE name='{table}'")
            sql = cursor.fetchone()[0]
            if 'FOREIGN KEY' in sql or 'REFERENCES' in sql:
                print(f"  🔴 {table}: 仍有外键")
            else:
                print(f"  ✅ {table}: 无外键")
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    remove_all_foreign_keys_and_cleanup()
