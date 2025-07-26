"""
四种状态效果目标系统测试指南

测试新的状态效果目标规则：
- self_buff：施加给施法者自己的增益效果
- self_debuff：施加给施法者自己的减益效果
- buff：施加给目标的增益效果
- debuff：施加给目标的减益效果
"""

print("=== 四种状态效果目标系统测试指南 ===")
print()

print("🎯 新系统核心概念:")
print("1. self_buff - 无论什么技能，都给施法者自己增益")
print("2. self_debuff - 无论什么技能，都给施法者自己减益")
print("3. buff - 无论什么技能，都给目标增益")
print("4. debuff - 无论什么技能，都给目标减益")
print()

print("📋 测试准备:")
print("1. 创建测试角色:")
print("   /cc 艾丽丝 100 15 8")
print("   /cc 鲍勃 80 12 6")
print("   /ce 邪恶法师 90 14 5")
print()

print("2. 为角色添加测试技能:")
print("   /sm 艾丽丝")
print("   添加技能:")
print("   - 强壮打击 (ID: 17) - self_buff: 伤害+自己获得强壮")
print("   - 守护祝福 (ID: 18) - buff: 纯buff，给目标守护")
print("   - 狂怒攻击 (ID: 29) - self_buff: 伤害+自己获得强壮")
print("   - 四重奥秘 (ID: 28) - 演示所有四种效果")
print()

print("   /sm 邪恶法师")
print("   添加技能:")
print("   - 烧伤攻击 (ID: 19) - debuff: 伤害+目标烧伤")
print("   - 虚弱诅咒 (ID: 21) - debuff: 纯debuff，给目标虚弱")
print("   - 生命转移 (ID: 30) - self_debuff: 治疗+自己获得虚弱")
print()

print("🧪 核心测试场景:")
print()

print("测试1: self_buff效果")
print("1. /join 艾丽丝 邪恶法师")
print("2. /attack → 选择艾丽丝 → 选择强壮打击 → 选择邪恶法师")
print("   预期结果：造成伤害 + 艾丽丝(施法者)获得强壮效果")
print("3. /show 艾丽丝")
print("   确认：艾丽丝有强壮状态，邪恶法师没有")
print()

print("测试2: buff效果（目标导向）")
print("1. /attack → 选择艾丽丝 → 选择守护祝福 → 选择鲍勃")
print("   预期结果：无伤害，鲍勃(目标)获得守护效果")
print("2. /show 鲍勃")
print("   确认：鲍勃有守护状态")
print("3. /show 艾丽丝")
print("   确认：艾丽丝没有守护状态")
print()

print("测试3: debuff效果（目标导向）")
print("1. /enemy_attack → 选择邪恶法师 → 选择虚弱诅咒 → 选择艾丽丝")
print("   预期结果：无伤害，艾丽丝(目标)获得虚弱效果")
print("2. /show 艾丽丝")
print("   确认：艾丽丝有虚弱状态")
print("3. /show 邪恶法师")
print("   确认：邪恶法师没有虚弱状态")
print()

print("测试4: self_debuff效果")
print("1. /enemy_attack → 选择邪恶法师 → 选择生命转移 → 选择邪恶法师")
print("   预期结果：邪恶法师恢复生命 + 邪恶法师(施法者)获得虚弱效果")
print("2. /show 邪恶法师")
print("   确认：邪恶法师有虚弱状态（自己给自己的）")
print()

print("🎭 高级测试: 四重奥秘")
print("这个技能演示所有四种效果同时作用:")
print("1. /attack → 选择艾丽丝 → 选择四重奥秘 → 选择邪恶法师")
print("   预期结果:")
print("   - 造成魔法伤害给邪恶法师")
print("   - 艾丽丝获得强壮(self_buff) + 虚弱(self_debuff)")
print("   - 邪恶法师获得守护(buff) + 易伤(debuff)")
print("2. /show 艾丽丝")
print("   确认：艾丽丝同时有强壮和虚弱状态")
print("3. /show 邪恶法师")
print("   确认：邪恶法师同时有守护和易伤状态")
print()

print("🔄 对比测试:")
print()

print("对比1: 不同技能给自己效果")
print("- 强壮打击(伤害技能): self_buff → 自己获得强壮")
print("- 狂怒攻击(伤害技能): self_buff → 自己获得强壮")
print("- 生命转移(治疗技能): self_debuff → 自己获得虚弱")
print("→ 验证：无论技能类型，self_*效果都给施法者")
print()

print("对比2: 不同技能给目标效果")
print("- 烧伤攻击(伤害技能): debuff → 目标获得烧伤")
print("- 虚弱诅咒(debuff技能): debuff → 目标获得虚弱")
print("- 守护祝福(buff技能): buff → 目标获得守护")
print("→ 验证：无论技能类型，buff/debuff效果都给目标")
print()

print("📊 验证要点:")
print()

print("✅ self_buff/self_debuff验证:")
print("- 无论伤害、治疗、buff、debuff技能")
print("- self_*效果都施加给施法者自己")
print("- 即使目标是别人，self_*效果依然给自己")
print()

print("✅ buff/debuff验证:")
print("- 无论伤害、治疗、buff、debuff技能")
print("- buff/debuff效果都施加给选中的目标")
print("- 即使是治疗技能，buff效果也给目标而非施法者")
print()

print("✅ 混合效果验证:")
print("- 一个技能可以同时有多种效果类型")
print("- 每种效果按其类型规则分别处理目标")
print("- 四重奥秘是最佳测试案例")
print()

print("🎯 实战测试建议:")
print("1. 先测试单一效果技能，确保基础逻辑正确")
print("2. 再测试混合效果技能，验证复杂情况")
print("3. 观察战斗中的实际数值变化")
print("4. 用/end_turn测试状态效果的回合处理")
print()

print("现在可以开始测试新的四种状态效果目标系统了！")
print("记住：self_*给自己，buff/debuff给目标！")
