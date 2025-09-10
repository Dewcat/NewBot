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
            ("add_damage_system", add_damage_system),
            ("add_status_effects_system", add_status_effects_system),
            ("update_buff_debuff_skills", update_buff_debuff_skills),
            ("update_status_effect_targeting", update_status_effect_targeting),
            ("add_action_system", add_action_system),
            ("add_aoe_skill_system", add_aoe_skill_system),
            ("remove_damage_multiplier", remove_damage_multiplier),
            ("add_emotion_system", add_emotion_system),
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
    """初始迁移"""
    cursor = conn.cursor()
    # 初始化设置，不再创建技能数据
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
        
        conn.commit()
        logger.info("✓ 技能系统更新完成")
    except Exception as e:
        logger.error(f"更新技能系统时出错: {e}")
        conn.rollback()


def add_damage_system(conn):
    """添加伤害类型、抗性和种族系统"""
    cursor = conn.cursor()
    
    try:
        # 检查角色表中需要添加的列
        cursor.execute("PRAGMA table_info(characters)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # 添加物理抗性列
        if 'physical_resistance' not in columns:
            cursor.execute("ALTER TABLE characters ADD COLUMN physical_resistance REAL DEFAULT 0.0")
            logger.info("✓ 添加physical_resistance列")
        
        # 添加魔法抗性列
        if 'magic_resistance' not in columns:
            cursor.execute("ALTER TABLE characters ADD COLUMN magic_resistance REAL DEFAULT 0.0")
            logger.info("✓ 添加magic_resistance列")
        
        # 添加种族标签列（JSON格式存储多个种族）
        if 'race_tags' not in columns:
            cursor.execute("ALTER TABLE characters ADD COLUMN race_tags TEXT DEFAULT '[]'")
            logger.info("✓ 添加race_tags列")
        
        # 检查技能表中需要添加的列
        cursor.execute("PRAGMA table_info(skills)")
        skill_columns = [column[1] for column in cursor.fetchall()]
        
        # 添加伤害类型列（physical, magic）
        if 'damage_type' not in skill_columns:
            cursor.execute("ALTER TABLE skills ADD COLUMN damage_type TEXT DEFAULT 'physical'")
            logger.info("✓ 添加damage_type列")
        
        # 添加特攻标签列（JSON格式存储对哪些种族有特攻）
        if 'special_damage_tags' not in skill_columns:
            cursor.execute("ALTER TABLE skills ADD COLUMN special_damage_tags TEXT DEFAULT '{}'")
            logger.info("✓ 添加special_damage_tags列")
        

        
        conn.commit()
        logger.info("✓ 伤害系统更新完成")
    except Exception as e:
        logger.error(f"更新伤害系统时出错: {e}")
        conn.rollback()

def add_status_effects_system(conn):
    """添加状态效果系统"""
    cursor = conn.cursor()
    
    try:
        logger.info("开始添加状态效果系统...")
        
        # 创建状态效果表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS character_status_effects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id INTEGER NOT NULL,
            effect_type TEXT NOT NULL,  -- buff 或 debuff
            effect_name TEXT NOT NULL,  -- 具体状态名称（如 strong, burn, poison 等）
            intensity INTEGER NOT NULL DEFAULT 1,  -- 强度
            duration INTEGER NOT NULL DEFAULT 1,   -- 层数/持续回合
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (character_id) REFERENCES characters (id) ON DELETE CASCADE
        )
        ''')
        
        # 为技能表添加技能分类字段
        cursor.execute('''
        ALTER TABLE skills ADD COLUMN skill_category TEXT DEFAULT 'damage'
        ''')
        

        

        
        conn.commit()
        logger.info("✓ 状态效果系统添加完成")
    except Exception as e:
        logger.error(f"添加状态效果系统时出错: {e}")
        conn.rollback()

def update_buff_debuff_skills(conn):
    """更新buff/debuff技能设计"""
    cursor = conn.cursor()
    
    try:
        logger.info("开始更新buff/debuff技能...")
        
        conn.commit()
        logger.info("✓ buff/debuff技能更新完成")
    except Exception as e:
        logger.error(f"更新buff/debuff技能时出错: {e}")
        conn.rollback()

def update_status_effect_targeting(conn):
    """更新状态效果目标定义 - 引入self_buff和self_debuff"""
    cursor = conn.cursor()
    logger.info("开始更新状态效果目标定义...")
    
    try:
        conn.commit()
        logger.info("✓ 状态效果目标定义更新完成")
    except Exception as e:
        logger.error(f"更新状态效果目标定义时出错: {e}")
        conn.rollback()

def add_action_system(conn):
    """添加角色行动次数系统"""
    cursor = conn.cursor()
    
    try:
        # 添加行动次数字段
        cursor.execute("""
            ALTER TABLE characters 
            ADD COLUMN actions_per_turn INTEGER DEFAULT 1
        """)
        
        cursor.execute("""
            ALTER TABLE characters 
            ADD COLUMN current_actions INTEGER DEFAULT 1
        """)
        
        # 为现有角色设置默认值
        cursor.execute("""
            UPDATE characters 
            SET actions_per_turn = 1, current_actions = 1 
            WHERE actions_per_turn IS NULL OR current_actions IS NULL
        """)
        
        conn.commit()
        logger.info("✅ 已添加角色行动次数系统")
    except Exception as e:
        logger.error(f"添加行动次数系统时出错: {e}")
        conn.rollback()

def add_haste_cooldown_skills(conn):
    """添加加速和冷却缩减技能"""
    cursor = conn.cursor()
    
    try:
        logger.info("开始添加加速和冷却缩减技能...")
        

        
        conn.commit()
        logger.info("✅ 已添加加速和冷却缩减技能")
    except Exception as e:
        logger.error(f"添加加速和冷却缩减技能时出错: {e}")
        conn.rollback()

def add_aoe_skill_system(conn):
    """添加AOE技能系统"""
    cursor = conn.cursor()
    
    try:
        logger.info("开始添加AOE技能系统...")
        
        conn.commit()
        logger.info("✅ 已添加AOE技能系统")
        
        conn.commit()
        logger.info("✅ 已添加AOE技能系统")
    except Exception as e:
        logger.error(f"添加AOE技能系统时出错: {e}")
        conn.rollback()

def remove_damage_multiplier(conn):
    """移除未使用的damage_multiplier字段"""
    logger.info("开始移除damage_multiplier字段...")
    
    try:
        cursor = conn.cursor()
        
        # 检查是否存在damage_multiplier字段
        cursor.execute("PRAGMA table_info(skills)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'damage_multiplier' not in columns:
            logger.info("damage_multiplier字段不存在，无需移除")
            return
            
        # 创建新的skills表（没有damage_multiplier字段）
        cursor.execute("""
            CREATE TABLE skills_new (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                skill_category TEXT NOT NULL,
                damage_formula TEXT,
                damage_type TEXT,
                special_damage_tags TEXT,
                cooldown INTEGER DEFAULT 0,
                effects TEXT,
                description TEXT
            )
        """)
        
        # 复制数据（不包括damage_multiplier）
        cursor.execute("""
            INSERT INTO skills_new 
            (id, name, skill_category, damage_formula, damage_type, special_damage_tags, cooldown, effects, description)
            SELECT id, name, skill_category, damage_formula, damage_type, special_damage_tags, cooldown, effects, description
            FROM skills
        """)
        
        # 删除旧表并重命名新表
        cursor.execute("DROP TABLE skills")
        cursor.execute("ALTER TABLE skills_new RENAME TO skills")
        
        conn.commit()
        logger.info("✅ 已移除damage_multiplier字段")
    except Exception as e:
        logger.error(f"移除damage_multiplier字段时出错: {e}")
        conn.rollback()

def add_emotion_system(conn):
    """添加情感系统相关表和字段"""
    cursor = conn.cursor()
    
    try:
        logger.info("🎭 开始添加情感系统...")
        
        # 检查characters表是否已有情感系统字段
        cursor.execute("PRAGMA table_info(characters)")
        columns = cursor.fetchall()
        column_names = [column[1] for column in columns]
        
        # 添加情感等级字段
        if "emotion_level" not in column_names:
            cursor.execute("ALTER TABLE characters ADD COLUMN emotion_level INTEGER NOT NULL DEFAULT 0")
            logger.info("✅ 添加了emotion_level字段")
        
        # 添加正面情感硬币字段
        if "positive_emotion_coins" not in column_names:
            cursor.execute("ALTER TABLE characters ADD COLUMN positive_emotion_coins INTEGER NOT NULL DEFAULT 0")
            logger.info("✅ 添加了positive_emotion_coins字段")
        
        # 添加负面情感硬币字段
        if "negative_emotion_coins" not in column_names:
            cursor.execute("ALTER TABLE characters ADD COLUMN negative_emotion_coins INTEGER NOT NULL DEFAULT 0")
            logger.info("✅ 添加了negative_emotion_coins字段")
        
        # 添加待升级状态字段
        if "pending_emotion_upgrade" not in column_names:
            cursor.execute("ALTER TABLE characters ADD COLUMN pending_emotion_upgrade INTEGER NOT NULL DEFAULT 0")
            logger.info("✅ 添加了pending_emotion_upgrade字段")
        
        # 检查skills表是否已有情感等级要求字段
        cursor.execute("PRAGMA table_info(skills)")
        skills_columns = cursor.fetchall()
        skills_column_names = [column[1] for column in skills_columns]
        
        if "required_emotion_level" not in skills_column_names:
            cursor.execute("ALTER TABLE skills ADD COLUMN required_emotion_level INTEGER NOT NULL DEFAULT 0")
            logger.info("✅ 添加了required_emotion_level字段")
        
        # 创建角色情感效果表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS character_emotion_effects (
            id INTEGER PRIMARY KEY,
            character_id INTEGER NOT NULL,
            effect_type TEXT NOT NULL,
            effect_name TEXT NOT NULL,
            intensity INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (character_id) REFERENCES characters (id)
        )
        ''')
        logger.info("✅ 创建了character_emotion_effects表")
        
        # 创建情感等级历史表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS emotion_level_history (
            id INTEGER PRIMARY KEY,
            character_id INTEGER NOT NULL,
            old_level INTEGER NOT NULL,
            new_level INTEGER NOT NULL,
            upgrade_type TEXT NOT NULL,
            positive_coins INTEGER NOT NULL DEFAULT 0,
            negative_coins INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (character_id) REFERENCES characters (id)
        )
        ''')
        logger.info("✅ 创建了emotion_level_history表")
        
        # 创建情感硬币日志表
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS emotion_coin_log (
            id INTEGER PRIMARY KEY,
            character_id INTEGER NOT NULL,
            positive_coins INTEGER NOT NULL DEFAULT 0,
            negative_coins INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL,
            total_after INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (character_id) REFERENCES characters (id)
        )
        ''')
        logger.info("✅ 创建了emotion_coin_log表")
        
        conn.commit()
        logger.info("🎭 情感系统添加完成")
        
    except Exception as e:
        logger.error(f"添加情感系统时出错: {e}")
        conn.rollback()
        raise
