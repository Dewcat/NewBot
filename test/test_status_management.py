#!/usr/bin/env python3
"""
测试新增的状态管理功能
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from database.queries import create_character, get_character, update_character_health, reset_all_characters, remove_all_from_battle
from character.status_formatter import format_character_status, format_character_list, format_battle_participants
from game.damage_calculator import update_character_cooldowns

def test_character_status_formatting():
    """测试角色状态格式化"""
    print("📋 测试角色状态格式化功能\n")
    
    # 创建测试角色
    char_id = create_character("测试勇士", "friendly", 75, 15, 10)
    
    # 添加一些冷却时间
    update_character_cooldowns(char_id, 5)  # 使用冷却3回合的技能
    update_character_cooldowns(char_id, 3)  # 使用冷却1回合的技能
    
    character = get_character(char_id)
    
    print("格式化后的角色状态:")
    print(format_character_status(character))
    print()

def test_auto_remove_from_battle():
    """测试生命值归0自动移出战斗"""
    print("💀 测试生命值归0自动移出战斗\n")
    
    # 创建测试角色并加入战斗
    char_id = create_character("濒死战士", "friendly", 50, 10, 5)
    
    from database.queries import set_character_battle_status
    set_character_battle_status(char_id, True)
    
    character = get_character(char_id)
    print(f"加入战斗前: {character['name']} 生命值 {character['health']}, 战斗状态: {'在战斗中' if character['in_battle'] else '未参战'}")
    
    # 将生命值设为0
    update_character_health(char_id, 0)
    
    character = get_character(char_id)
    print(f"生命值归0后: {character['name']} 生命值 {character['health']}, 战斗状态: {'在战斗中' if character['in_battle'] else '未参战'}")
    
    # 显示格式化状态
    print("\n格式化状态显示:")
    print(format_character_status(character))
    print()

def test_character_list_formatting():
    """测试角色列表格式化"""
    print("📝 测试角色列表格式化\n")
    
    # 创建几个不同状态的角色
    char1_id = create_character("健康战士", "friendly", 100, 15, 10)
    char2_id = create_character("受伤法师", "friendly", 30, 12, 8)
    char3_id = create_character("邪恶哥布林", "enemy", 80, 8, 6)
    
    # 设置不同的战斗状态
    from database.queries import set_character_battle_status
    set_character_battle_status(char1_id, True)
    set_character_battle_status(char3_id, True)
    
    # 模拟一个角色受伤到濒死
    update_character_health(char2_id, 5)
    
    from database.queries import get_characters_by_type
    
    print("友方角色列表（简要格式）:")
    friendly_chars = get_characters_by_type("friendly")
    print(format_character_list(friendly_chars, show_details=False))
    
    print("\n敌方角色列表（详细格式）:")
    enemy_chars = get_characters_by_type("enemy")
    print(format_character_list(enemy_chars, show_details=True))
    print()

def test_battle_participants():
    """测试战斗参与者显示"""
    print("⚔️ 测试战斗参与者显示\n")
    
    print("当前战斗参与者:")
    print(format_battle_participants())
    print()

def test_reset_functions():
    """测试重置功能"""
    print("🔄 测试重置功能\n")
    
    print("重置前角色状态:")
    from database.queries import get_characters_by_type
    all_chars = get_characters_by_type("friendly") + get_characters_by_type("enemy")
    print(format_character_list(all_chars, show_details=False))
    
    print(f"\n执行 reset_all_characters()...")
    count = reset_all_characters()
    print(f"重置了 {count} 个角色")
    
    print("\n重置后角色状态:")
    all_chars = get_characters_by_type("friendly") + get_characters_by_type("enemy")
    print(format_character_list(all_chars, show_details=False))
    
    print("\n重置后战斗参与者:")
    print(format_battle_participants())

if __name__ == "__main__":
    test_character_status_formatting()
    print("-" * 50)
    test_auto_remove_from_battle()
    print("-" * 50)
    test_character_list_formatting()
    print("-" * 50)
    test_battle_participants()
    print("-" * 50)
    test_reset_functions()
