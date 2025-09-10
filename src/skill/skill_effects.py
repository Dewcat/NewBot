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
    update_character_cooldowns,
    apply_damage_with_stagger
)
from skill.effect_target_resolver import target_resolver
from character.emotion_system import add_emotion_coins

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
        elif skill_category == 'self':
            return self.execute_self(attacker, target, skill_info)
        elif skill_category == 'aoe_damage':
            return self.execute_aoe_damage(attacker, target, skill_info)
        elif skill_category == 'aoe_healing':
            return self.execute_aoe_healing(attacker, target, skill_info)
        elif skill_category == 'aoe_buff':
            return self.execute_aoe_buff(attacker, target, skill_info)
        elif skill_category == 'aoe_debuff':
            return self.execute_aoe_debuff(attacker, target, skill_info)
        elif skill_category == 'aoe':  # 兼容旧的aoe分类
            return self.execute_aoe(attacker, target, skill_info)
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
        
        # 处理混乱值扣除
        stagger_messages = apply_damage_with_stagger(target['id'], final_damage)
        
        # 处理技能的额外状态效果（传递最终伤害作为主效果值）
        status_messages = self.apply_skill_status_effects(attacker, target, skill_info, final_damage)
        
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
        detail_messages.extend(stagger_messages)  # 添加混乱值信息
        detail_messages.extend(status_messages)
        detail_messages.extend(action_messages)
        
        if detail_messages:
            result_text += "\n" + "\n".join(detail_messages)
        
        # 处理自我效果（自我伤害/治疗），传递实际伤害值
        self_effect_messages = self.apply_self_effects(attacker, skill_info, final_damage, 'damage')
        if self_effect_messages:
            result_text += "\n" + "\n".join(self_effect_messages)
        
        # 处理情感硬币获取
        emotion_messages = []
        
        # 1. 处理骰子情感硬币
        dice_results_info = damage_result.get('dice_results_info', [])
        for dice_info in dice_results_info:
            dice_emotion_msgs = self.process_dice_emotion_coins(
                attacker['id'], 
                dice_info['results'], 
                dice_info['faces'],
                attacker['name']
            )
            emotion_messages.extend(dice_emotion_msgs)
        
        # 2. 处理伤害相关情感硬币
        damage_emotion_msgs = self.process_damage_emotion_coins(attacker, target, final_damage, new_health <= 0)
        emotion_messages.extend(damage_emotion_msgs)
        
        if emotion_messages:
            result_text += "\n" + "\n".join(emotion_messages)
        
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
        
        # 处理技能的额外状态效果（传递实际治疗量作为主效果值）
        status_messages = self.apply_skill_status_effects(attacker, heal_target, skill_info, actual_heal)
        
        # 处理行动后效果
        action_messages = process_action_effects(attacker['id'])
        
        # 更新冷却时间
        update_character_cooldowns(attacker['id'], skill_info['id'] if skill_info else 1)
        
        result_text = f"💚 治疗：{heal_amount} 点 → 恢复了 {actual_heal} 点生命值"
        if actual_heal < heal_amount:
            result_text += f"（生命值已满，实际恢复{actual_heal}点）"
        
        # 添加状态效果消息
        all_messages = status_messages + action_messages
        if all_messages:
            result_text += "\n" + "\n".join(all_messages)
        
        # 处理自我效果（自我伤害/治疗），传递原始治疗值
        self_effect_messages = self.apply_self_effects(attacker, skill_info, heal_amount, 'healing')
        if self_effect_messages:
            result_text += "\n" + "\n".join(self_effect_messages)
        
        # 处理治疗相关的情感硬币获取
        healing_emotion_messages = self.process_healing_emotion_coins(attacker, heal_target, actual_heal)
        if healing_emotion_messages:
            result_text += "\n" + "\n".join(healing_emotion_messages)
        
        return {
            'total_damage': -actual_heal,
            'result_text': result_text,
            'target_health': new_health
        }
    
    def execute_damage_without_self_effects(self, attacker, target, skill_info):
        """执行伤害技能但不触发自我效果和状态效果（用于AOE）"""
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
        
        # 构建伤害显示（简化版，不包含状态效果）
        result_text = f"总伤害: {final_damage}"
        
        return {
            'total_damage': final_damage,
            'result_text': result_text,
            'target_health': new_health
        }
    
    def execute_healing_without_self_effects(self, attacker, target, skill_info):
        """执行治疗技能但不触发自我效果和状态效果（用于AOE）"""
        # 治疗技能的目标是被选中的目标
        heal_target = target if target else attacker
        
        # 计算治疗量
        heal_amount = self.calculate_healing_amount(attacker, skill_info)
        
        new_health = min(heal_target['health'] + heal_amount, heal_target['max_health'])
        actual_heal = new_health - heal_target['health']
        
        update_character_health(heal_target['id'], new_health)
        record_battle(attacker['id'], heal_target['id'], -actual_heal, skill_info['id'] if skill_info else 1)
        
        result_text = f"恢复了 {actual_heal} 点生命值"
        if actual_heal < heal_amount:
            result_text += f"（生命值已满，实际恢复{actual_heal}点）"
        
        # 处理治疗相关的情感硬币获取（简化版，不显示详细消息）
        healing_emotion_messages = self.process_healing_emotion_coins(attacker, heal_target, actual_heal)
        # 对于AOE治疗，我们不在这里显示详细的情感硬币消息，而是在AOE结果中统一处理
        
        return {
            'total_damage': -actual_heal,
            'result_text': result_text,
            'target_health': new_health,
            'emotion_messages': healing_emotion_messages  # 返回情感硬币消息供上级处理
        }
    
    def calculate_healing_amount(self, healer, skill_info):
        """计算治疗量 - 不受攻防和抗性影响"""
        if not skill_info:
            # 无技能时使用基础治疗公式
            heal_result = calculate_damage_from_formula('1d6')
            return heal_result[0] if isinstance(heal_result, tuple) else heal_result
        
        # 使用技能的伤害公式但不考虑抗性和攻防
        heal_result = calculate_damage_from_formula(skill_info.get('damage_formula', '1d6'))
        return heal_result[0] if isinstance(heal_result, tuple) else heal_result
    
    def execute_buff(self, attacker, target, skill_info):
        """执行纯增益技能 - 不造成伤害，只施加buff效果"""
        
        # 处理技能的状态效果 - buff技能可以指定目标（主效果值为0）
        status_messages = self.apply_skill_status_effects(attacker, target, skill_info, 0)
        
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
        
        # 处理自我效果（自我伤害/治疗），buff技能传递0值
        self_effect_messages = self.apply_self_effects(attacker, skill_info, 0, 'buff')
        if self_effect_messages:
            result_text += "\n" + "\n".join(self_effect_messages)
        
        return {
            'total_damage': 0,
            'result_text': result_text,
            'target_health': target['health'] if target else 0
        }
    
    def execute_debuff(self, attacker, target, skill_info):
        """执行纯减益技能 - 不造成伤害，只施加debuff效果"""
        
        # 处理技能的状态效果 - debuff技能可以指定目标（主效果值为0）
        status_messages = self.apply_skill_status_effects(attacker, target, skill_info, 0)
        
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
        
        # 处理自我效果（自我伤害/治疗），debuff技能传递0值
        self_effect_messages = self.apply_self_effects(attacker, skill_info, 0, 'debuff')
        if self_effect_messages:
            result_text += "\n" + "\n".join(self_effect_messages)
        
        return {
            'total_damage': 0,
            'result_text': result_text,
            'target_health': target['health']
        }
    
    def execute_self(self, attacker, target, skill_info):
        """执行自我技能 - 不造成伤害，只对自己施加效果"""
        
        # 自我技能的目标始终是施法者自己
        self_target = attacker
        
        # 处理技能的状态效果 - 自我技能只对施法者生效（主效果值为0）
        status_messages = self.apply_skill_status_effects(attacker, self_target, skill_info, 0)
        
        # 处理行动后效果
        action_messages = process_action_effects(attacker['id'])
        
        # 更新冷却时间
        update_character_cooldowns(attacker['id'], skill_info['id'] if skill_info else 1)
        
        skill_name = skill_info.get('name', '自我技能') if skill_info else '自我技能'
        result_text = f"🧘 {skill_name}：自我强化效果"
        
        # 添加状态效果消息
        all_messages = status_messages + action_messages
        if all_messages:
            result_text += "\n" + "\n".join(all_messages)
        
        # 处理自我效果（自我伤害/治疗），自我技能传递0值
        self_effect_messages = self.apply_self_effects(attacker, skill_info, 0, 'self')
        if self_effect_messages:
            result_text += "\n" + "\n".join(self_effect_messages)
        
        return {
            'total_damage': 0,
            'result_text': result_text,
            'target_health': attacker['health']
        }
    
    def execute_aoe(self, attacker, target, skill_info):
        """执行AOE技能 - 对所有敌方或友方目标生效"""
        from database.queries import get_battle_characters
        import json
        
        # 分析技能效果来确定是否为治疗/友方技能
        try:
            effects = json.loads(skill_info.get('effects', '{}')) if skill_info else {}
        except (json.JSONDecodeError, TypeError):
            effects = {}
        
        # 判断技能类型
        damage_formula = skill_info.get('damage_formula', '0') if skill_info else '0'
        has_damage = damage_formula != '0'
        has_buff = 'buff' in effects
        has_debuff = 'debuff' in effects
        
        # 获取战斗中的角色
        battle_chars = get_battle_characters()
        
        # 确定目标：有buff效果或无伤害无debuff = 友方技能；有伤害或debuff = 敌方技能
        if has_buff or (not has_damage and not has_debuff):
            # 友方技能：目标所有友方
            targets = [char for char in battle_chars 
                      if char['character_type'] == attacker['character_type']]
            action_desc = "强化"
            is_friendly_skill = True
        else:
            # 敌方技能：目标所有敌方
            targets = [char for char in battle_chars 
                      if char['character_type'] != attacker['character_type']]
            action_desc = "攻击"
            is_friendly_skill = False
            action_desc = "强化"
        
        if not targets:
            skill_name = skill_info.get('name', 'AOE技能') if skill_info else 'AOE技能'
            return {
                'total_damage': 0,
                'result_text': f"🌀 {skill_name}：没有有效目标",
                'target_health': 0
            }
        
        # 执行AOE效果
        total_damage_dealt = 0
        total_healing_done = 0
        all_messages = []
        
        skill_name = skill_info.get('name', 'AOE技能') if skill_info else 'AOE技能'
        
        for aoe_target in targets:
            if not is_friendly_skill:
                # 对每个敌方目标执行伤害（不触发自我效果）
                result = self.execute_damage_without_self_effects(attacker, aoe_target, skill_info)
                total_damage_dealt += result['total_damage']
                target_result = f"→ {aoe_target['name']}: {result['result_text'].split(' → ')[-1] if ' → ' in result['result_text'] else result['result_text']}"
            else:
                # 对每个友方目标执行治疗/buff（不触发自我效果）
                result = self.execute_healing_without_self_effects(attacker, aoe_target, skill_info)
                if result['total_damage'] < 0:  # 治疗技能返回负伤害
                    total_healing_done += abs(result['total_damage'])
                target_result = f"→ {aoe_target['name']}: {result['result_text'].split(' → ')[-1] if ' → ' in result['result_text'] else result['result_text']}"
            
            all_messages.append(target_result)
        
        # 处理施法者的自我效果（基于总效果值）
        total_effect_value = total_damage_dealt if not is_friendly_skill else total_healing_done
        self_effect_messages = self.apply_self_effects(attacker, skill_info, total_effect_value, 'aoe')
        
        # 统一处理对所有目标的状态效果（只处理一次）
        target_status_messages = []
        if targets:
            # 随机选择一个目标用于状态效果触发（实际上对所有目标生效）
            sample_target = targets[0]
            target_status_messages = self.apply_aoe_status_effects(attacker, targets, skill_info, is_friendly_skill)
        
        # 处理行动后效果
        action_messages = process_action_effects(attacker['id'])
        
        # 更新冷却时间
        update_character_cooldowns(attacker['id'], skill_info['id'] if skill_info else 1)
        
        # 构建结果文本
        if not is_friendly_skill:
            result_text = f"🌀 AOE攻击：{skill_name}\n"
            result_text += f"💥 对 {len(targets)} 个敌方目标造成总计 {total_damage_dealt} 点伤害\n"
        else:
            result_text = f"🌀 AOE{action_desc}：{skill_name}\n"
            result_text += f"💚 对 {len(targets)} 个友方目标提供效果\n"
        
        result_text += "\n".join(all_messages)
        
        # 添加自我效果和行动后效果
        if self_effect_messages:
            result_text += "\n" + "\n".join(self_effect_messages)
        if target_status_messages:
            result_text += "\n" + "\n".join(target_status_messages)
        if action_messages:
            result_text += "\n" + "\n".join(action_messages)
        
        return {
            'total_damage': total_damage_dealt if not is_friendly_skill else -total_healing_done,
            'result_text': result_text,
            'target_health': 0  # AOE没有单一目标血量
        }
    
    def apply_aoe_status_effects(self, attacker, targets, skill_info, is_friendly_skill):
        """统一处理AOE技能的状态效果"""
        from character.status_effects import add_status_effect
        import json
        
        messages = []
        
        if not skill_info or not targets:
            return messages
        
        try:
            effects = json.loads(skill_info.get('effects', '{}'))
        except (json.JSONDecodeError, TypeError):
            effects = {}
        
        # 处理对目标的状态效果
        target_effect_key = 'buff' if is_friendly_skill else 'debuff'
        
        if target_effect_key in effects:
            effect_info = effects[target_effect_key]
            effect_names = {
                'strong': '强壮', 'breathing': '呼吸法', 'guard': '守护', 'shield': '护盾',
                'burn': '烧伤', 'poison': '中毒', 'rupture': '破裂', 'bleeding': '流血',
                'weak': '虚弱', 'vulnerable': '易伤'
            }
            
            effect_name = effect_names.get(effect_info['type'], effect_info['type'])
            effect_icon = "✨" if is_friendly_skill else "💀"
            
            for target in targets:
                success = add_status_effect(
                    target['id'],
                    target_effect_key,
                    effect_info['type'],
                    effect_info['intensity'],
                    effect_info['duration']
                )
                if success:
                    if effect_info['type'] == 'shield':
                        messages.append(f"{effect_icon} {target['name']} 获得了 {effect_info['intensity']} 点{effect_name}")
                    else:
                        messages.append(f"{effect_icon} {target['name']} 受到了 {effect_name}({effect_info['intensity']}) 效果，持续 {effect_info['duration']} 回合")
        
        return messages
    
    def execute_aoe_damage(self, attacker, target, skill_info):
        """执行AOE伤害技能"""
        from database.queries import get_characters_by_type
        
        # AOE伤害技能目标是所有敌方角色
        attacker_type = attacker.get('character_type', 'friendly')
        enemy_type = 'enemy' if attacker_type == 'friendly' else 'friendly'
        targets = get_characters_by_type(enemy_type, in_battle=True)
        
        if not targets:
            return {
                'total_damage': 0,
                'result_text': f"🌀 {skill_info.get('name', 'AOE攻击')}：没有找到敌方目标",
                'target_health': 0
            }
        
        # 对每个目标执行伤害
        total_damage = 0
        damage_messages = []
        
        for enemy_target in targets:
            damage_result = self.execute_damage_without_self_effects(attacker, enemy_target, skill_info)
            total_damage += damage_result['total_damage']
            damage_messages.append(f"→ {enemy_target['name']}: 受到 {damage_result['total_damage']} 点伤害")
        
        # 处理技能的次要效果（传递总伤害作为主效果值）
        status_messages = self.apply_skill_status_effects(attacker, None, skill_info, total_damage)
        
        # 处理行动后效果
        action_messages = process_action_effects(attacker['id'])
        
        # 处理自我效果
        self_effect_messages = self.apply_self_effects(attacker, skill_info, total_damage, 'aoe_damage')
        
        # 更新冷却时间
        update_character_cooldowns(attacker['id'], skill_info['id'] if skill_info else 1)
        
        # 构建结果文本
        skill_name = skill_info.get('name', 'AOE攻击')
        result_text = f"⚔️ 对 {len(targets)} 个敌方目标造成总计 {total_damage} 点伤害\n"
        result_text += "\n".join(damage_messages)
        
        # 添加次要效果
        all_secondary_messages = status_messages + self_effect_messages + action_messages
        if all_secondary_messages:
            result_text += "\n" + "\n".join(all_secondary_messages)
        
        return {
            'total_damage': total_damage,
            'result_text': result_text,
            'target_health': 0
        }
    
    def execute_aoe_healing(self, attacker, target, skill_info):
        """执行AOE治疗技能"""
        from database.queries import get_characters_by_type
        
        # AOE治疗技能目标是所有友方角色
        attacker_type = attacker.get('character_type', 'friendly')
        targets = get_characters_by_type(attacker_type, in_battle=True)
        
        if not targets:
            return {
                'total_damage': 0,
                'result_text': f"🌀 {skill_info.get('name', 'AOE治疗')}：没有找到友方目标",
                'target_health': 0
            }
        
        # 对每个目标执行治疗
        total_healing = 0
        healing_messages = []
        all_emotion_messages = []  # 收集所有情感硬币消息
        
        for ally_target in targets:
            healing_result = self.execute_healing_without_self_effects(attacker, ally_target, skill_info)
            heal_amount = abs(healing_result['total_damage'])  # 治疗返回负伤害
            total_healing += heal_amount
            healing_messages.append(f"→ {ally_target['name']}: 恢复 {heal_amount} 点生命值")
            
            # 收集情感硬币消息
            if 'emotion_messages' in healing_result:
                all_emotion_messages.extend(healing_result['emotion_messages'])
        
        # 处理技能的次要效果（传递总治疗量作为主效果值）
        status_messages = self.apply_skill_status_effects(attacker, None, skill_info, total_healing)
        
        # 处理行动后效果
        action_messages = process_action_effects(attacker['id'])
        
        # 处理自我效果
        self_effect_messages = self.apply_self_effects(attacker, skill_info, total_healing, 'aoe_healing')
        
        # 更新冷却时间
        update_character_cooldowns(attacker['id'], skill_info['id'] if skill_info else 1)
        
        # 构建结果文本
        skill_name = skill_info.get('name', 'AOE治疗')
        result_text = f"💚 对 {len(targets)} 个友方目标总计恢复 {total_healing} 点生命值\n"
        result_text += "\n".join(healing_messages)
        
        # 添加次要效果
        all_secondary_messages = status_messages + self_effect_messages + action_messages
        if all_secondary_messages:
            result_text += "\n" + "\n".join(all_secondary_messages)
        
        # 添加情感硬币消息
        if all_emotion_messages:
            result_text += "\n" + "\n".join(all_emotion_messages)
        
        return {
            'total_damage': -total_healing,  # 治疗返回负伤害
            'result_text': result_text,
            'target_health': 0
        }
    
    def execute_aoe_buff(self, attacker, target, skill_info):
        """执行AOE增益技能"""
        from database.queries import get_characters_by_type
        
        # AOE增益技能目标是所有友方角色
        attacker_type = attacker.get('character_type', 'friendly')
        targets = get_characters_by_type(attacker_type, in_battle=True)
        
        if not targets:
            return {
                'total_damage': 0,
                'result_text': f"🌀 {skill_info.get('name', 'AOE增益')}：没有找到友方目标",
                'target_health': 0
            }
        
        # 处理技能的主要效果和次要效果（AOE增益技能主效果值为0）
        status_messages = self.apply_skill_status_effects(attacker, None, skill_info, 0)
        
        # 处理行动后效果
        action_messages = process_action_effects(attacker['id'])
        
        # 处理自我效果
        self_effect_messages = self.apply_self_effects(attacker, skill_info, 0, 'aoe_buff')
        
        # 更新冷却时间
        update_character_cooldowns(attacker['id'], skill_info['id'] if skill_info else 1)
        
        # 构建结果文本
        skill_name = skill_info.get('name', 'AOE增益')
        result_text = f"✨ 对 {len(targets)} 个友方目标施加增益效果"
        
        # 添加所有效果
        all_messages = status_messages + self_effect_messages + action_messages
        if all_messages:
            result_text += "\n" + "\n".join(all_messages)
        
        return {
            'total_damage': 0,
            'result_text': result_text,
            'target_health': 0
        }
    
    def execute_aoe_debuff(self, attacker, target, skill_info):
        """执行AOE减益技能"""
        from database.queries import get_characters_by_type
        
        # AOE减益技能目标是所有敌方角色
        attacker_type = attacker.get('character_type', 'friendly')
        enemy_type = 'enemy' if attacker_type == 'friendly' else 'friendly'
        targets = get_characters_by_type(enemy_type, in_battle=True)
        
        if not targets:
            return {
                'total_damage': 0,
                'result_text': f"🌀 {skill_info.get('name', 'AOE减益')}：没有找到敌方目标",
                'target_health': 0
            }
        
        # 处理技能的主要效果和次要效果（AOE减益技能主效果值为0）
        status_messages = self.apply_skill_status_effects(attacker, None, skill_info, 0)
        
        # 处理行动后效果
        action_messages = process_action_effects(attacker['id'])
        
        # 处理自我效果
        self_effect_messages = self.apply_self_effects(attacker, skill_info, 0, 'aoe_debuff')
        
        # 更新冷却时间
        update_character_cooldowns(attacker['id'], skill_info['id'] if skill_info else 1)
        
        # 构建结果文本
        skill_name = skill_info.get('name', 'AOE减益')
        result_text = f"💀 对 {len(targets)} 个敌方目标施加减益效果"
        
        # 添加所有效果
        all_messages = status_messages + self_effect_messages + action_messages
        if all_messages:
            result_text += "\n" + "\n".join(all_messages)
        
        return {
            'total_damage': 0,
            'result_text': result_text,
            'target_health': 0
        }
    
    def apply_skill_status_effects(self, attacker, target, skill_info, main_effect_value=0):
        """应用技能的状态效果（使用新的目标解析系统，支持百分比计算）"""
        messages = []
        
        if not skill_info:
            return messages
        
        try:
            effects = json.loads(skill_info.get('effects', '{}'))
        except (json.JSONDecodeError, TypeError):
            effects = {}
        
        # 处理buff效果
        if 'buff' in effects:
            buff_info = effects['buff']
            # 解析目标
            target_type = buff_info.get('target', 'skill_target')
            buff_targets = target_resolver.resolve_target(target_type, attacker, target)
            
            # 应用buff效果
            for buff_target in buff_targets:
                if not buff_target:
                    continue
                    
                # 特殊处理冷却缩减 - 立即生效而不是作为状态效果
                if buff_info['type'] == 'cooldown_reduction':
                    messages.extend(self._apply_instant_cooldown_reduction(buff_target['id'], buff_info['intensity']))
                # 特殊处理加速 - 立即生效当前回合并添加为状态效果
                elif buff_info['type'] == 'haste':
                    success = add_status_effect(
                        buff_target['id'],
                        'buff',
                        buff_info['type'],
                        buff_info['intensity'],
                        buff_info['duration']
                    )
                    if success:
                        # 立即应用加速效果到当前回合
                        current_char = get_character(buff_target['id'])
                        if current_char:
                            from database.queries import update_character_actions
                            current_actions = current_char.get('current_actions', 0)
                            new_actions = current_actions + buff_info['intensity']
                            if update_character_actions(buff_target['id'], new_actions):
                                messages.append(f"✨ {buff_target['name']} 获得了 加速 效果")
                                messages.append(f"⚡ {buff_target['name']} 的加速立即增加了 {buff_info['intensity']} 次行动次数")
                else:
                    success = add_status_effect(
                        buff_target['id'],
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
                        
                        if buff_info['type'] == 'shield':
                            # 护盾只显示盾值
                            messages.append(f"✨ {buff_target['name']} 获得了 {buff_info['intensity']} 点{buff_name}")
                        else:
                            # 其他buff显示强度和持续时间
                            messages.append(f"✨ {buff_target['name']} 获得了 {buff_name}({buff_info['intensity']}) 效果，持续 {buff_info['duration']} 回合")
        
        # 处理debuff效果
        if 'debuff' in effects:
            debuff_info = effects['debuff']
            # 解析目标
            target_type = debuff_info.get('target', 'skill_target')
            debuff_targets = target_resolver.resolve_target(target_type, attacker, target)
            
            # 应用debuff效果
            for debuff_target in debuff_targets:
                if not debuff_target:
                    continue
                    
                success = add_status_effect(
                    debuff_target['id'],
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
                    messages.append(f"💀 {debuff_target['name']} 受到了 {debuff_name}({debuff_info['intensity']}) 效果，持续 {debuff_info['duration']} 回合")
        
        # 处理damage效果（对目标造成伤害）
        if 'damage' in effects:
            damage_info = effects['damage']
            # 解析目标
            target_type = damage_info.get('target', 'skill_target')
            damage_targets = target_resolver.resolve_target(target_type, attacker, target)
            
            # 应用伤害效果
            for damage_target in damage_targets:
                if not damage_target:
                    continue
                    
                # 计算伤害量（支持百分比）
                damage_amount = self._calculate_effect_amount(damage_info, main_effect_value, 'damage')
                if damage_amount > 0:
                    new_health = max(0, damage_target['health'] - damage_amount)
                    update_character_health(damage_target['id'], new_health)
                    messages.append(f"⚔️ {damage_target['name']} 受到了 {damage_amount} 点额外伤害")
        
        # 处理heal效果（对目标进行治疗）
        if 'heal' in effects:
            heal_info = effects['heal']
            # 解析目标
            target_type = heal_info.get('target', 'skill_target')
            heal_targets = target_resolver.resolve_target(target_type, attacker, target)
            
            # 应用治疗效果
            for heal_target in heal_targets:
                if not heal_target:
                    continue
                    
                # 计算治疗量（支持百分比）
                heal_amount = self._calculate_effect_amount(heal_info, main_effect_value, 'heal')
                if heal_amount > 0:
                    new_health = min(heal_target['max_health'], heal_target['health'] + heal_amount)
                    actual_heal = new_health - heal_target['health']
                    if actual_heal > 0:
                        update_character_health(heal_target['id'], new_health)
                        messages.append(f"💚 {heal_target['name']} 恢复了 {actual_heal} 点生命值")
        
        return messages
    
    def _calculate_effect_amount(self, effect_config, main_effect_value, effect_type):
        """
        计算效果数值（支持百分比）
        
        Args:
            effect_config: 效果配置
            main_effect_value: 主效果数值（伤害或治疗量）
            effect_type: 效果类型
            
        Returns:
            int: 计算后的效果数值
        """
        if isinstance(effect_config, dict):
            # 固定数值
            if 'amount' in effect_config:
                return effect_config['amount']
            
            # 百分比计算（基于主效果）
            if 'percentage' in effect_config:
                percentage = effect_config['percentage']
                return int(main_effect_value * percentage / 100)
        
        return 0
    
    def _apply_instant_cooldown_reduction(self, character_id: int, intensity: int) -> list:
        """立即应用冷却缩减效果"""
        from database.queries import get_character
        from database.db_connection import get_db_connection
        import json
        import logging
        
        logger = logging.getLogger(__name__)
        messages = []
        
        # 获取角色信息
        character = get_character(character_id)
        if not character:
            return messages
        
        character_name = character.get('name', f'角色{character_id}')
        
        try:
            # 获取当前状态
            status = character.get('status', {})
            if isinstance(status, str):
                status = json.loads(status)
            elif status is None:
                status = {}
            
            if 'cooldowns' in status and status['cooldowns']:
                # 有冷却中的技能
                reduced_skills = []
                for skill_id, cooldown in list(status['cooldowns'].items()):
                    new_cooldown = max(0, cooldown - intensity)
                    if new_cooldown <= 0:
                        del status['cooldowns'][skill_id]
                        reduced_skills.append(skill_id)
                    else:
                        status['cooldowns'][skill_id] = new_cooldown
                
                # 更新角色状态
                conn = get_db_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute(
                        "UPDATE characters SET status = ? WHERE id = ?",
                        (json.dumps(status), character_id)
                    )
                    conn.commit()
                    
                    if reduced_skills or intensity > 0:
                        if reduced_skills:
                            messages.append(f"❄️ {character_name} 的技能冷却时间缩短了，部分技能可立即使用")
                        else:
                            messages.append(f"❄️ {character_name} 的技能冷却时间得到了缩短")
                            
                except Exception as e:
                    logger.error(f"更新冷却状态时出错: {e}")
                    conn.rollback()
                finally:
                    conn.close()
            else:
                # 没有冷却中的技能
                messages.append(f"❄️ {character_name} 尝试缩短技能冷却时间，但当前没有技能在冷却中")
                
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.error(f"处理冷却缩减时出错: {e}")
            messages.append(f"❄️ {character_name} 的技能得到了强化")
        
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
        final_damage, damage_details, dice_results_info = calculate_advanced_damage(skill_info, attacker, target)
        
        return {
            'total_damage': final_damage,
            'damage_details': damage_details,
            'damage_type': skill_info.get('damage_type', 'physical'),
            'dice_results_info': dice_results_info  # 添加骰子结果信息
        }
    
    def apply_self_effects(self, attacker, skill_info, skill_effect_value=0, effect_type='damage'):
        """
        应用技能的自我效果（自我伤害/治疗）
        
        Args:
            attacker: 施法者角色信息
            skill_info: 技能信息
            skill_effect_value: 技能的实际效果值（伤害量或治疗量）
            effect_type: 技能效果类型 ('damage', 'healing', 'buff', 'debuff', 'self')
            
        Returns:
            list: 自我效果消息列表
        """
        messages = []
        
        if not skill_info:
            return messages
            
        try:
            effects = skill_info.get('effects', '{}')
            effects_dict = json.loads(effects) if isinstance(effects, str) else effects
            
            # 处理自我伤害
            if 'self_damage' in effects_dict:
                self_damage = effects_dict['self_damage']
                damage_amount = self._calculate_self_effect_amount(
                    self_damage, skill_effect_value, effect_type
                )
                
                if damage_amount > 0:
                    # 重新获取施法者的最新血量信息，因为可能已经被主要技能效果修改
                    from database.queries import get_character
                    current_attacker = get_character(attacker['id'])
                    if current_attacker:
                        current_health = current_attacker.get('health', attacker['health'])
                        new_health = max(0, current_health - damage_amount)
                        update_character_health(attacker['id'], new_health)
                        messages.append(f"💔 {attacker['name']} 承受了 {damage_amount} 点反噬伤害")
            
            # 处理自我治疗
            if 'self_heal' in effects_dict:
                self_heal = effects_dict['self_heal']
                heal_amount = self._calculate_self_effect_amount(
                    self_heal, skill_effect_value, effect_type
                )
                
                if heal_amount > 0:
                    # 重新获取施法者的最新血量信息，因为可能已经被主要技能效果修改
                    from database.queries import get_character
                    current_attacker = get_character(attacker['id'])
                    if current_attacker:
                        max_health = current_attacker.get('max_health', 100)
                        current_health = current_attacker.get('health', attacker['health'])
                        new_health = min(max_health, current_health + heal_amount)
                        actual_heal = new_health - current_health
                        if actual_heal > 0:
                            update_character_health(attacker['id'], new_health)
                            messages.append(f"💚 {attacker['name']} 回复了 {actual_heal} 点生命值")
                    
        except Exception as e:
            print(f"处理自我效果时出错: {e}")
            
        return messages
    
    def _calculate_self_effect_amount(self, effect_config, skill_effect_value, effect_type):
        """
        计算自我效果的数值
        
        Args:
            effect_config: 自我效果配置
            skill_effect_value: 技能的实际效果值
            effect_type: 技能效果类型
            
        Returns:
            int: 计算后的自我效果数值
        """
        if isinstance(effect_config, (int, float)):
            # 简单数值，直接返回
            return int(effect_config)
        elif isinstance(effect_config, dict):
            # 固定数值
            if 'amount' in effect_config:
                return effect_config['amount']
            
            # 百分比计算
            if 'percentage' in effect_config:
                percentage = effect_config['percentage']
                return int(skill_effect_value * percentage / 100)
            
            # 基于类型的百分比计算
            if 'damage_percentage' in effect_config and effect_type in ('damage', 'aoe'):
                percentage = effect_config['damage_percentage']
                return int(skill_effect_value * percentage / 100)
            
            if 'healing_percentage' in effect_config and effect_type in ('healing', 'aoe'):
                percentage = effect_config['healing_percentage']
                return int(skill_effect_value * percentage / 100)
        
        return 0
    
    def process_damage_emotion_coins(self, attacker, target, damage_dealt, target_died):
        """
        处理伤害相关的情感硬币获取
        
        Args:
            attacker: 攻击者信息
            target: 目标信息
            damage_dealt: 实际造成的伤害
            target_died: 目标是否死亡
            
        Returns:
            list: 情感硬币获取消息
        """
        messages = []
        
        try:
            # 造成伤害时获得1个正面情感硬币（基于次数）
            positive_coins = 1  # 每次造成伤害获得1个硬币
            
            # 击杀目标获得额外正面情感硬币
            if target_died:
                positive_coins += 2
                
            if positive_coins > 0:
                result = add_emotion_coins(
                    attacker['id'], 
                    positive=positive_coins,
                    source=f"造成{damage_dealt}伤害" + ("并击杀目标" if target_died else "")
                )
                
                if result.get('success') and result.get('coins_added'):
                    msg = f"🎭 {attacker['name']} 获得{positive_coins}个正面情感硬币"
                    if result.get('upgrade_pending'):
                        msg += f"，准备升级到{result['target_level']}级！"
                    messages.append(msg)
                    
            # 受到伤害时获得1个负面情感硬币（基于次数）
            negative_coins = 1  # 每次受到伤害获得1个硬币
            
            if negative_coins > 0:
                result = add_emotion_coins(
                    target['id'],
                    negative=negative_coins,
                    source=f"受到{damage_dealt}伤害"
                )
                
                if result.get('success') and result.get('coins_added'):
                    msg = f"🎭 {target['name']} 获得{negative_coins}个负面情感硬币"
                    if result.get('upgrade_pending'):
                        msg += f"，准备升级到{result['target_level']}级！"
                    messages.append(msg)
                    
        except Exception as e:
            print(f"处理情感硬币时出错: {e}")
        
        return messages
    
    def process_healing_emotion_coins(self, healer, target, healing_amount):
        """
        处理治疗相关的情感硬币获取
        
        Args:
            healer: 治疗者信息
            target: 目标信息
            healing_amount: 实际治疗量
            
        Returns:
            list: 情感硬币获取消息
        """
        messages = []
        
        try:
            # 造成治疗时获得1个正面情感硬币（基于次数）
            positive_coins_healer = 1  # 治疗者每次治疗获得1个正面硬币
            
            result_healer = add_emotion_coins(
                healer['id'], 
                positive=positive_coins_healer,
                source=f"治疗{healing_amount}点生命值"
            )
            
            if result_healer.get('success') and result_healer.get('coins_added'):
                msg = f"🎭 {healer['name']} 获得{positive_coins_healer}个正面情感硬币"
                if result_healer.get('upgrade_pending'):
                    msg += f"，准备升级到{result_healer['target_level']}级！"
                messages.append(msg)
            
            # 接受治疗时也获得1个正面情感硬币（基于次数）
            # 只有当治疗者和被治疗者不是同一人时才给被治疗者硬币
            if healer['id'] != target['id']:
                positive_coins_target = 1  # 被治疗者每次接受治疗获得1个正面硬币
                
                result_target = add_emotion_coins(
                    target['id'],
                    positive=positive_coins_target,
                    source=f"接受{healing_amount}点治疗"
                )
                
                if result_target.get('success') and result_target.get('coins_added'):
                    msg = f"🎭 {target['name']} 获得{positive_coins_target}个正面情感硬币"
                    if result_target.get('upgrade_pending'):
                        msg += f"，准备升级到{result_target['target_level']}级！"
                    messages.append(msg)
                    
        except Exception as e:
            print(f"处理治疗情感硬币时出错: {e}")
        
        return messages
    
    def process_dice_emotion_coins(self, character_id, dice_results, dice_sides, character_name):
        """
        处理骰子相关的情感硬币获取
        
        Args:
            character_id: 角色ID
            dice_results: 骰子结果列表
            dice_sides: 骰子面数
            character_name: 角色名称
            
        Returns:
            list: 情感硬币获取消息
        """
        messages = []
        
        try:
            from character.emotion_system import EmotionSystem
            
            positive_coins, negative_coins = EmotionSystem.get_emotion_coins_from_dice_roll(
                dice_results, dice_sides
            )
            
            if positive_coins > 0 or negative_coins > 0:
                result = add_emotion_coins(
                    character_id,
                    positive_coins=positive_coins,
                    negative_coins=negative_coins,
                    source=f"骰子结果：{dice_results}"
                )
                
                if result.get('success') and result.get('coins_added'):
                    coin_details = []
                    if positive_coins > 0:
                        coin_details.append(f"{positive_coins}个正面硬币")
                    if negative_coins > 0:
                        coin_details.append(f"{negative_coins}个负面硬币")
                    
                    msg = f"🎲 {character_name} 获得{' 和 '.join(coin_details)}"
                    if result.get('upgrade_pending'):
                        msg += f"，准备升级到{result['target_level']}级！"
                    messages.append(msg)
                    
        except Exception as e:
            print(f"处理骰子情感硬币时出错: {e}")
        
        return messages
    
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
