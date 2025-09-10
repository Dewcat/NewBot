#!/usr/bin/env python3
"""
测试修改后的情感硬币获取机制
"""

import sys
import os

# 添加项目根目录到路径
sys.path.append('.')

def test_new_emotion_mechanics():
    """测试新的情感硬币获取机制"""
    print("🎭 测试新的情感硬币获取机制...")
    
    try:
        from database.queries import create_character, get_character
        from skill.skill_effects import SkillEffect
        
        # 创建测试角色
        attacker_id = create_character("攻击者", "friendly", 100, 15, 8)
        target_id = create_character("目标", "enemy", 80, 12, 6)
        healer_id = create_character("治疗者", "friendly", 90, 10, 10)
        patient_id = create_character("病人", "friendly", 50, 8, 5)
        
        print(f"创建测试角色: 攻击者({attacker_id}), 目标({target_id}), 治疗者({healer_id}), 病人({patient_id})")
        
        # 创建技能效果实例
        from skill.skill_effects import DefaultSkillEffect
        skill_effect = DefaultSkillEffect()
        
        # 测试伤害情感硬币（基于次数）
        print("\n1. 测试伤害情感硬币获取:")
        attacker = get_character(attacker_id)
        target = get_character(target_id)
        
        # 模拟造成伤害（不管伤害多少，都只获得1个正面硬币）
        damage_messages_1 = skill_effect.process_damage_emotion_coins(attacker, target, 5, False)  # 5点伤害
        damage_messages_2 = skill_effect.process_damage_emotion_coins(attacker, target, 50, False) # 50点伤害
        
        print("造成5点伤害的情感硬币:")
        for msg in damage_messages_1:
            print(f"  {msg}")
        print("造成50点伤害的情感硬币:")
        for msg in damage_messages_2:
            print(f"  {msg}")
            
        # 测试治疗情感硬币
        print("\n2. 测试治疗情感硬币获取:")
        healer = get_character(healer_id)
        patient = get_character(patient_id)
        
        # 模拟治疗他人
        healing_messages = skill_effect.process_healing_emotion_coins(healer, patient, 20)
        print("治疗他人的情感硬币:")
        for msg in healing_messages:
            print(f"  {msg}")
        
        # 模拟自我治疗
        self_healing_messages = skill_effect.process_healing_emotion_coins(healer, healer, 15)
        print("自我治疗的情感硬币:")
        for msg in self_healing_messages:
            print(f"  {msg}")
            
        # 检查最终状态
        print("\n3. 角色最终情感状态:")
        for char_id, name in [(attacker_id, "攻击者"), (target_id, "目标"), (healer_id, "治疗者"), (patient_id, "病人")]:
            char = get_character(char_id)
            print(f"  {name}: 情感等级{char.get('emotion_level', 0)}, "
                  f"正面硬币{char.get('positive_emotion_coins', 0)}, "
                  f"负面硬币{char.get('negative_emotion_coins', 0)}")
        
        print("\n✅ 新情感硬币机制测试完成！")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_new_emotion_mechanics()
