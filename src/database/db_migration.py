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
        
        # 更新现有角色的种族标签
        character_race_updates = [
            # 这里可以为现有角色设置一些默认种族
            # 格式: (character_id, race_tags_json)
        ]
        
        # 更新现有技能的伤害类型和特攻
        skill_damage_updates = [
            (1, 'physical', '{}'),  # 不死鸟斩 - 物理攻击
            (2, 'magic', '{}'),     # 蛐蛐 - 魔法攻击
            (3, 'physical', '{"machine": 1.5}'),  # 阿拉斯工坊 - 对机械特攻
            (4, 'magic', '{}'),     # 布雷泽工坊 - 魔法攻击
            (5, 'physical', '{}'),  # 快速压制 - 物理攻击
            (6, 'physical', '{}'),  # 攻击 - 物理攻击
            (7, 'magic', '{}'),     # 净化 - 魔法治疗
            (8, 'physical', '{"beast": 1.3}'),  # 宠物狗斗 - 对野兽特攻
            (9, 'physical', '{}'),  # 放松肌肉 - 物理攻击
            (10, 'physical', '{}'), # 再来再来！- 物理攻击
            (11, 'physical', '{"machine": 1.4}'),  # 链锯剑 - 对机械特攻
            (12, 'physical', '{}'), # 镇压 - 物理攻击
            (13, 'physical', '{}'), # 纵斩 - 物理攻击
            (14, 'physical', '{"human": 1.6}'),  # 利刃封喉 - 对人类特攻
            (15, 'physical', '{}'), # 入身尖刀 - 物理攻击
            (16, 'magic', '{"dragon": 2.0}'),   # 碎片万段 - 对龙特攻
        ]
        
        for skill_id, damage_type, special_tags in skill_damage_updates:
            cursor.execute("""
                UPDATE skills 
                SET damage_type = ?, special_damage_tags = ? 
                WHERE id = ?
            """, (damage_type, special_tags, skill_id))
        
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
        
        # 更新现有技能的分类
        skill_category_updates = [
            (7, 'healing'),   # 净化 - 治疗技能
            (1, 'damage'),    # 普通攻击 - 伤害技能
            (2, 'damage'),    # 火球 - 伤害技能
            (3, 'damage'),    # 冰箭 - 伤害技能
            (4, 'damage'),    # 闪电 - 伤害技能
            (5, 'damage'),    # 地震 - 伤害技能
            (6, 'damage'),    # 风刃 - 伤害技能
            (8, 'damage'),    # 疾风剑法 - 伤害技能
            (9, 'damage'),    # 放松肌肉 - 伤害技能
            (10, 'damage'),   # 再来再来！- 伤害技能
            (11, 'damage'),   # 链锯剑 - 伤害技能
            (12, 'damage'),   # 镇压 - 伤害技能
            (13, 'damage'),   # 纵斩 - 伤害技能
            (14, 'damage'),   # 利刃封喉 - 伤害技能
            (15, 'damage'),   # 入身尖刀 - 伤害技能
            (16, 'damage'),   # 碎片万段 - 伤害技能
        ]
        
        for skill_id, category in skill_category_updates:
            cursor.execute("""
                UPDATE skills 
                SET skill_category = ? 
                WHERE id = ?
            """, (category, skill_id))
        
        # 添加一些增益减益技能示例
        status_skills = [
            # 伴随伤害的技能（damage类型 + 附带状态效果）
            (17, '强壮打击', 'damage', '1d8', 'physical', '{}', 5, '{"buff": {"type": "strong", "intensity": 3, "duration": 3}}'),
            (19, '烧伤攻击', 'damage', '1d6', 'magic', '{}', 4, '{"debuff": {"type": "burn", "intensity": 5, "duration": 3}}'),
            (20, '中毒箭', 'damage', '1d4', 'physical', '{}', 4, '{"debuff": {"type": "poison", "intensity": 15, "duration": 2}}'),
            
            # 纯增益技能（buff类型，不造成伤害）
            (18, '守护祝福', 'buff', '0', 'none', '{}', 3, '{"buff": {"type": "guard", "intensity": 2, "duration": 4}}'),
            (23, '呼吸法', 'buff', '0', 'none', '{}', 2, '{"buff": {"type": "breathing", "intensity": 10, "duration": 5}}'),
            (24, '护盾术', 'buff', '0', 'magic', '{}', 4, '{"buff": {"type": "shield", "intensity": 30, "duration": 999}}'),
            (25, '强化术', 'buff', '0', 'magic', '{}', 3, '{"buff": {"type": "strong", "intensity": 2, "duration": 5}}'),
            
            # 纯减益技能（debuff类型，不造成伤害）
            (21, '虚弱诅咒', 'debuff', '0', 'magic', '{}', 3, '{"debuff": {"type": "weak", "intensity": 2, "duration": 3}}'),
            (22, '易伤标记', 'debuff', '0', 'magic', '{}', 3, '{"debuff": {"type": "vulnerable", "intensity": 1, "duration": 4}}'),
            (26, '恐惧术', 'debuff', '0', 'magic', '{}', 4, '{"debuff": {"type": "weak", "intensity": 3, "duration": 2}}'),
            (27, '破甲诅咒', 'debuff', '0', 'magic', '{}', 3, '{"debuff": {"type": "vulnerable", "intensity": 2, "duration": 3}}'),
        ]
        
        for skill_id, name, category, formula, damage_type, special_tags, cooldown, effects in status_skills:
            cursor.execute("""
                INSERT OR IGNORE INTO skills 
                (id, name, skill_category, damage_formula, damage_type, special_damage_tags, cooldown, effects) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (skill_id, name, category, formula, damage_type, special_tags, cooldown, effects))
        
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
        
        # 删除旧的状态效果技能
        cursor.execute("DELETE FROM skills WHERE id >= 17 AND id <= 27")
        
        # 添加新设计的状态效果技能
        status_skills = [
            # 伴随伤害的技能（damage类型 + 附带状态效果）
            (17, '强壮打击', 'damage', '1d8', 'physical', '{}', 5, '{"buff": {"type": "strong", "intensity": 3, "duration": 3}}'),
            (19, '烧伤攻击', 'damage', '1d6', 'magic', '{}', 4, '{"debuff": {"type": "burn", "intensity": 5, "duration": 3}}'),
            (20, '中毒箭', 'damage', '1d4', 'physical', '{}', 4, '{"debuff": {"type": "poison", "intensity": 15, "duration": 2}}'),
            
            # 纯增益技能（buff类型，不造成伤害）
            (18, '守护祝福', 'buff', '0', 'none', '{}', 3, '{"buff": {"type": "guard", "intensity": 2, "duration": 4}}'),
            (23, '呼吸法', 'buff', '0', 'none', '{}', 2, '{"buff": {"type": "breathing", "intensity": 10, "duration": 5}}'),
            (24, '护盾术', 'buff', '0', 'magic', '{}', 4, '{"buff": {"type": "shield", "intensity": 30, "duration": 999}}'),
            (25, '强化术', 'buff', '0', 'magic', '{}', 3, '{"buff": {"type": "strong", "intensity": 2, "duration": 5}}'),
            
            # 纯减益技能（debuff类型，不造成伤害）
            (21, '虚弱诅咒', 'debuff', '0', 'magic', '{}', 3, '{"debuff": {"type": "weak", "intensity": 2, "duration": 3}}'),
            (22, '易伤标记', 'debuff', '0', 'magic', '{}', 3, '{"debuff": {"type": "vulnerable", "intensity": 1, "duration": 4}}'),
            (26, '恐惧术', 'debuff', '0', 'magic', '{}', 4, '{"debuff": {"type": "weak", "intensity": 3, "duration": 2}}'),
            (27, '破甲诅咒', 'debuff', '0', 'magic', '{}', 3, '{"debuff": {"type": "vulnerable", "intensity": 2, "duration": 3}}'),
        ]
        
        for skill_id, name, category, formula, damage_type, special_tags, cooldown, effects in status_skills:
            cursor.execute("""
                INSERT OR REPLACE INTO skills 
                (id, name, skill_category, damage_formula, damage_type, special_damage_tags, cooldown, effects) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (skill_id, name, category, formula, damage_type, special_tags, cooldown, effects))
        
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
        # 更新技能效果定义
        # 按照新的逻辑：
        # - self_buff/self_debuff: 施加给施法者自己
        # - buff/debuff: 施加给目标
        
        status_skill_updates = [
            # 伴随型技能 - 这些技能原本的buff效果应该改为self_buff
            (17, '强壮打击', '{"self_buff": {"type": "strong", "intensity": 3, "duration": 3}}'),  # 伤害+自己获得强壮
            
            # 伴随型治疗技能 - 治疗时给自己的增益效果改为self_buff
            (23, '呼吸法', '{"heal": true, "self_buff": {"type": "breathing", "intensity": 10, "duration": 5}}'),  # 治疗+自己获得呼吸法
            
            # 伴随型攻击技能 - 这些技能的debuff效果应该施加给目标，保持为debuff
            (1, '不死鸟斩', '{"debuff": {"type": "burn", "intensity": 5, "duration": 3}}'),  # 伤害+目标烧伤
            (19, '烧伤攻击', '{"debuff": {"type": "burn", "intensity": 5, "duration": 3}}'),  # 伤害+目标烧伤  
            (20, '中毒箭', '{"debuff": {"type": "poison", "intensity": 15, "duration": 2}}'),  # 伤害+目标中毒
            
            # 纯增益技能 - 这些技能的buff效果施加给目标，保持为buff
            (18, '守护祝福', '{"buff": {"type": "guard", "intensity": 2, "duration": 4}}'),  # 给目标守护
            (24, '护盾术', '{"buff": {"type": "shield", "intensity": 30, "duration": 999}}'),  # 给目标护盾
            (25, '强化术', '{"buff": {"type": "strong", "intensity": 2, "duration": 5}}'),  # 给目标强壮
            
            # 纯减益技能 - 这些技能的debuff效果施加给目标，保持为debuff  
            (21, '虚弱诅咒', '{"debuff": {"type": "weak", "intensity": 2, "duration": 3}}'),  # 给目标虚弱
            (22, '易伤标记', '{"debuff": {"type": "vulnerable", "intensity": 1, "duration": 4}}'),  # 给目标易伤
            (26, '恐惧术', '{"debuff": {"type": "weak", "intensity": 3, "duration": 2}}'),  # 给目标虚弱
            (27, '破甲诅咒', '{"debuff": {"type": "vulnerable", "intensity": 2, "duration": 3}}'),  # 给目标易伤
        ]
        
        for skill_id, name, effects in status_skill_updates:
            cursor.execute("UPDATE skills SET effects = ? WHERE id = ?", (effects, skill_id))
            logger.info(f"✓ 更新技能 {name} (ID: {skill_id}) 的效果定义")
        
        # 添加一些演示新系统的技能
        demo_skills = [
            # 演示所有四种效果类型的技能
            (28, '四重奥秘', 'damage', '2d6+2', 'magic', '{}', 6, 
             '{"self_buff": {"type": "strong", "intensity": 1, "duration": 2}, "self_debuff": {"type": "weak", "intensity": 1, "duration": 1}, "buff": {"type": "guard", "intensity": 1, "duration": 2}, "debuff": {"type": "vulnerable", "intensity": 1, "duration": 2}}'),
            
            # 自我强化攻击 - 攻击时给自己增益
            (29, '狂怒攻击', 'damage', '1d8+3', 'physical', '{}', 3,
             '{"self_buff": {"type": "strong", "intensity": 2, "duration": 3}}'),
            
            # 自我削弱治疗 - 治疗时给自己减益（代价型技能）
            (30, '生命转移', 'healing', '3d6', 'magic', '{}', 4,
             '{"heal": true, "self_debuff": {"type": "weak", "intensity": 1, "duration": 2}}'),
        ]
        
        for skill_id, name, category, formula, damage_type, special_tags, cooldown, effects in demo_skills:
            cursor.execute("""
                INSERT OR REPLACE INTO skills 
                (id, name, skill_category, damage_formula, damage_type, special_damage_tags, cooldown, effects) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (skill_id, name, category, formula, damage_type, special_tags, cooldown, effects))
            logger.info(f"✓ 添加演示技能 {name} (ID: {skill_id})")
        
        conn.commit()
        logger.info("✓ 状态效果目标定义更新完成")
    except Exception as e:
        logger.error(f"更新状态效果目标定义时出错: {e}")
        conn.rollback()
