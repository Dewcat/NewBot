#!/usr/bin/env python3
import sys
import os
sys.path.append('.')

from database.queries import get_character

# 获取最新创建的角色
char = get_character(17)  # 勇敢战士的ID应该是17
if char:
    print(f"角色: {char['name']}")
    print(f"生命值: {char['health']}")
    print(f"最大生命值: {char['max_health']}")
    print(f"攻击力: {char['attack']}")
    print(f"防御力: {char['defense']}")
    print(f"status字段类型: {type(char.get('status'))}")
    print(f"status内容: {char.get('status')}")
else:
    print("角色17不存在")

# 检查另一个角色
char2 = get_character(18)  # 智慧法师
if char2:
    print(f"\n角色2: {char2['name']}")
    print(f"生命值: {char2['health']}")
    print(f"最大生命值: {char2['max_health']}")
else:
    print("角色18不存在")
