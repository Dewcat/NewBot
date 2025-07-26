#!/usr/bin/env python3
"""
最终状态管理功能演示
"""

import sys
import os
sys.path.append('.')

from database.queries import (
    create_character, get_character, update_character_health, 
    reset_all_characters, remove_all_from_battle,
    set_character_battle_status, get_characters_by_type
)
from character.status_formatter import (
    format_character_status, format_character_list, format_battle_participants
)
from game.damage_calculator import update_character_cooldowns

def demo_all_features():
    """演示所有新功能"""
    print("🎭 SimpleBot 状态管理功能演示\n")
    
    # 1. 清理并创建演示角色
    print("1️⃣ 清理数据并创建演示角色")
    reset_all_characters()
    
    warrior_id = create_character("勇敢战士", "friendly", 100, 18, 12)
    mage_id = create_character("智慧法师", "friendly", 80, 15, 8)
    goblin_id = create_character("邪恶哥布林", "enemy", 60, 12, 6)
    
    print("✅ 创建了3个演示角色\n")
    
    # 2. 展示格式化的角色状态
    print("2️⃣ 角色状态格式化显示")
    warrior = get_character(warrior_id)
    print(format_character_status(warrior))
    print()
    
    # 3. 添加技能冷却并显示
    print("3️⃣ 添加技能冷却时间")
    update_character_cooldowns(warrior_id, 16)  # 碎片万段，冷却3回合
    update_character_cooldowns(warrior_id, 3)   # 阿拉斯工坊，冷却1回合
    
    warrior = get_character(warrior_id)
    print("使用技能后的状态:")
    print(format_character_status(warrior))
    print()
    
    # 4. 角色受伤和加入战斗
    print("4️⃣ 角色受伤并加入战斗")
    update_character_health(mage_id, 25)  # 法师受重伤
    set_character_battle_status(warrior_id, True)
    set_character_battle_status(mage_id, True) 
    set_character_battle_status(goblin_id, True)
    
    print("战斗状态:")
    print(format_battle_participants())
    print()
    
    # 5. 模拟角色死亡（自动移出战斗）
    print("5️⃣ 模拟角色死亡（自动移出战斗）")
    print("击败哥布林...")
    update_character_health(goblin_id, 0)  # 哥布林死亡
    
    print("死亡后的战斗状态:")
    print(format_battle_participants())
    
    goblin = get_character(goblin_id)
    print("哥布林当前状态:")
    print(format_character_status(goblin))
    print()
    
    # 6. 显示角色列表
    print("6️⃣ 角色列表显示")
    all_friendly = get_characters_by_type("friendly")
    all_enemy = get_characters_by_type("enemy")
    
    print("友方角色:")
    print(format_character_list(all_friendly, show_details=False))
    print("\n敌方角色:")
    print(format_character_list(all_enemy, show_details=False))
    print()
    
    # 7. 测试重置功能
    print("7️⃣ 重置所有角色")
    count = reset_all_characters()
    print(f"重置了 {count} 个角色")
    
    print("重置后状态:")
    all_chars = get_characters_by_type("friendly") + get_characters_by_type("enemy")
    print(format_character_list(all_chars, show_details=False))
    
    print("\n重置后战斗参与者:")
    print(format_battle_participants())
    
    print("\n🎉 所有功能演示完成！")

if __name__ == "__main__":
    demo_all_features()
