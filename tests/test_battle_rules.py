from __future__ import annotations

from conftest import lock_enemy_planning

import json

import pytest

from dewbot.models import BattlePhase, BattleRuleError


def _cooldown(world: object, skill_id: int) -> int:
    row = world.database.fetch_one(
        """
        SELECT remaining FROM battle_skill_cooldowns
        WHERE battle_id=? AND character_id=? AND skill_id=?
        """,
        (world.battle_id, world.hero_id, skill_id),
    )
    return int(row["remaining"]) if row is not None else 0


def _active_effect(world: object, character_id: int, effect_key: str):
    return world.database.fetch_one(
        """
        SELECT * FROM active_effects
        WHERE battle_id=? AND character_id=? AND effect_key=?
        """,
        (world.battle_id, character_id, effect_key),
    )


def _start(world: object, enemy_skill="skill.test.wait") -> None:
    battle_id, _messages = world.engine.start_battle([world.hero_id], [world.enemy_id])
    world.engine.use_skill(world.enemy_id, world.skill_ids[enemy_skill], [world.hero_id])
    lock_enemy_planning(world.engine)
    world.battle_id = battle_id


def test_turn_is_friendly_actions_then_enemy_actions_then_turn_end(world: object) -> None:
    _start(world)
    wait = world.skill_ids["skill.test.wait"]

    status = world.engine.battle_status()
    assert status["current_turn"] == 1
    assert status["phase"] == BattlePhase.FRIENDLY_ACTION.value

    with pytest.raises(BattleRuleError):
        world.engine.use_skill(world.enemy_id, wait, [world.hero_id])

    world.engine.use_skill(world.hero_id, wait, [world.enemy_id])
    world.engine.end_friendly_phase()
    assert world.engine.battle_status()["phase"] == BattlePhase.ENEMY_ACTION.value

    with pytest.raises(BattleRuleError):
        world.engine.use_skill(world.hero_id, wait, [world.enemy_id])

    world.engine.end_turn()
    lock_enemy_planning(world.engine)

    status = world.engine.battle_status()
    assert status["current_turn"] == 2
    assert status["phase"] == BattlePhase.FRIENDLY_ACTION.value


