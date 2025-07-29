import sqlite3
import os
import logging
from pathlib import Path

# 配置日志
logger = logging.getLogger(__name__)

# 数据库文件路径
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data', 'simplebot.db')

# 确保数据目录存在
def ensure_data_dir():
    data_dir = os.path.dirname(DB_PATH)
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
        logger.info(f"已创建数据目录: {data_dir}")

# 获取数据库连接
def get_db_connection():
    ensure_data_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 设置行工厂，让行对象表现得像字典
    return conn

# 初始化数据库表
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 创建角色表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS characters (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        character_type TEXT NOT NULL DEFAULT 'friendly', -- 'friendly'表示友方角色，'enemy'表示敌方角色
        in_battle INTEGER NOT NULL DEFAULT 0, -- 0表示未加入战斗，1表示已加入战斗
        health INTEGER NOT NULL DEFAULT 100,
        max_health INTEGER NOT NULL DEFAULT 100,
        attack INTEGER NOT NULL DEFAULT 10,
        defense INTEGER NOT NULL DEFAULT 5,
        status TEXT DEFAULT '{}',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # 创建技能表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        cooldown INTEGER DEFAULT 0
    )
    ''')
    
    # 创建角色技能关联表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS character_skills (
        character_id INTEGER,
        skill_id INTEGER,
        PRIMARY KEY (character_id, skill_id),
        FOREIGN KEY (character_id) REFERENCES characters (id),
        FOREIGN KEY (skill_id) REFERENCES skills (id)
    )
    ''')
    
    # 创建战斗记录表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS battle_logs (
        id INTEGER PRIMARY KEY,
        attacker_id INTEGER,
        defender_id INTEGER,
        damage INTEGER,
        skill_used INTEGER,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (attacker_id) REFERENCES characters (id),
        FOREIGN KEY (defender_id) REFERENCES characters (id),
        FOREIGN KEY (skill_used) REFERENCES skills (id)
    )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("数据库表初始化完成")
