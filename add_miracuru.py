#!/usr/bin/env python3
"""
添加米拉库尔角色和她的独特技能
"""

import sys
import os
import json
import sqlite3

# 添加src目录到Python路径
sys.path.append('/Users/dew/PythonWorkspace/NewBot/src')

from database.db_connection import get_db_connection
from database.queries import create_character

def add_miracuru():
    """添加米拉库尔角色"""
    
    # 连接数据库
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        print("🌑 开始添加米拉库尔角色...")
        
        # 1. 添加角色
        cursor.execute("""
            INSERT OR REPLACE INTO characters (
                name, character_type, health, max_health, 
                attack, defense, in_battle, 
                physical_resistance, magic_resistance,
                emotion_level, positive_emotion_coins, negative_emotion_coins,
                actions_per_turn, current_actions,
                status, race_tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "米拉库尔", "friendly", 200, 200,  # 名称，类型，生命值
            20, 10, 0,  # 攻击，防御，战斗状态
            0.0, 0.0,  # 物理抗性，魔法抗性（普通人类无特殊抗性）
            0, 0, 0,  # 情感系统（初始0级）
            1, 1,  # 每回合1次行动（标准设置）
            '{}',  # status字段：空JSON对象，用于存储buff/debuff
            '人类'  # 种族标签（普通人类）
        ))
        
        character_id = cursor.lastrowid
        print(f"✅ 米拉库尔角色已创建，ID: {character_id}")
        
        # 2. 添加技能：生于黑夜
        cursor.execute("""
            INSERT OR REPLACE INTO skills (
                name, description, cooldown, damage_formula, 
                effects, damage_type, skill_category, required_emotion_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "生于黑夜",
            "展开黑夜领域，赋予自身666枚负面情感硬币，并为自身附加1级6层黑夜领域效果",
            666,  # 冷却666回合
            "",   # 无伤害公式
            json.dumps({
                "status": [
                    {
                        "effect": "dark_domain",
                        "turns": 6,
                        "value": 1,
                        "target": "self"
                    }
                ]
            }),
            "",  # 无伤害类型
            "self_buff",  # 自我增益
            0  # 无情感需求
        ))
        
        skill_id_1 = cursor.lastrowid
        print(f"✅ 技能'生于黑夜'已创建，ID: {skill_id_1}")
        
        # 3. 添加技能：暗黑
        cursor.execute("""
            INSERT OR REPLACE INTO skills (
                name, description, cooldown, damage_formula, 
                effects, damage_type, skill_category, required_emotion_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "暗黑",
            "基础的魔法攻击",
            0,  # 无冷却
            "6d6",  # 伤害：6d6
            "{}",  # 无附加效果
            "magic",  # 魔法伤害
            "damage",  # 伤害技能
            0  # 无情感需求
        ))
        
        skill_id_2 = cursor.lastrowid
        print(f"✅ 技能'暗黑'已创建，ID: {skill_id_2}")
        
        # 4. 添加技能：兽之数
        cursor.execute("""
            INSERT OR REPLACE INTO skills (
                name, description, cooldown, damage_formula, 
                effects, damage_type, skill_category, required_emotion_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "兽之数",
            "若自身拥有黑夜领域层数，追加6d6魔法伤害",
            6,  # 冷却6回合
            "6d6",  # 基础伤害：6d6
            json.dumps({
                "conditional_damage": {
                    "condition": "self_has_dark_domain",
                    "damage_formula": "6d6",
                    "damage_type": "magic",
                    "target": "skill_target"
                }
            }),
            "magic",  # 魔法伤害
            "damage",  # 伤害技能
            0  # 无情感需求
        ))
        
        skill_id_3 = cursor.lastrowid
        print(f"✅ 技能'兽之数'已创建，ID: {skill_id_3}")
        
        # 5. 添加技能：深恶痛绝
        cursor.execute("""
            INSERT OR REPLACE INTO skills (
                name, description, cooldown, damage_formula, 
                effects, damage_type, skill_category, required_emotion_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "深恶痛绝",
            "使目标敌方获得1级6层易伤和1级6层虚弱",
            6,  # 冷却6回合
            "",   # 无伤害公式
            json.dumps({
                "status": [
                    {
                        "effect": "vulnerable",
                        "turns": 6,
                        "value": 1,
                        "target": "skill_target"
                    },
                    {
                        "effect": "weak",
                        "turns": 6,
                        "value": 1,
                        "target": "skill_target"
                    }
                ]
            }),
            "",  # 无伤害类型
            "debuff",  # 减益技能
            0  # 无情感需求
        ))
        
        skill_id_4 = cursor.lastrowid
        print(f"✅ 技能'深恶痛绝'已创建，ID: {skill_id_4}")
        
        # 6. 添加技能：长夜终尽
        cursor.execute("""
            INSERT OR REPLACE INTO skills (
                name, description, cooldown, damage_formula, 
                effects, damage_type, skill_category, required_emotion_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "长夜终尽",
            "对所有敌人造成巨大魔法伤害，自身受到造成的100%伤害",
            666,  # 冷却666回合
            "66+6d6",  # 伤害：66+6d6
            json.dumps({
                "damage": {
                    "target": "self",
                    "percentage": 100
                }
            }),
            "magic",  # 魔法伤害
            "aoe_damage",  # 群体伤害技能
            5  # 需要5级情感
        ))
        
        skill_id_5 = cursor.lastrowid
        print(f"✅ 技能'长夜终尽'已创建，ID: {skill_id_5}")
        
        # 7. 将技能分配给米拉库尔
        skills_to_assign = [skill_id_1, skill_id_2, skill_id_3, skill_id_4, skill_id_5]
        
        for skill_id in skills_to_assign:
            cursor.execute("""
                INSERT OR REPLACE INTO character_skills (character_id, skill_id)
                VALUES (?, ?)
            """, (character_id, skill_id))
        
        print(f"✅ 已为米拉库尔分配 {len(skills_to_assign)} 个技能")
        
        conn.commit()
        print("🌑 米拉库尔角色和技能创建完成！")
        
        # 显示角色信息
        cursor.execute("SELECT * FROM characters WHERE id = ?", (character_id,))
        character = cursor.fetchone()
        print(f"\n📋 角色信息:")
        print(f"   名称: {character[1]}")
        print(f"   类型: {character[2]}")
        print(f"   生命值: {character[4]}/{character[5]}")
        print(f"   攻击/防御: {character[6]}/{character[7]}")
        print(f"   种族标签: {character[12] if len(character) > 12 else '无'}")
        
        # 显示技能列表
        cursor.execute("""
            SELECT s.name, s.description, s.cooldown, s.damage_formula
            FROM skills s
            JOIN character_skills cs ON s.id = cs.skill_id
            WHERE cs.character_id = ?
        """, (character_id,))
        
        skills = cursor.fetchall()
        print(f"\n⚔️ 技能列表:")
        for skill in skills:
            print(f"   • {skill[0]}: {skill[1]}")
            if skill[3]:
                print(f"     伤害: {skill[3]}")
            print(f"     冷却: {skill[2]}回合")
            print()
        
    except Exception as e:
        conn.rollback()
        print(f"❌ 创建米拉库尔时出错: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        conn.close()

if __name__ == "__main__":
    add_miracuru()
