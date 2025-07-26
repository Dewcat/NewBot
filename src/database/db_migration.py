import logging
import sqlite3
from .db_connection import get_db_connection, init_db

logger = logging.getLogger(__name__)

def run_migrations():
    """运行所有数据库迁移"""
    try:
        # 初始化数据库表结构
        init_db()
        
        # 获取数据库连接
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 创建迁移记录表（如果不存在）
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS migrations (
            id INTEGER PRIMARY KEY,
            migration_name TEXT NOT NULL UNIQUE,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # 运行迁移
        migrations = [
            ("initial_setup", initial_setup),
            ("add_character_type_and_battle_status", add_character_type_and_battle_status),
            ("remove_user_id_column", remove_user_id_column),
            ("update_skill_system", update_skill_system),
            # 将来可以在这里添加更多迁移
        ]
        
        for name, migration_func in migrations:
            # 检查迁移是否已经应用
            cursor.execute("SELECT COUNT(*) FROM migrations WHERE migration_name = ?", (name,))
            if cursor.fetchone()[0] == 0:
                logger.info(f"应用迁移: {name}")
                migration_func(conn)
                cursor.execute("INSERT INTO migrations (migration_name) VALUES (?)", (name,))
                conn.commit()
            else:
                logger.info(f"迁移已经应用: {name}")
        
        conn.close()
        logger.info("所有迁移已完成")
    except Exception as e:
        logger.error(f"迁移过程中出错: {e}")
        raise

def initial_setup(conn):
    """初始迁移 - 添加一些基础技能数据"""
    cursor = conn.cursor()
    
    # 添加基础技能
    base_skills = [
        (1, "普通攻击", "基础的物理攻击", 1.0, 0),
        (2, "强力一击", "造成1.5倍伤害的强力攻击", 1.5, 3),
        (3, "连击", "造成0.8倍伤害的两次连续攻击", 0.8, 2),
        (4, "暴击", "有30%几率造成2倍伤害", 2.0, 5)
    ]
    
    cursor.executemany(
        "INSERT OR IGNORE INTO skills (id, name, description, damage_multiplier, cooldown) VALUES (?, ?, ?, ?, ?)",
        base_skills
    )
    
    conn.commit()

def add_character_type_and_battle_status(conn):
    """添加角色类型和战斗状态列"""
    cursor = conn.cursor()
    
    # 检查character_type列是否已存在
    cursor.execute("PRAGMA table_info(characters)")
    columns = cursor.fetchall()
    column_names = [column[1] for column in columns]
    
    if "character_type" not in column_names:
        cursor.execute("ALTER TABLE characters ADD COLUMN character_type TEXT NOT NULL DEFAULT 'friendly'")
        logger.info("添加了character_type列")
    
    if "in_battle" not in column_names:
        cursor.execute("ALTER TABLE characters ADD COLUMN in_battle INTEGER NOT NULL DEFAULT 0")
        logger.info("添加了in_battle列")
    
    # 将现有角色标记为友方角色
    cursor.execute("UPDATE characters SET character_type = 'friendly' WHERE character_type IS NULL")
    
    conn.commit()

def remove_user_id_column(conn):
    """移除user_id列，简化角色管理"""
    cursor = conn.cursor()
    
    # SQLite不直接支持删除列，需要通过创建临时表并复制数据来实现
    try:
        # 1. 创建一个新表，不包含user_id列
        cursor.execute('''
        CREATE TABLE characters_new (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            character_type TEXT NOT NULL DEFAULT 'friendly',
            in_battle INTEGER NOT NULL DEFAULT 0,
            health INTEGER NOT NULL DEFAULT 100,
            max_health INTEGER NOT NULL DEFAULT 100,
            attack INTEGER NOT NULL DEFAULT 10,
            defense INTEGER NOT NULL DEFAULT 5,
            status TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # 2. 将原表数据复制到新表
        cursor.execute('''
        INSERT INTO characters_new (
            id, name, character_type, in_battle, health, max_health, attack, defense, status, created_at
        ) SELECT 
            id, name, character_type, in_battle, health, max_health, attack, defense, status, created_at 
        FROM characters
        ''')
        
        # 3. 删除原表
        cursor.execute("DROP TABLE characters")
        
        # 4. 将新表重命名为原表名
        cursor.execute("ALTER TABLE characters_new RENAME TO characters")
        
        logger.info("成功移除user_id列 - 角色不再与特定用户绑定，任何人都可以控制所有角色")
        conn.commit()
    except Exception as e:
        logger.error(f"移除user_id列时出错: {e}")
        conn.rollback()

def update_skill_system(conn):
    """更新技能系统：添加damage_formula, cooldown, effects列"""
    cursor = conn.cursor()
    
    try:
        # 检查是否需要添加新列
        cursor.execute("PRAGMA table_info(skills)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # 添加damage_formula列
        if 'damage_formula' not in columns:
            cursor.execute("ALTER TABLE skills ADD COLUMN damage_formula TEXT DEFAULT '1d6'")
            logger.info("✓ 添加damage_formula列")
        
        # 添加cooldown列
        if 'cooldown' not in columns:
            cursor.execute("ALTER TABLE skills ADD COLUMN cooldown INTEGER DEFAULT 0")
            logger.info("✓ 添加cooldown列")
        
        # 添加effects列
        if 'effects' not in columns:
            cursor.execute("ALTER TABLE skills ADD COLUMN effects TEXT DEFAULT '{}'")
            logger.info("✓ 添加effects列")
        
        # 更新现有技能的新字段，基于提供的数据库图片
        skill_updates = [
            (1, '30+3d10', 0, '{}'),  # 不死鸟斩
            (2, '15+1d15', 0, '{}'),  # 蛐蛐
            (3, '4+3d4', 1, '{}'),   # 阿拉斯工坊
            (4, '2+3d7', 2, '{}'),   # 布雷泽工坊
            (5, '5+5d3', 3, '{}'),   # 快速压制
            (6, '3+2d4', 1, '{}'),   # 攻击
            (7, '30+3d12', 0, '{"heal": true}'),  # 净化（治疗技能）
            (8, '20+4d5', 2, '{}'),  # 宠物狗斗
            (9, '3+2d4', 1, '{}'),   # 放松肌肉
            (10, '7+3d3', 0, '{}'),  # 再来再来！
            (11, '10+1d8', 0, '{}'), # 链锯剑
            (12, '5+2d6', 1, '{}'),  # 镇压
            (13, '2+2d8', 2, '{}'),  # 纵斩
            (14, '10+1d2', 0, '{}'), # 利刃封喉
            (15, '3+3d5', 1, '{}'),  # 入身尖刀
            (16, '5+1d25', 3, '{}'), # 碎片万段
        ]
        
        for skill_id, formula, cooldown, effects in skill_updates:
            cursor.execute("""
                UPDATE skills 
                SET damage_formula = ?, cooldown = ?, effects = ? 
                WHERE id = ?
            """, (formula, cooldown, effects, skill_id))
        
        conn.commit()
        logger.info("✓ 技能系统更新完成")
    except Exception as e:
        logger.error(f"更新技能系统时出错: {e}")
        conn.rollback()
