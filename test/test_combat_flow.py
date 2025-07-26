"""测试新的战斗流程"""
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from database.queries import get_characters_by_type, get_character_skills, get_skill
import json

def test_combat_flow():
    print("=== 测试战斗流程 ===")
    
    # 获取友方角色
    friendly_chars = get_characters_by_type("friendly", in_battle=True)
    print(f"战斗中的友方角色: {len(friendly_chars)}")
    for char in friendly_chars:
        print(f"  - {char['name']} (HP: {char['health']}/{char['max_health']})")
    
    # 获取敌方角色
    enemy_chars = get_characters_by_type("enemy", in_battle=True)
    print(f"战斗中的敌方角色: {len(enemy_chars)}")
    for char in enemy_chars:
        print(f"  - {char['name']} (HP: {char['health']}/{char['max_health']})")
    
    if friendly_chars:
        attacker = friendly_chars[0]
        print(f"\n=== 攻击者: {attacker['name']} ===")
        
        # 获取技能
        skills = get_character_skills(attacker['id'])
        print(f"可用技能: {len(skills)}")
        
        for skill in skills:
            # 判断技能类型
            try:
                effects = skill.get('effects', '{}')
                effects_dict = json.loads(effects) if isinstance(effects, str) else effects
                is_heal = effects_dict.get('heal', False)
                skill_type = "💚 治疗" if is_heal else "⚔️ 攻击"
            except:
                skill_type = "⚔️ 攻击"
            
            print(f"  {skill_type} {skill['name']}")
            print(f"    伤害公式: {skill['damage_formula']}")
            print(f"    冷却时间: {skill['cooldown']}")
            if skill.get('effects'):
                print(f"    效果: {skill['effects']}")
            print()

if __name__ == "__main__":
    test_combat_flow()
