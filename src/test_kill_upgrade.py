#!/usr/bin/env python3
"""
测试击杀奖励和升级机制
"""

import sys
import os

# 添加项目根目录到路径
sys.path.append('.')

def test_kill_bonus_and_upgrade():
    """测试击杀奖励和升级机制"""
    print("🎭 测试击杀奖励和升级机制...")
    
    try:
        from database.queries import create_character, get_character
        from skill.skill_effects import DefaultSkillEffect
        from character.emotion_system import process_emotion_upgrades
        
        # 创建测试角色
        killer_id = create_character("杀手", "friendly", 100, 20, 10)
        victim_id = create_character("受害者", "enemy", 100, 10, 5)
        
        print(f"创建测试角色: 杀手({killer_id}), 受害者({victim_id})")
        
        skill_effect = DefaultSkillEffect()
        
        # 模拟击杀（target_died=True）
        killer = get_character(killer_id)
        victim = get_character(victim_id)
        
        kill_messages = skill_effect.process_damage_emotion_coins(killer, victim, 25, True)
        print("\n击杀奖励:")
        for msg in kill_messages:
            print(f"  {msg}")
        
        # 检查击杀者状态
        killer_after = get_character(killer_id)
        print(f"\n击杀后状态:")
        print(f"  杀手: 正面硬币{killer_after.get('positive_emotion_coins', 0)}, "
              f"待升级{killer_after.get('pending_emotion_upgrade', 0)}")
        
        # 如果达到升级要求，测试升级
        if killer_after.get('pending_emotion_upgrade', 0):
            print("\n执行升级:")
            upgrade_messages = process_emotion_upgrades()
            for msg in upgrade_messages:
                print(f"  {msg}")
            
            # 检查升级后状态
            killer_upgraded = get_character(killer_id)
            print(f"\n升级后状态:")
            print(f"  杀手: 情感等级{killer_upgraded.get('emotion_level', 0)}, "
                  f"正面硬币{killer_upgraded.get('positive_emotion_coins', 0)}, "
                  f"负面硬币{killer_upgraded.get('negative_emotion_coins', 0)}")
        
        print("\n✅ 击杀奖励和升级测试完成！")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_kill_bonus_and_upgrade()
