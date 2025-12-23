"""
情感系统数据库迁移
添加情感等级、情感硬币、技能情感等级限制等字段
"""
import sqlite3
import os

def get_db_path():
    """获取数据库路径"""
    return os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'dewbot.db')

def upgrade():
    """升级数据库结构以支持情感系统"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 为characters表添加情感系统字段
        cursor.execute('''
            ALTER TABLE characters ADD COLUMN emotion_level INTEGER DEFAULT 0
        ''')
        print("✅ 添加characters.emotion_level字段")
        
        cursor.execute('''
            ALTER TABLE characters ADD COLUMN positive_emotion_coins INTEGER DEFAULT 0
        ''')
        print("✅ 添加characters.positive_emotion_coins字段")
        
        cursor.execute('''
            ALTER TABLE characters ADD COLUMN negative_emotion_coins INTEGER DEFAULT 0
        ''')
        print("✅ 添加characters.negative_emotion_coins字段")
        
        cursor.execute('''
            ALTER TABLE characters ADD COLUMN pending_emotion_upgrade INTEGER DEFAULT 0
        ''')
        print("✅ 添加characters.pending_emotion_upgrade字段")
        
        # 为skills表添加情感等级限制字段
        cursor.execute('''
            ALTER TABLE skills ADD COLUMN required_emotion_level INTEGER DEFAULT 0
        ''')
        print("✅ 添加skills.required_emotion_level字段")
        
        # 创建情感效果表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS character_emotion_effects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                effect_type TEXT NOT NULL,
                effect_name TEXT NOT NULL,
                intensity INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (character_id) REFERENCES characters (id) ON DELETE CASCADE
            )
        ''')
        print("✅ 创建character_emotion_effects表")
        
        # 创建情感升级历史表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS emotion_level_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character_id INTEGER NOT NULL,
                old_level INTEGER NOT NULL,
                new_level INTEGER NOT NULL,
                upgrade_type TEXT NOT NULL,
                positive_coins INTEGER DEFAULT 0,
                negative_coins INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (character_id) REFERENCES characters (id) ON DELETE CASCADE
            )
        ''')
        print("✅ 创建emotion_level_history表")
        
        conn.commit()
        print("🎉 情感系统数据库迁移完成！")
        
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("⚠️ 字段已存在，跳过重复添加")
        else:
            conn.rollback()
            raise e
    except Exception as e:
        conn.rollback()
        print(f"❌ 数据库迁移失败: {e}")
        raise
    finally:
        conn.close()

def downgrade():
    """回滚情感系统相关更改"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 删除新创建的表
        cursor.execute('DROP TABLE IF EXISTS character_emotion_effects')
        cursor.execute('DROP TABLE IF EXISTS emotion_level_history')
        
        # SQLite不支持DROP COLUMN，需要重建表来移除字段
        # 这里只提供删除表的回滚，字段删除需要手动处理
        print("⚠️ 注意：SQLite不支持删除列，需要手动重建表来完全回滚")
        
        conn.commit()
        print("🔄 情感系统数据库回滚完成（部分）")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ 数据库回滚失败: {e}")
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    upgrade()
