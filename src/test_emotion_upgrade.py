#!/usr/bin/env python3
"""
测试情感系统升级的脚本
"""

import sys
import os

# 添加项目根目录到路径
sys.path.append('.')

def test_emotion_upgrade():
    """测试情感系统升级功能"""
    print("🎭 测试情感升级...")
    
    try:
        from character.emotion_system import process_emotion_upgrades, apply_emotion_effects
        from database.queries import get_character
        
        # 处理所有角色的情感升级
        upgrade_messages = process_emotion_upgrades()
        print("升级消息:")
        for msg in upgrade_messages:
            print(f"  {msg}")
        
        if not upgrade_messages:
            print("  没有角色需要升级")
            return
            
        # 测试应用情感效果
        print("\n测试情感效果应用:")
        test_char_id = 79  # 使用之前创建的测试角色
        char = get_character(test_char_id)
        if char:
            print(f"角色 {char['name']} 当前情感等级: {char.get('emotion_level', 0)}")
            
            effect_messages = apply_emotion_effects(test_char_id)
            print("情感效果:")
            for msg in effect_messages:
                print(f"  {msg}")
        
        print("✅ 情感升级测试完成！")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_emotion_upgrade()
