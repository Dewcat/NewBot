import random
import json
from abc import ABC, abstractmethod
from database.queries import update_character_health, record_battle, get_character
from character.status_effects import (
    add_status_effect, 
    process_hit_effects, 
    process_action_effects,
    calculate_damage_modifiers
)
from game.damage_calculator import (
    calculate_damage_from_formula, 
    calculate_attack_defense_modifier,
    calculate_advanced_damage,
    update_character_cooldowns
)

class SkillEffect(ABC):
    """技能效果的抽象基类"""
    
    def execute(self, attacker, target, skill_info):
        """
        执行技能效果
        
        Args:
            attacker: 攻击者角色信息
            target: 目标角色信息  
            skill_info: 技能信息
            
        Returns:
            dict: {
                'total_damage': int,  # 总伤害
                'result_text': str,   # 战斗结果文本
                'target_health': int  # 目标剩余生命值
            }
        """
        # 根据技能分类选择处理方式
        skill_category = skill_info.get('skill_category', 'damage') if skill_info else 'damage'
        
        if skill_category == 'healing':
            return self.execute_healing(attacker, target, skill_info)
        elif skill_category == 'buff':
            return self.execute_buff(attacker, target, skill_info)
        elif skill_category == 'debuff':
            return self.execute_debuff(attacker, target, skill_info)
        else:  # damage 或其他默认为伤害
            return self.execute_damage(attacker, target, skill_info)
    
    def execute_damage(self, attacker, target, skill_info):
        """执行伤害技能"""
        # 计算基础伤害
        damage_result = self.calculate_skill_damage(attacker, target, skill_info)
        base_damage = damage_result['total_damage']
        
        # 应用攻击者的状态效果修正
        modified_damage, is_crit, attacker_messages = calculate_damage_modifiers(attacker['id'], base_damage)
        
        # 应用目标的受击状态效果
        final_damage, target_messages = process_hit_effects(target['id'], modified_damage)
        
        # 应用伤害
        new_health = max(0, target['health'] - final_damage)
        update_character_health(target['id'], new_health)
        record_battle(attacker['id'], target['id'], final_damage, skill_info['id'] if skill_info else None)
        
        # 处理技能的额外状态效果
        status_messages = self.apply_skill_status_effects(attacker, target, skill_info)
        
        # 处理攻击者的行动后效果
        action_messages = process_action_effects(attacker['id'])
        
        # 更新冷却时间
        update_character_cooldowns(attacker['id'], skill_info['id'] if skill_info else 1)
        
        # 构建整合的伤害显示
        damage_type = damage_result['damage_type']
        damage_type_icon = "⚔️" if damage_type == "physical" else "🔮"
        damage_type_name = "物理" if damage_type == "physical" else "魔法"
        
        crit_text = " (暴击!)" if is_crit else ""
        
        # 整合所有伤害修正信息
        damage_parts = [damage_result['damage_details']]
        
        # 添加状态效果修正信息
        if modified_damage != base_damage:
            damage_change = modified_damage - base_damage
            if damage_change > 0:
                damage_parts.append(f"状态增伤: +{damage_change}")
            else:
                damage_parts.append(f"状态减伤: {damage_change}")
        
        # 添加受击效果修正信息  
        if final_damage != modified_damage:
            damage_change = final_damage - modified_damage
            if damage_change > 0:
                damage_parts.append(f"受击增伤: +{damage_change}")
            else:
                damage_parts.append(f"受击减伤: {damage_change}")
        
        # 构建最终的伤害显示行
        damage_display = " → ".join(damage_parts) + f" → 总伤害: {final_damage}"
        result_text = f"{damage_type_icon} {damage_type_name}伤害{crit_text}：{damage_display}"
        
        # 添加状态效果详细信息（如果有的话）
        detail_messages = []
        if is_crit and any("呼吸法触发暴击" in msg for msg in attacker_messages):
            detail_messages.extend(attacker_messages)
        if attacker_messages and not any("呼吸法触发暴击" in msg for msg in attacker_messages):
            detail_messages.extend(attacker_messages)
        detail_messages.extend(target_messages)
        detail_messages.extend(status_messages)
        detail_messages.extend(action_messages)
        
        if detail_messages:
            result_text += "\n" + "\n".join(detail_messages)
        
        return {
            'total_damage': final_damage,
            'result_text': result_text,
            'target_health': new_health
        }
    
    def execute_healing(self, attacker, target, skill_info):
        """执行治疗技能"""
        # 治疗技能的目标是被选中的目标（可以是自己或其他友方）
        heal_target = target if target else attacker
        
        # 计算治疗量 - 治疗技能不受攻防和抗性影响，只使用基础公式
        heal_amount = self.calculate_healing_amount(attacker, skill_info)
        
        new_health = min(heal_target['health'] + heal_amount, heal_target['max_health'])
        actual_heal = new_health - heal_target['health']
        
        update_character_health(heal_target['id'], new_health)
        record_battle(attacker['id'], heal_target['id'], -actual_heal, skill_info['id'] if skill_info else 1)
        
        # 处理技能的额外状态效果
        status_messages = self.apply_skill_status_effects(attacker, heal_target, skill_info)
        
        # 处理行动后效果
        action_messages = process_action_effects(attacker['id'])
        
        # 更新冷却时间
        update_character_cooldowns(attacker['id'], skill_info['id'] if skill_info else 1)
        
        result_text = f"💚 魔法治疗：{heal_amount} 点 → 恢复了 {actual_heal} 点生命值"
        if actual_heal < heal_amount:
            result_text += f"（生命值已满，实际恢复{actual_heal}点）"
        
        # 添加状态效果消息
        all_messages = status_messages + action_messages
        if all_messages:
            result_text += "\n" + "\n".join(all_messages)
        
        return {
            'total_damage': -actual_heal,
            'result_text': result_text,
            'target_health': heal_target['health']
        }
    
    def calculate_healing_amount(self, healer, skill_info):
        """计算治疗量 - 不受攻防和抗性影响"""
        if not skill_info:
            # 无技能时使用基础治疗公式
            return calculate_damage_from_formula('1d6', healer)
        
        # 使用技能的伤害公式但不考虑抗性和攻防
        base_heal = calculate_damage_from_formula(skill_info.get('damage_formula', '1d6'), healer)
        return base_heal
    
    def execute_buff(self, attacker, target, skill_info):
        """执行纯增益技能 - 不造成伤害，只施加buff效果"""
        
        # 处理技能的状态效果 - buff技能可以指定目标
        status_messages = self.apply_skill_status_effects(attacker, target, skill_info)
        
        # 处理行动后效果
        action_messages = process_action_effects(attacker['id'])
        
        # 更新冷却时间
        update_character_cooldowns(attacker['id'], skill_info['id'] if skill_info else 1)
        
        skill_name = skill_info.get('name', '增益技能') if skill_info else '增益技能'
        target_name = target.get('name', '目标') if target else '目标'
        result_text = f"✨ {skill_name}：对 {target_name} 施加增益效果"
        
        # 添加状态效果消息
        all_messages = status_messages + action_messages
        if all_messages:
            result_text += "\n" + "\n".join(all_messages)
        
        return {
            'total_damage': 0,
            'result_text': result_text,
            'target_health': target['health'] if target else 0
        }
    
    def execute_debuff(self, attacker, target, skill_info):
        """执行纯减益技能 - 不造成伤害，只施加debuff效果"""
        
        # 处理技能的状态效果 - debuff技能可以指定目标
        status_messages = self.apply_skill_status_effects(attacker, target, skill_info)
        
        # 处理行动后效果
        action_messages = process_action_effects(attacker['id'])
        
        # 更新冷却时间
        update_character_cooldowns(attacker['id'], skill_info['id'] if skill_info else 1)
        
        skill_name = skill_info.get('name', '减益技能') if skill_info else '减益技能'
        target_name = target.get('name', '目标') if target else '目标'
        result_text = f"💀 {skill_name}：对 {target_name} 施加减益效果"
        
        # 添加状态效果消息
        all_messages = status_messages + action_messages
        if all_messages:
            result_text += "\n" + "\n".join(all_messages)
        
        return {
            'total_damage': 0,
            'result_text': result_text,
            'target_health': target['health']
        }
    
    def apply_skill_status_effects(self, attacker, target, skill_info):
        """应用技能的状态效果"""
        messages = []
        
        if not skill_info:
            return messages
        
        try:
            effects = json.loads(skill_info.get('effects', '{}'))
        except (json.JSONDecodeError, TypeError):
            effects = {}
        
        # 获取技能分类
        skill_category = skill_info.get('skill_category', 'damage')
        
        # 处理四种状态效果类型
        
        # 1. 处理self_buff效果 - 始终施加给施法者自己
        if 'self_buff' in effects:
            buff_info = effects['self_buff']
            success = add_status_effect(
                attacker['id'],
                'buff',
                buff_info['type'],
                buff_info['intensity'],
                buff_info['duration']
            )
            if success:
                buff_names = {
                    'strong': '强壮',
                    'breathing': '呼吸法',
                    'guard': '守护',
                    'shield': '护盾'
                }
                buff_name = buff_names.get(buff_info['type'], buff_info['type'])
                messages.append(f"✨ {attacker['name']} 获得了 {buff_name} 效果")
        
        # 2. 处理self_debuff效果 - 始终施加给施法者自己
        if 'self_debuff' in effects:
            debuff_info = effects['self_debuff']
            success = add_status_effect(
                attacker['id'],
                'debuff',
                debuff_info['type'],
                debuff_info['intensity'],
                debuff_info['duration']
            )
            if success:
                debuff_names = {
                    'burn': '烧伤',
                    'poison': '中毒',
                    'rupture': '破裂',
                    'bleeding': '流血',
                    'weak': '虚弱',
                    'vulnerable': '易伤'
                }
                debuff_name = debuff_names.get(debuff_info['type'], debuff_info['type'])
                messages.append(f"💀 {attacker['name']} 受到了 {debuff_name} 效果")
        
        # 3. 处理buff效果 - 始终施加给目标
        if 'buff' in effects:
            buff_info = effects['buff']
            buff_target_id = target['id'] if target else attacker['id']
            buff_target_name = target['name'] if target else attacker['name']
            
            success = add_status_effect(
                buff_target_id,
                'buff',
                buff_info['type'],
                buff_info['intensity'],
                buff_info['duration']
            )
            if success:
                buff_names = {
                    'strong': '强壮',
                    'breathing': '呼吸法',
                    'guard': '守护',
                    'shield': '护盾'
                }
                buff_name = buff_names.get(buff_info['type'], buff_info['type'])
                messages.append(f"✨ {buff_target_name} 获得了 {buff_name} 效果")
        
        # 4. 处理debuff效果 - 始终施加给目标
        if 'debuff' in effects:
            debuff_info = effects['debuff']
            debuff_target_id = target['id'] if target else attacker['id']
            debuff_target_name = target['name'] if target else attacker['name']
            
            success = add_status_effect(
                debuff_target_id,
                'debuff',
                debuff_info['type'],
                debuff_info['intensity'],
                debuff_info['duration']
            )
            if success:
                debuff_names = {
                    'burn': '烧伤',
                    'poison': '中毒',
                    'rupture': '破裂',
                    'bleeding': '流血',
                    'weak': '虚弱',
                    'vulnerable': '易伤'
                }
                debuff_name = debuff_names.get(debuff_info['type'], debuff_info['type'])
                messages.append(f"💀 {debuff_target_name} 受到了 {debuff_name} 效果")
        
        return messages
    
    def calculate_skill_damage(self, attacker, target, skill_info):
        """计算技能的高级伤害（包含伤害类型、抗性、特攻）"""
        if not skill_info:
            # 无技能时使用基础攻击公式
            skill_info = {
                'damage_formula': '1d6',
                'damage_type': 'physical',
                'special_damage_tags': '{}'
            }
        
        # 使用新的高级伤害计算系统
        final_damage, damage_details = calculate_advanced_damage(skill_info, attacker, target)
        
        return {
            'total_damage': final_damage,
            'damage_details': damage_details,
            'damage_type': skill_info.get('damage_type', 'physical')
        }
    
    @abstractmethod
    def apply_special_effects(self, attacker, target, skill_info, damage_result):
        """应用技能的特殊效果（已废弃，保留兼容性）"""
        pass

