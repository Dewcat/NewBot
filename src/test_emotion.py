#!/usr/bin/env python3
"""
测试情感系统的脚本
"""

import sys
import os

# 添加项目根目录到路径
sys.path.append('.')

def test_emotion_system():
    """测试情感系统基本功能"""
    print("🎭 测试情感系统...")
    
    try:
        from character.emotion_system import add_emotion_coins
        from database.queries import get_character, create_character
        
        # 创建测试角色
        test_char_id = create_character("测试角色", "friendly", 100, 10, 5)
        if not test_char_id:
            print("创建测试角色失败")
            return
            
        print(f"创建测试角色 ID: {test_char_id}")
        
        # 测试添加情感硬币
        result = add_emotion_coins(test_char_id, positive=2, negative=1, source="测试")
        print(f"添加情感硬币结果: {result}")
        
        # 检查角色状态
        char = get_character(test_char_id)
        print(f"角色情感状态:")
        print(f"  情感等级: {char.get('emotion_level', 0)}")
        print(f"  正面硬币: {char.get('positive_emotion_coins', 0)}")
        print(f"  负面硬币: {char.get('negative_emotion_coins', 0)}")
        print(f"  待升级: {char.get('pending_emotion_upgrade', 0)}")
        
        print("✅ 情感系统测试完成！")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_emotion_system()
