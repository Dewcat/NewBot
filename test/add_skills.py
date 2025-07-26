#!/usr/bin/env python3
import sys
import os
sys.path.append('.')

from database.db_connection import get_db_connection

def add_missing_skills():
    """根据用户提供的图片数据添加缺失的技能"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 从图片中的技能数据
    skills_from_image = [
        (1, "不死鸟斩", "强力的斩击技能", "30+3d10", 0, "{}"),
        (2, "蛐蛐", "快速轻击", "15+1d15", 0, "{}"),
        (3, "阿拉斯工坊", "精密攻击", "4+3d4", 1, "{}"),
        (4, "布雷泽工坊", "重型攻击", "2+3d7", 2, "{}"),
        (5, "快速压制", "连续压制攻击", "5+5d3", 3, "{}"),
        (6, "攻击", "基础攻击技能", "3+2d4", 1, "{}"),
        (7, "净化", "恢复生命值", "30+3d12", 0, '{"heal": true}'),
        (8, "宠物狗斗", "召唤宠物攻击", "20+4d5", 2, "{}"),
        (9, "放松肌肉", "缓解压力的攻击", "3+2d4", 1, "{}"),
        (10, "再来再来！", "激励性攻击", "7+3d3", 0, "{}"),
        (11, "链锯剑", "锯齿攻击", "10+1d8", 0, "{}"),
        (12, "镇压", "压制性攻击", "5+2d6", 1, "{}"),
        (13, "纵斩", "垂直斩击", "2+2d8", 2, "{}"),
        (14, "利刃封喉", "精准致命攻击", "10+1d2", 0, "{}"),
        (15, "入身尖刀", "近身攻击", "3+3d5", 1, "{}"),
        (16, "碎片万段", "爆炸性攻击", "5+1d25", 3, "{}"),
    ]
    
    # 先清理现有技能
    cursor.execute("DELETE FROM skills")
    
    # 插入新技能
    for skill_id, name, description, damage_formula, cooldown, effects in skills_from_image:
        cursor.execute("""
            INSERT INTO skills (id, name, description, damage_multiplier, cooldown, damage_formula, effects)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (skill_id, name, description, 1.0, cooldown, damage_formula, effects))
    
    conn.commit()
    conn.close()
    print("✓ 已添加16个技能到数据库")

if __name__ == "__main__":
    add_missing_skills()
