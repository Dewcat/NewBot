"""
重新设计的Buff/Debuff系统测试指南

本指南将帮助您测试新的两种状态效果技能类型
"""

print("=== 新Buff/Debuff系统测试指南 ===")
print()

print("🔄 系统概述:")
print("1. 伴随型：damage/healing技能 + 附带状态效果")
print("2. 纯粹型：专门的buff/debuff技能，可选择目标")
print()

print("📋 测试准备:")
print("1. 创建测试角色:")
print("   /cc 艾丽丝 100 15 8")
print("   /cc 鲍勃 80 12 6")
print("   /ce 邪恶法师 90 14 5")
print()

print("2. 为角色添加新技能:")
print("   /sm 艾丽丝")
print("   添加技能:")
print("   - 强壮打击 (ID: 17) - 伤害+自己获得强壮")
print("   - 守护祝福 (ID: 18) - 纯buff，给目标守护")
print("   - 强化术 (ID: 25) - 纯buff，给目标强壮")
print("   - 护盾术 (ID: 24) - 纯buff，给目标护盾")
print()

print("   /sm 邪恶法师")
print("   添加技能:")
print("   - 烧伤攻击 (ID: 19) - 伤害+目标烧伤")
print("   - 虚弱诅咒 (ID: 21) - 纯debuff，给目标虚弱")
print("   - 易伤标记 (ID: 22) - 纯debuff，给目标易伤")
print()

print("🎯 测试场景:")
print()

print("场景1: 伴随型状态效果测试")
print("1. /join 艾丽丝 邪恶法师")
print("2. /attack → 选择艾丽丝 → 选择强壮打击 → 选择邪恶法师")
print("   预期结果：造成伤害 + 艾丽丝获得强壮效果")
print("3. /show 艾丽丝")
print("   确认：艾丽丝有强壮状态")
print()

print("场景2: 纯增益技能测试")
print("1. /attack → 选择艾丽丝 → 选择守护祝福 → 选择鲍勃")
print("   预期结果：无伤害，鲍勃获得守护效果")
print("2. /show 鲍勃")
print("   确认：鲍勃有守护状态")
print()

print("场景3: 纯减益技能测试")
print("1. /enemy_attack → 选择邪恶法师 → 选择虚弱诅咒 → 选择艾丽丝")
print("   预期结果：无伤害，艾丽丝获得虚弱效果")
print("2. /show 艾丽丝")
print("   确认：艾丽丝有虚弱状态")
print()

print("场景4: 目标选择灵活性测试")
print("1. /attack → 选择艾丽丝 → 选择强化术 → 选择鲍勃")
print("   预期结果：鲍勃获得强壮效果（不是施法者艾丽丝）")
print("2. /enemy_attack → 选择邪恶法师 → 选择易伤标记 → 选择鲍勃")
print("   预期结果：鲍勃获得易伤效果")
print()

print("场景5: 状态效果叠加和战斗测试")
print("1. 给多个角色施加不同状态效果")
print("2. 进行正常战斗，观察状态效果如何影响伤害")
print("3. /end_turn 观察状态效果的回合处理")
print()

print("🔍 验证要点:")
print()

print("✅ 伴随型技能验证:")
print("- 造成了正确的伤害")
print("- 状态效果施加给正确的目标（buff→自己，debuff→目标）")
print("- 伤害和状态效果同时生效")
print()

print("✅ 纯粹型技能验证:")
print("- 没有造成任何伤害")
print("- 状态效果施加给选中的目标")
print("- 可以自由选择友方或敌方目标")
print()

print("✅ 目标选择验证:")
print("- 纯buff技能：可以选择任意角色作为目标")
print("- 纯debuff技能：可以选择任意角色作为目标")
print("- 伴随型技能：状态效果目标按规则自动确定")
print()

print("📊 技能对比测试:")
print()
print("对比强壮打击 vs 强化术:")
print("- 强壮打击：造成伤害 + 自己获得强壮")
print("- 强化术：无伤害 + 选中目标获得强壮")
print()

print("对比烧伤攻击 vs 虚弱诅咒:")
print("- 烧伤攻击：造成伤害 + 目标获得烧伤")
print("- 虚弱诅咒：无伤害 + 选中目标获得虚弱")
print()

print("🎮 战术应用测试:")
print("1. 开战前用纯buff技能预先强化队友")
print("2. 战斗中用伴随型技能获得即时收益")
print("3. 用纯debuff技能精确削弱特定敌人")
print("4. 观察不同策略的效果差异")
print()

print("💡 高级测试:")
print("1. 测试护盾术的护盾机制（不受回合限制）")
print("2. 测试状态效果的叠加规则")
print("3. 测试回合结束时的状态处理")
print("4. 测试/reset_all是否正确清除所有状态")
print()

print("现在可以开始测试新的Buff/Debuff系统了！")
print("记住：伴随型有伤害，纯粹型可选目标！")
