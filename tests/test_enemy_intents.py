from __future__ import annotations

import json
import pytest
from dewbot.models import BattleRuleError, Faction


def setup(world, kind="EVADE", power="10", damage="5", enemies=2):
    with world.database.transaction() as c:
        c.execute("UPDATE character_templates SET metadata_json=? WHERE template_key='unit.test_hero'", (json.dumps({"defense_skill": {"kind": kind, "power": power}}),))
        c.execute("UPDATE skill_behaviors SET effect_value=? WHERE behavior_key='behavior.test.wait.damage'", (damage,))
    foes = [world.enemy_id]
    if enemies == 2:
        foes.append(world.engine.spawn_character("enemy.test_dummy", Faction.ENEMY))
    world.engine.start_battle([world.hero_id], foes)
    return foes


def plan(world, foes):
    for foe in foes:
        world.engine.use_skill(foe, world.skill_ids["skill.test.wait"], [world.hero_id])
    world.engine.finish_enemy_planning()


def test_planning_is_visible_locked_and_does_not_deal_damage(world):
    foes = setup(world)
    before = world.engine.get_character(world.hero_id)["current_hp"]
    with pytest.raises(BattleRuleError):
        world.engine.use_skill(world.hero_id, world.skill_ids["skill.test.wait"], [foes[0]])
    plan(world, foes)
    status = world.engine.battle_status()
    assert len(status["enemy_intents"]) == 2
    assert status["enemy_intents"][0]["skill_name"] == "Wait"
    assert status["enemy_intents"][0]["target_ids"] == [world.hero_id]
    assert world.engine.get_character(world.hero_id)["current_hp"] == before
    with pytest.raises(BattleRuleError):
        world.engine.use_skill(foes[0], world.skill_ids["skill.test.wait"], [world.hero_id])
    world.engine.end_friendly_phase()
    world.engine.end_turn()
    assert world.engine.get_character(world.hero_id)["current_hp"] == before - 10
    assert world.engine.battle_status()["phase"] == "ENEMY_PLANNING"


def test_enemy_planning_locks_when_last_available_action_is_used(world):
    foes = setup(world)
    with world.database.transaction() as c:
        c.executemany("UPDATE characters SET current_actions=1 WHERE id=?", [(foe,) for foe in foes])
    first = world.engine.use_skill(foes[0], world.skill_ids["skill.test.wait"], [world.hero_id])
    assert first.phase.value == "ENEMY_PLANNING"
    final = world.engine.use_skill(foes[1], world.skill_ids["skill.test.wait"], [world.hero_id])
    assert final.phase.value == "FRIENDLY_ACTION"
    assert world.engine.battle_status()["phase"] == "FRIENDLY_ACTION"
    assert any("敌方行动已确定" in line for line in final.messages)
    assert world.engine.get_character(world.hero_id)["current_hp"] == 200
    assert all(intent["status"] == "PENDING" for intent in world.engine.battle_status()["enemy_intents"])


def test_evade_reuses_across_enemies_and_equal_points_succeed(world):
    foes = setup(world, power="5")
    plan(world, foes)
    before = world.engine.get_character(world.hero_id)["current_hp"]
    world.engine.declare_defense(world.hero_id)
    world.engine.end_friendly_phase()
    messages = world.engine.end_turn()
    assert world.engine.get_character(world.hero_id)["current_hp"] == before
    assert sum("成功，可继续闪避" in m for m in messages) == 2


def test_failed_evade_ends_reuse(world):
    foes = setup(world, power="4")
    plan(world, foes)
    world.engine.declare_defense(world.hero_id)
    world.engine.end_friendly_phase()
    messages = world.engine.end_turn()
    assert world.engine.get_character(world.hero_id)["current_hp"] == 190
    assert sum("失败，本回合闪避结束" in m for m in messages) == 1


def test_player_attack_staggers_enemy_before_execution(world):
    foes = setup(world, damage="5", enemies=1)
    plan(world, foes)
    with world.database.transaction() as c:
        c.execute("UPDATE characters SET current_stagger=1 WHERE id=?", (foes[0],))
    world.engine.use_skill(world.hero_id, world.skill_ids["skill.test.wait"], [foes[0]])
    assert world.engine.battle_status()["enemy_intents"][0]["disabled"]
    world.engine.end_friendly_phase()
    messages = world.engine.end_turn()
    assert any("取消" in m for m in messages)
    assert world.engine.get_character(world.hero_id)["current_hp"] == 200


