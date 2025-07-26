#!/usr/bin/env python3
"""
测试技能冷却时间系统
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from game.damage_calculator import (
    update_character_cooldowns,
    is_skill_on_cooldown,
    get_skill_cooldown_remaining
)
from database.queries import create_character, get_character, get_skill
import json

def test_cooldown_system():
    """测试冷却时间系统"""
    print("🕐 测试技能冷却时间系统\n")
    
    # 创建测试角色
    char_id = create_character("测试战士", "friendly", 100, 15, 10)
    print(f"创建测试角色，ID: {char_id}")
    
    # 测试技能冷却（使用技能5：快速压制，冷却3回合）
    skill_id = 5
    skill = get_skill(skill_id)
    print(f"技能: {skill['name']} (冷却时间: {skill['cooldown']} 回合)")
    
    # 初始状态
    print(f"\n初始状态:")
    print(f"  技能在冷却中: {is_skill_on_cooldown(char_id, skill_id)}")
    print(f"  剩余冷却时间: {get_skill_cooldown_remaining(char_id, skill_id)} 回合")
    
    # 使用技能
    print(f"\n使用技能...")
    update_character_cooldowns(char_id, skill_id)
    
    print(f"使用后状态:")
    print(f"  技能在冷却中: {is_skill_on_cooldown(char_id, skill_id)}")
    print(f"  剩余冷却时间: {get_skill_cooldown_remaining(char_id, skill_id)} 回合")
    
    # 查看角色状态JSON
    character = get_character(char_id)
    print(f"  角色状态JSON: {character['status']}")
    
    # 模拟几个回合的冷却减少
    for turn in range(1, 5):
        print(f"\n第{turn}回合后（使用其他技能触发冷却减少）:")
        update_character_cooldowns(char_id, 1)  # 使用普通攻击触发冷却减少
        print(f"  技能在冷却中: {is_skill_on_cooldown(char_id, skill_id)}")
        print(f"  剩余冷却时间: {get_skill_cooldown_remaining(char_id, skill_id)} 回合")
        
        character = get_character(char_id)
        print(f"  角色状态JSON: {character['status']}")
        
        if not is_skill_on_cooldown(char_id, skill_id):
            print(f"  ✅ 技能冷却完成，可以再次使用！")
            break

def test_multiple_skills_cooldown():
    """测试多个技能的冷却时间"""
    print("\n\n🔥 测试多技能冷却系统\n")
    
    # 创建另一个测试角色
    char_id = create_character("多技能战士", "friendly", 100, 15, 10)
    print(f"创建测试角色，ID: {char_id}")
    
    # 依次使用多个有冷却的技能
    skills_to_test = [3, 4, 5, 16]  # 不同冷却时间的技能
    
    for skill_id in skills_to_test:
        skill = get_skill(skill_id)
        print(f"\n使用技能: {skill['name']} (冷却{skill['cooldown']}回合)")
        update_character_cooldowns(char_id, skill_id)
        
        # 显示所有技能的冷却状态
        print("  当前所有技能冷却状态:")
        for check_skill_id in skills_to_test:
            remaining = get_skill_cooldown_remaining(char_id, check_skill_id)
            check_skill = get_skill(check_skill_id)
            status = "🔒冷却中" if remaining > 0 else "✅可用"
            print(f"    {check_skill['name']}: {status} ({remaining}回合)")
    
    # 显示最终状态
    character = get_character(char_id)
    print(f"\n最终角色状态JSON: {character['status']}")

if __name__ == "__main__":
    test_cooldown_system()
    test_multiple_skills_cooldown()
