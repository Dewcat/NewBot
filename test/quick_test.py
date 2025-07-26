#!/usr/bin/env python3
import sys
import os
sys.path.append('.')

from database.queries import get_character, reset_all_characters, update_character_health

print("测试重置功能")
char = get_character(1)
if char:
    print(f"重置前 - 角色: {char['name']}, 生命值: {char['health']}/{char['max_health']}")
    
    # 模拟受伤
    update_character_health(1, 10)
    char = get_character(1)
    print(f"受伤后 - 角色: {char['name']}, 生命值: {char['health']}/{char['max_health']}")
    
    # 重置
    reset_all_characters()
    char = get_character(1)
    print(f"重置后 - 角色: {char['name']}, 生命值: {char['health']}/{char['max_health']}")
else:
    print("没有找到角色1")