@pytest.mark.parametrize("kind", ["INTERCEPT", "MEET"])
def test_redirect_is_deferred_and_counter_happens_after_damage(world, kind):
    setup(world, kind=kind, power="3", enemies=1)
    # Add a second friendly through the engine's existing reinforcement API.
    ally = world.engine.spawn_character("unit.test_hero", Faction.FRIENDLY)
    with world.database.transaction() as c:
        world.engine._add_participants(c, world.engine.battle_status()["id"], [ally], Faction.FRIENDLY, 1)
    world.engine.use_skill(world.enemy_id, world.skill_ids["skill.test.wait"], [ally])
    world.engine.finish_enemy_planning()
    intent = world.engine.battle_status()["enemy_intents"][0]
    world.engine.declare_defense(world.hero_id, intent["id"])
    assert world.engine.battle_status()["enemy_intents"][0]["target_ids"] == [ally]
    detail = world.engine.battle_status()["enemy_intents"][0]["skill_effects"][0]
    assert detail["effect_type"] == "DAMAGE"
    assert detail["value"] == "5"
    assert detail["target_names"] == [world.engine.get_character(world.hero_id)["name"]]
    world.engine.end_friendly_phase()
    messages = world.engine.end_turn()
    assert world.engine.get_character(ally)["current_hp"] == 200
    assert world.engine.get_character(world.hero_id)["current_hp"] == (198 if kind == "INTERCEPT" else 195)
    assert world.engine.get_character(world.enemy_id)["current_hp"] == (500 if kind == "INTERCEPT" else 497)
    assert any("的攻击被" in m for m in messages)


@pytest.mark.parametrize("kind", ["INTERCEPT", "MEET"])
@pytest.mark.parametrize("selected", [0, 1])
def test_redirect_defense_only_responds_to_bound_skill(world, kind, selected):
    foes = setup(world, kind=kind, power="3")
    plan(world, foes)
    intents = world.engine.battle_status()["enemy_intents"]
    world.engine.declare_defense(world.hero_id, intents[selected]["id"])
    rows = world.engine.battle_status()["enemy_intents"]
    assert rows[selected]["redirect"]["actor_id"] == world.hero_id
    assert rows[1-selected]["redirect"] is None
    world.engine.end_friendly_phase()
    messages = world.engine.end_turn()
    assert world.engine.get_character(world.hero_id)["current_hp"] == (193 if kind == "INTERCEPT" else 190)
    assert sum("防御点数" in line for line in messages) == (1 if kind == "INTERCEPT" else 0)
    assert sum("发动反击" in line for line in messages) == (1 if kind == "MEET" else 0)
    assert world.engine.get_character(foes[1-selected])["current_hp"] == 500


def test_evade_success_then_failure_stops_even_against_later_weak_hit(world):
    foes = setup(world, power="1d6", damage="5")
    # Three separately planned skills, ordered by submission.
    world.engine.use_skill(foes[0], world.skill_ids["skill.test.wait"], [world.hero_id])
    world.engine.use_skill(foes[1], world.skill_ids["skill.test.wait"], [world.hero_id])
    world.engine.use_skill(foes[0], world.skill_ids["skill.test.wait"], [world.hero_id])
    world.engine.finish_enemy_planning()
    world.engine.declare_defense(world.hero_id)
    world.engine.end_friendly_phase()
    from unittest.mock import patch
    with patch.object(world.engine.rng, "randint", side_effect=[6, 1]) as rolls:
        messages = world.engine.end_turn()
    assert rolls.call_count == 2
    assert world.engine.get_character(world.hero_id)["current_hp"] == 190
    assert sum("成功，可继续闪避" in m for m in messages) == 1


def test_evade_reuses_for_each_damage_behavior_in_one_skill(world):
    foes = setup(world, power="5", enemies=1)
    with world.database.transaction() as c:
        c.execute("INSERT INTO skill_behaviors(behavior_key,skill_id,timing,effect_type,effect_value,sort_order) VALUES('test.second_hit',?,'ON','DAMAGE','5',1)", (world.skill_ids["skill.test.wait"],))
    plan(world, foes)
    world.engine.declare_defense(world.hero_id)
    world.engine.end_friendly_phase()
    messages = world.engine.end_turn()
    assert world.engine.get_character(world.hero_id)["current_hp"] == 200
    assert sum("成功，可继续闪避" in m for m in messages) == 2


def test_intents_and_defense_survive_engine_restart(world):
    from dewbot.engine import BattleEngine
    foes = setup(world)
    plan(world, foes)
    world.engine.declare_defense(world.hero_id)
    restarted = BattleEngine(world.database)
    assert len(restarted.battle_status()["enemy_intents"]) == 2
    restarted.end_friendly_phase()
    restarted.end_turn()
    assert restarted.get_character(world.hero_id)["current_hp"] == 200