class NormalAttackEffect(SkillEffect):
    """普通攻击效果"""
    
    def apply_special_effects(self, attacker, target, skill_info, damage_result):
        """保留兼容性的方法"""
        return self.execute_damage(attacker, target, skill_info)

class HealingEffect(SkillEffect):
    """治疗效果"""
    
    def apply_special_effects(self, attacker, target, skill_info, damage_result):
        """保留兼容性的方法"""
        return self.execute_healing(attacker, target, skill_info)

class DefaultSkillEffect(SkillEffect):
    """默认技能效果（根据技能的effects JSON处理）"""
    
    def apply_special_effects(self, attacker, target, skill_info, damage_result):
        """保留兼容性的方法"""
        return self.execute(attacker, target, skill_info)

class SkillEffectRegistry:
    """技能效果注册表"""
    
    def __init__(self):
        self.effects = {}
        self._register_default_effects()
    
    def _register_default_effects(self):
        """注册默认技能效果"""
        # 只为特殊技能注册专门的效果类
        self.register_effect(1, NormalAttackEffect())  # 普通攻击
        self.register_effect(7, HealingEffect())       # 净化（治疗技能）
    
    def register_effect(self, skill_id, effect):
        """注册技能效果"""
        self.effects[skill_id] = effect
    
    def get_effect(self, skill_id):
        """获取技能效果"""
        return self.effects.get(skill_id, DefaultSkillEffect())
    
    def execute_skill(self, attacker, target, skill_info):
        """执行技能"""
        if not skill_info:
            # 无技能时使用普通攻击
            effect = self.get_effect(1)
        else:
            effect = self.get_effect(skill_info['id'])
        
        return effect.execute(attacker, target, skill_info)

# 创建全局技能效果注册表实例
skill_registry = SkillEffectRegistry()
