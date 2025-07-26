#!/usr/bin/env python3
"""
完整的战斗系统测试
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from database.queries import create_character, get_character, get_skill, add_skill_to_character
from skill.skill_effects import skill_registry
from game.damage_calculator import is_skill_on_cooldown
import json

def test_complete_battle():
    """测试完整的战斗流程"""
    print("⚔️ 完整战斗系统测试\n")
    
    # 创建测试角色
    attacker_id = create_character("勇士阿尔法", "friendly", 100, 20, 10)
    target_id = create_character("邪恶哥布林", "enemy", 80, 12, 8)
    
    # 给攻击者添加一些技能
    skills_to_add = [1, 3, 7, 16]  # 不死鸟斩, 阿拉斯工坊, 净化, 碎片万段
    for skill_id in skills_to_add:
        add_skill_to_character(attacker_id, skill_id)
    
    print("🏗️ 战斗准备")
    attacker = get_character(attacker_id)
    target = get_character(target_id)
    
    print(f"攻击者: {attacker['name']} (生命:{attacker['health']}/{attacker['max_health']}, 攻击:{attacker['attack']}, 防御:{attacker['defense']})")
    print(f"目标: {target['name']} (生命:{target['health']}/{target['max_health']}, 攻击:{target['attack']}, 防御:{target['defense']})")
    
    print(f"\n📋 攻击者技能列表:")
    for skill_id in skills_to_add:
        skill = get_skill(skill_id)
        print(f"  - {skill['name']}: {skill['damage_formula']} (冷却:{skill['cooldown']}回合)")
    
    # 进行多轮战斗测试
    round_num = 1
    skills_to_use = [1, 3, 16, 7, 1]  # 测试序列：不死鸟斩->阿拉斯工坊->碎片万段->净化->不死鸟斩
    
    for skill_id in skills_to_use:
        print(f"\n🔄 第{round_num}回合")
        print("-" * 40)
        
        # 重新获取角色状态
        attacker = get_character(attacker_id)
        target = get_character(target_id)
        
        if target['health'] <= 0:
            print(f"💀 {target['name']} 已被击败！战斗结束。")
            break
        
        # 检查技能冷却状态
        skill = get_skill(skill_id)
        if is_skill_on_cooldown(attacker_id, skill_id):
            print(f"🔒 {skill['name']} 还在冷却中，改用普通攻击")
            skill = get_skill(1)  # 改用普通攻击
            skill_id = 1
        
        print(f"🎯 {attacker['name']} 使用 {skill['name']}")
        print(f"   当前状态: 生命{attacker['health']}/{attacker['max_health']}")
        print(f"   目标状态: 生命{target['health']}/{target['max_health']}")
        
        # 执行技能
        result = skill_registry.execute_skill(attacker, target, skill)
        
        print(f"   结果: {result['result_text']}")
        
        # 检查目标生命值
        target = get_character(target_id)
        if result['total_damage'] < 0:  # 治疗
            attacker = get_character(attacker_id)  # 治疗会影响攻击者
            print(f"   攻击者新状态: 生命{attacker['health']}/{attacker['max_health']}")
        else:
            print(f"   目标新状态: 生命{target['health']}/{target['max_health']}")
        
        # 显示冷却状态
        cooldowns_info = []
        for check_skill_id in skills_to_add:
            if is_skill_on_cooldown(attacker_id, check_skill_id):
                check_skill = get_skill(check_skill_id)
                cooldowns_info.append(f"{check_skill['name']}(冷却中)")
        
        if cooldowns_info:
            print(f"   冷却状态: {', '.join(cooldowns_info)}")
        else:
            print(f"   冷却状态: 所有技能可用")
        
        round_num += 1
    
    print(f"\n🏁 战斗结束总结")
    attacker = get_character(attacker_id)
    target = get_character(target_id)
    print(f"最终状态:")
    print(f"  {attacker['name']}: {attacker['health']}/{attacker['max_health']} 生命值")
    print(f"  {target['name']}: {target['health']}/{target['max_health']} 生命值")
    
    if target['health'] <= 0:
        print(f"🏆 {attacker['name']} 获得胜利！")
    else:
        print(f"⚔️ 战斗继续进行中...")

def test_special_effects():
    """测试特殊效果"""
    print("\n\n✨ 特殊效果测试\n")
    
    # 创建测试角色
    healer_id = create_character("牧师", "friendly", 50, 10, 5)  # 低血量测试治疗
    target_id = create_character("训练假人", "enemy", 100, 5, 20)  # 高防御测试攻防差值
    
    # 添加净化技能
    add_skill_to_character(healer_id, 7)
    
    print("🔮 治疗技能测试")
    healer = get_character(healer_id)
    print(f"治疗前: {healer['name']} 生命值 {healer['health']}/{healer['max_health']}")
    
    skill = get_skill(7)  # 净化技能
    result = skill_registry.execute_skill(healer, healer, skill)  # 治疗技能目标是自己
    
    healer = get_character(healer_id)
    print(f"治疗效果: {result['result_text']}")
    print(f"治疗后: {healer['name']} 生命值 {healer['health']}/{healer['max_health']}")
    
    print(f"\n🛡️ 攻防差值极端情况测试")
    attacker = get_character(healer_id)
    target = get_character(target_id)
    
    print(f"攻击者: 攻击{attacker['attack']}, 目标: 防御{target['defense']}")
    print(f"攻防差值: {attacker['attack'] - target['defense']} (预期伤害减少)")
    
    skill = get_skill(1)  # 不死鸟斩
    result = skill_registry.execute_skill(attacker, target, skill)
    
    print(f"攻击结果: {result['result_text']}")

if __name__ == "__main__":
    test_complete_battle()
    test_special_effects()