def test_dead_locked_target_does_not_retarget(world):
    foes = setup(world, enemies=1)
    ally = world.engine.spawn_character("unit.test_hero", Faction.FRIENDLY)
    with world.database.transaction() as c:
        world.engine._add_participants(c, world.engine.battle_status()["id"], [ally], Faction.FRIENDLY, 1)
    plan(world, foes)
    with world.database.transaction() as c:
        c.execute("UPDATE characters SET current_hp=0 WHERE id=?", (world.hero_id,))
    world.engine.end_friendly_phase()
    messages = world.engine.end_turn()
    assert world.engine.get_character(ally)["current_hp"] == 200
    assert any("不重新选择目标" in m for m in messages)


def test_random_targets_are_selected_at_planning(world):
    foes = setup(world, enemies=1)
    with world.database.transaction() as c:
        c.execute("UPDATE skills SET target_method='RANDOM',target_param=1 WHERE id=?", (world.skill_ids["skill.test.wait"],))
    world.engine.use_skill(foes[0], world.skill_ids["skill.test.wait"])
    world.engine.finish_enemy_planning()
    from unittest.mock import patch
    world.engine.end_friendly_phase()
    with patch.object(world.engine.rng, "choice", side_effect=AssertionError("must not retarget")):
        world.engine.end_turn()
    assert world.engine.get_character(world.hero_id)["current_hp"] == 195


def test_latest_redirect_updates_preview_and_execution(world):
    foes = setup(world, kind="INTERCEPT", power="10", enemies=1)
    ally = world.engine.spawn_character("unit.test_hero", Faction.FRIENDLY)
    with world.database.transaction() as c:
        world.engine._add_participants(c, world.engine.battle_status()["id"], [ally], Faction.FRIENDLY, 1)
    plan(world, foes)
    intent_id = world.engine.battle_status()["enemy_intents"][0]["id"]
    world.engine.declare_defense(world.hero_id, intent_id)
    with world.database.transaction() as c:
        c.execute("UPDATE character_templates SET metadata_json=? WHERE template_key='unit.test_hero'", (json.dumps({"defense_skill": {"kind": "MEET", "power": "10"}}),))
    world.engine.declare_defense(ally, intent_id)
    intent = world.engine.battle_status()["enemy_intents"][0]
    assert intent["effective_target_ids"] == [ally]
    assert intent["redirect"]["label"] == "迎击"
    assert intent["redirect"]["actor_id"] == ally
    world.engine.end_friendly_phase()
    world.engine.end_turn()
    assert world.engine.get_character(world.hero_id)["current_hp"] == 200
    assert world.engine.get_character(ally)["current_hp"] == 195
    assert world.engine.get_character(foes[0])["current_hp"] == 490


@pytest.mark.parametrize("kind", ["GUARD", "EVADE", "COUNTER"])
@pytest.mark.parametrize("automatic", [False, True])
def test_defenses_respond_to_aoe_and_automatic_targets(world, kind, automatic):
    foes = setup(world, kind=kind, power="10", enemies=1)
    with world.database.transaction() as c:
        if automatic:
            c.execute("UPDATE skills SET target_scope='SELF',target_method='SELF' WHERE id=?", (world.skill_ids["skill.test.wait"],))
            c.execute("UPDATE skill_behaviors SET target_source='AUTO',target_scope='ENEMY',target_method='ALL_TARGETS' WHERE skill_id=?", (world.skill_ids["skill.test.wait"],))
        else:
            c.execute("UPDATE skills SET target_method='ALL_TARGETS' WHERE id=?", (world.skill_ids["skill.test.wait"],))
    plan(world, foes)
    assert world.engine.battle_status()["enemy_intents"][0]["area_target_ids"] == [world.hero_id]
    world.engine.declare_defense(world.hero_id)
    world.engine.end_friendly_phase()
    world.engine.end_turn()
    assert world.engine.get_character(world.hero_id)["current_hp"] == (195 if kind == "COUNTER" else 200)
    assert world.engine.get_character(foes[0])["current_hp"] == (490 if kind == "COUNTER" else 500)


@pytest.mark.parametrize("automatic", [False, True])
def test_friendly_area_attack_preserves_actual_scope_in_preview(world, automatic):
    foes = setup(world)
    plan(world, foes)
    with world.database.transaction() as c:
        if automatic:
            c.execute("UPDATE skills SET target_scope='SELF',target_method='SELF' WHERE id=?", (world.skill_ids["skill.test.wait"],))
            c.execute("UPDATE skill_behaviors SET target_source='AUTO',target_scope='ENEMY',target_method='ALL_TARGETS' WHERE skill_id=?", (world.skill_ids["skill.test.wait"],))
        else:
            c.execute("UPDATE skills SET target_method='ALL_TARGETS' WHERE id=?", (world.skill_ids["skill.test.wait"],))
    world.engine.use_skill(world.hero_id, world.skill_ids["skill.test.wait"])
    attack = world.engine.battle_status()["friendly_attacks"][0]
    assert set(attack["area_target_ids"]) == set(foes)
    assert set(attack["target_ids"]) == set(foes)