def test_manager_effect_resolves_a_friendly_wipe_immediately(world: object) -> None:
    _start(world)

    def wipe_friendlies(context: object) -> None:
        context.connection.execute(
            """
            UPDATE characters SET current_hp=0 WHERE id IN (
                SELECT character_id FROM battle_participants
                WHERE battle_id=? AND faction='FRIENDLY' AND active_in_stage=1
            )
            """,
            (context.battle_id,),
        )

    world.engine.registry.register("test_manager_wipe", wipe_friendlies)
    with world.database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO manager_skills(
                manager_skill_key,pack_key,name,handler_key,
                max_uses_per_battle,allowed_phase
            ) VALUES('manager.test.wipe','test.extension','Test Wipe',?,1,?)
            """,
            ("test_manager_wipe", BattlePhase.FRIENDLY_ACTION.value),
        )

    messages = world.engine.use_manager_skill("manager.test.wipe")

    battle = world.database.fetch_one(
        "SELECT status,result,phase FROM battles WHERE id=?", (world.battle_id,)
    )
    assert battle["status"] == "COMPLETE"
    assert battle["result"] == "DEFEAT"
    assert battle["phase"] == BattlePhase.BATTLE_END.value
    assert any("战败" in message for message in messages)


def test_normal_cooldown_only_advances_at_turn_end(world: object) -> None:
    _start(world)
    cooldown_skill = world.skill_ids["skill.test.cooldown"]
    wait = world.skill_ids["skill.test.wait"]

    world.engine.use_skill(world.hero_id, cooldown_skill, [world.enemy_id])
    assert _cooldown(world, cooldown_skill) == 2

    # A second friendly action and an enemy action must not advance cooldowns.
    # （我方行动耗尽后自动移交敌方阶段，无需手动 end_friendly_phase。）
    world.engine.use_skill(world.hero_id, wait, [world.enemy_id])
    assert _cooldown(world, cooldown_skill) == 2
    assert _cooldown(world, cooldown_skill) == 2

    world.engine.end_turn()
    lock_enemy_planning(world.engine)
    assert _cooldown(world, cooldown_skill) == 1
    with pytest.raises(BattleRuleError):
        world.engine.use_skill(world.hero_id, cooldown_skill, [world.enemy_id])

    world.engine.end_friendly_phase()
    world.engine.end_turn()
    lock_enemy_planning(world.engine)
    assert _cooldown(world, cooldown_skill) == 0
    world.engine.use_skill(world.hero_id, cooldown_skill, [world.enemy_id])


def test_generic_effects_clear_but_pending_effects_activate_next_turn(world: object) -> None:
    _start(world, "skill.common.delayed_weakness")
    guard = world.skill_ids["skill.common.guard"]
    delayed_weakness = world.skill_ids["skill.common.delayed_weakness"]

    world.engine.use_skill(world.hero_id, guard)
    shield = _active_effect(world, world.hero_id, "status.shield")
    assert shield is not None
    assert int(shield["intensity"]) == 8

    world.engine.end_friendly_phase()
    # The planned skill has not executed yet, so no next-turn effect is queued.
    assert _active_effect(world, world.hero_id, "status.weakness") is None
    assert world.database.fetch_one("SELECT id FROM battle_pending_effects WHERE battle_id=?", (world.battle_id,)) is None

    world.engine.end_turn()
    lock_enemy_planning(world.engine)

    assert _active_effect(world, world.hero_id, "status.shield") is None
    weakness = _active_effect(world, world.hero_id, "status.weakness")
    assert weakness is not None
    assert int(weakness["intensity"]) == 2
    assert world.database.fetch_one(
        "SELECT id FROM battle_pending_effects WHERE battle_id=?",
        (world.battle_id,),
    ) is None

    # With no replacement pending effect, the activated weakness also expires
    # at the following TURN_END.
    world.engine.end_friendly_phase()
    world.engine.end_turn()
    lock_enemy_planning(world.engine)
    assert _active_effect(world, world.hero_id, "status.weakness") is None


def test_fixed_status_damage_does_not_reduce_stagger(world: object) -> None:
    _start(world)
    ignite = world.skill_ids["skill.test.ignite"]
    before = world.engine.get_character(world.enemy_id)

    world.engine.use_skill(world.hero_id, ignite, [world.enemy_id])
    world.engine.end_friendly_phase()
    world.engine.end_turn()
    lock_enemy_planning(world.engine)

    after = world.engine.get_character(world.enemy_id)
    assert after["current_hp"] == before["current_hp"] - 7
    assert after["current_stagger"] == before["current_stagger"]
    assert after["is_staggered"] == 0
    event = world.database.fetch_one(
        """
        SELECT payload_json FROM battle_logs
        WHERE battle_id=? AND event_type='STATUS_DAMAGE'
        ORDER BY id DESC LIMIT 1
        """,
        (world.battle_id,),
    )
    assert event is not None
    snapshot = json.loads(event["payload_json"])["snapshot"]
    assert snapshot["metadata"]["damage_source"] == "STATUS"
    assert snapshot["hits"][0]["hit"] is False
    assert snapshot["hits"][0]["source_key"] == "status.burn"


def test_reaching_emotion_level_four_grants_one_battle_action(world: object) -> None:
    _start(world)
    original = world.engine.get_character(world.hero_id)
    assert original["max_actions"] == 2
    cooldown_skill = world.skill_ids["skill.test.cooldown"]
    world.engine.use_skill(world.hero_id, cooldown_skill, [world.enemy_id])
    assert _cooldown(world, cooldown_skill) == 2

    with world.database.transaction() as connection:
        connection.execute(
            """
            UPDATE characters SET emotion_level=3,positive_emotion_coins=7,
                negative_emotion_coins=0,pending_emotion_upgrade=1
            WHERE id=?
            """,
            (world.hero_id,),
        )

    world.engine.end_friendly_phase()
    world.engine.end_turn()
    lock_enemy_planning(world.engine)

    level_four = world.engine.get_character(world.hero_id)
    assert level_four["emotion_level"] == 4
    assert level_four["max_actions"] == 3
    assert level_four["current_actions"] == 3
    assert level_four["emotion_bonus_actions"] == 1
    # TURN_END natural progress and the level-up reward each advance normal CD once.
    assert _cooldown(world, cooldown_skill) == 0

    # Level five must not grant the level-four bonus a second time.
    with world.database.transaction() as connection:
        connection.execute(
            """
            UPDATE characters SET positive_emotion_coins=9,
                negative_emotion_coins=0,pending_emotion_upgrade=1
            WHERE id=?
            """,
            (world.hero_id,),
        )
    world.engine.end_friendly_phase()
    world.engine.end_turn()
    lock_enemy_planning(world.engine)
    level_five = world.engine.get_character(world.hero_id)
    assert level_five["emotion_level"] == 5
    assert level_five["max_actions"] == 3
    assert level_five["emotion_bonus_actions"] == 1

    world.engine.end_battle()
    restored = world.engine.get_character(world.hero_id)
    assert restored["max_actions"] == 2
    assert restored["current_actions"] == 2
    assert restored["emotion_bonus_actions"] == 0


def test_any_ego_can_only_be_used_once_per_character_per_battle(world: object) -> None:
    _start(world)
    ego_one = world.skill_ids["skill.test.ego_one"]
    ego_two = world.skill_ids["skill.test.ego_two"]
    with world.database.transaction() as connection:
        connection.execute(
            "UPDATE characters SET emotion_level=1 WHERE id=?", (world.hero_id,)
        )

    world.engine.use_skill(world.hero_id, ego_one, [world.enemy_id])

    usage = world.database.fetch_one(
        """
        SELECT ego_used,used_skill_id FROM battle_ego_usage
        WHERE battle_id=? AND character_id=?
        """,
        (world.battle_id, world.hero_id),
    )
    assert usage is not None
    assert int(usage["ego_used"]) == 1
    assert int(usage["used_skill_id"]) == ego_one
    assert _cooldown(world, ego_one) == 0

    ego_two_state = next(
        skill
        for skill in world.engine.list_skills(world.hero_id)
        if int(skill["id"]) == ego_two
    )
    assert ego_two_state["ego_used"] is True
    assert ego_two_state["available"] is False
    with pytest.raises(BattleRuleError):
        world.engine.use_skill(world.hero_id, ego_two, [world.enemy_id])

    # Usage is battle-scoped, so a new battle permits a different E.G.O.
    world.engine.end_battle()
    second_battle, _ = world.engine.start_battle([world.hero_id], [world.enemy_id])
    lock_enemy_planning(world.engine)
    world.battle_id = second_battle
    with world.database.transaction() as connection:
        connection.execute(
            "UPDATE characters SET emotion_level=1 WHERE id=?", (world.hero_id,)
        )
    world.engine.use_skill(world.hero_id, ego_two, [world.enemy_id])


def test_top_level_skill_immediately_defeats_battle_when_last_friendly_dies(
    world: object,
) -> None:
    _start(world)
    hero = world.engine.get_character(world.hero_id)
    with world.database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO active_effects(
                battle_id,character_id,effect_key,category,intensity,stacks,
                params_json
            ) VALUES(?,?,?,'REGULAR',?,1,'{}')
            """,
            (
                world.battle_id,
                world.hero_id,
                "status.bleeding",
                int(hero["current_hp"]) + 1,
            ),
        )

    result = world.engine.use_skill(
        world.hero_id,
        world.skill_ids["skill.test.wait"],
        [world.enemy_id],
    )

    battle = world.database.fetch_one(
        "SELECT status,result FROM battles WHERE id=?", (world.battle_id,)
    )
    assert battle["status"] == "COMPLETE"
    assert battle["result"] == "DEFEAT"
    assert result.phase == BattlePhase.BATTLE_END


def test_battle_end_clears_runtime_tables_but_keeps_history(world: object) -> None:
    _start(world)
    world.engine.use_skill(
        world.hero_id, world.skill_ids["skill.common.guard"]
    )
    world.engine.use_skill(
        world.hero_id,
        world.skill_ids["skill.test.cooldown"],
        [world.enemy_id],
    )
    world.engine.end_battle()

    for table in (
        "active_effects",
        "battle_pending_effects",
        "battle_registered_behaviors",
        "battle_skill_cooldowns",
        "battle_ego_usage",
        "battle_active_pages",
    ):
        row = world.database.fetch_one(
            f"SELECT COUNT(*) AS amount FROM {table} WHERE battle_id=?",
            (world.battle_id,),
        )
        assert row is not None
        assert int(row["amount"]) == 0
    assert world.database.fetch_one(
        "SELECT 1 FROM battle_logs WHERE battle_id=?", (world.battle_id,)
    ) is not None
    assert world.database.fetch_one(
        "SELECT 1 FROM battle_content_versions WHERE battle_id=?", (world.battle_id,)
    ) is not None
