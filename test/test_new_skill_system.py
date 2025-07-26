#!/usr/bin/env python3
"""
测试新的技能系统和骰子计算
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from game.damage_calculator import (
    parse_dice_formula,
    calculate_damage_from_formula,
    calculate_attack_defense_modifier
)
from database.queries import get_skill

def test_dice_formulas():
    """测试骰子公式解析和计算"""
    print("🎲 测试骰子公式系统\n")
    
    test_formulas = [
        "30+3d10",  # 不死鸟斩
        "15+1d15",  # 蛐蛐  
        "4+3d4",    # 阿拉斯工坊
        "2+3d7",    # 布雷泽工坊
        "5+5d3",    # 快速压制
        "1d6",      # 简单骰子
        "10",       # 固定值
        "3d4+2"     # 骰子+固定值
    ]
    
    for formula in test_formulas:
        print(f"公式: {formula}")
        
        # 解析公式
        base_value, dice_rolls = parse_dice_formula(formula)
        print(f"  解析结果: 基础值={base_value}, 骰子={dice_rolls}")
        
        # 计算伤害（多次测试看随机性）
        print("  计算结果:")
        for i in range(3):
            damage, detail = calculate_damage_from_formula(formula)
            print(f"    第{i+1}次: {detail} = {damage} 点伤害")
        print()

def test_attack_defense_modifier():
    """测试攻防差值计算"""
    print("⚔️ 测试攻防差值系统\n")
    
    test_cases = [
        (10, 5),   # 攻击力10，防御力5，差值+5
        (5, 10),   # 攻击力5，防御力10，差值-5  
        (15, 15),  # 攻击力15，防御力15，差值0
        (20, 5),   # 攻击力20，防御力5，差值+15
        (3, 15),   # 攻击力3，防御力15，差值-12
    ]
    
    for attack, defense in test_cases:
        modifier = calculate_attack_defense_modifier(attack, defense)
        diff = attack - defense
        print(f"攻击力{attack} vs 防御力{defense}")
        print(f"  差值: {diff:+d}")
        print(f"  伤害倍率: {modifier:.2f} ({modifier*100:.0f}%)")
        print(f"  示例: 10点基础伤害 → {int(10 * modifier)} 点实际伤害")
        print()

def test_skill_data():
    """测试技能数据读取"""
    print("📋 测试技能数据\n")
    
    skill_ids = [1, 7, 16]  # 测试几个技能
    
    for skill_id in skill_ids:
        skill = get_skill(skill_id)
        if skill:
            print(f"技能ID {skill_id}: {skill['name']}")
            print(f"  描述: {skill['description']}")
            print(f"  伤害公式: {skill.get('damage_formula', '未设置')}")
            print(f"  冷却时间: {skill.get('cooldown', 0)} 回合")
            print(f"  特殊效果: {skill.get('effects', '{}')}")
            print()
        else:
            print(f"技能ID {skill_id}: 未找到")
            print()

def simulate_battle():
    """模拟一次完整的战斗计算"""
    print("🥊 模拟战斗计算\n")
    
    # 模拟角色数据
    attacker = {'name': '勇士', 'attack': 15, 'defense': 8}
    target = {'name': '哥布林', 'attack': 8, 'defense': 12}
    
    # 模拟技能
    skill = get_skill(1)  # 不死鸟斩
    if skill:
        print(f"攻击者: {attacker['name']} (攻击{attacker['attack']}, 防御{attacker['defense']})")
        print(f"目标: {target['name']} (攻击{target['attack']}, 防御{target['defense']})")
        print(f"使用技能: {skill['name']} ({skill['damage_formula']})")
        print()
        
        # 计算攻防差值修正
        modifier = calculate_attack_defense_modifier(attacker['attack'], target['defense'])
        print(f"攻防差值: {attacker['attack']} - {target['defense']} = {attacker['attack'] - target['defense']}")
        print(f"伤害修正: {modifier:.2f}")
        print()
        
        # 计算伤害
        base_damage, detail = calculate_damage_from_formula(skill['damage_formula'])
        final_damage = int(base_damage * modifier)
        final_damage = max(1, final_damage)  # 至少1点伤害
        
        print(f"骰子结果: {detail} = {base_damage} 点基础伤害")
        print(f"应用修正: {base_damage} × {modifier:.2f} = {final_damage} 点最终伤害")
    else:
        print("无法获取技能数据")

if __name__ == "__main__":
    test_dice_formulas()
    print("-" * 50)
    test_attack_defense_modifier()
    print("-" * 50)
    test_skill_data()
    print("-" * 50)
    simulate_battle()
