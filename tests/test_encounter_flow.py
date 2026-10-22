from __future__ import annotations

from conftest import lock_enemy_planning

import json

import pytest

from dewbot.content import ContentLoader
from dewbot.engine import BattleEngine
from dewbot.models import BattlePhase, BattleRuleError, Faction

from conftest import BASE_PACK


CORE_PERSONAS = BASE_PACK.with_name("core_personas.json")
SHOWCASE_PACK = BASE_PACK.with_name("test_showcase.json")


def _engine(database: object) -> BattleEngine:
    loader = ContentLoader(database)
    loader.load_path(BASE_PACK)
    loader.load_path(CORE_PERSONAS)
    return BattleEngine(database)


def _showcase_engine(database: object) -> BattleEngine:
    loader = ContentLoader(database)
    loader.load_path(BASE_PACK)
    loader.load_path(CORE_PERSONAS)
    loader.load_path(SHOWCASE_PACK)
    return BattleEngine(database)


@pytest.mark.parametrize("result", ["ABORTED", "VICTORY"])
def test_battle_finish_heals_friendlies_and_removes_generated_enemies(
    database: object, result: str
) -> None:
    engine = _engine(database)
    setup_id = engine.prepare_encounter("encounter.training_ground")
    jue = engine.get_core_character("珏")
    persona = next(
        item for item in engine.list_personas(int(jue["id"])) if item["is_default"]
    )
    engine.add_core_to_setup(int(jue["id"]), int(persona["id"]), setup_id=setup_id)
    helper = engine.spawn_character("unit.training_assistant", Faction.FRIENDLY)
    engine.add_noncore_friendlies_to_setup([helper], setup_id=setup_id)
    battle_id, _ = engine.launch_prepared_battle(setup_id)
    lock_enemy_planning(engine)

    generated_enemy_ids = [
        int(row["character_id"])
        for row in database.fetch_all(
            "SELECT character_id FROM battle_spawn_origins WHERE battle_id=?",
            (battle_id,),
        )
    ]
    assert generated_enemy_ids
    with database.transaction() as connection:
        connection.execute(
            """
            UPDATE characters SET current_hp=1,current_actions=0,current_stagger=1,
                is_staggered=1,stagger_turns=2,emotion_level=3,
                positive_emotion_coins=2,negative_emotion_coins=1
            WHERE id IN (?,?)
            """,
            (int(jue["id"]), helper),
        )

    engine.end_battle(result)

    for character_id in (int(jue["id"]), helper):
        character = engine.get_character(character_id)
        assert int(character["current_hp"]) == int(character["max_hp"])
        assert int(character["current_actions"]) == int(character["max_actions"])
        assert int(character["current_stagger"]) == int(character["max_stagger"])
        assert int(character["is_staggered"]) == 0
        assert int(character["emotion_level"]) == 0
    assert not database.fetch_all(
        "SELECT id FROM characters WHERE id IN ("
        + ",".join("?" for _ in generated_enemy_ids)
        + ")",
        tuple(generated_enemy_ids),
    )
    final_log = database.fetch_one(
        """
        SELECT payload_json FROM battle_logs
        WHERE battle_id=? AND event_type='BATTLE_END'
        """,
        (battle_id,),
    )
    assert final_log is not None
    assert json.loads(final_log["payload_json"])["participant_factions"]


def test_persona_dummy_has_no_actions_and_auto_skips_enemy_phase(
    database: object,
) -> None:
    engine = _showcase_engine(database)
    setup_id = engine.prepare_encounter("encounter.showcase.persona_dummy")
    jue = engine.get_core_character("珏")
    persona = next(
        item for item in engine.list_personas(int(jue["id"])) if item["is_default"]
    )
    engine.add_core_to_setup(int(jue["id"]), int(persona["id"]), setup_id=setup_id)
    battle_id, _ = engine.launch_prepared_battle(setup_id)
    lock_enemy_planning(engine)
    dummy = database.fetch_one(
        """
        SELECT c.current_hp,c.max_hp,c.current_actions,c.max_actions
        FROM battle_spawn_origins o
        JOIN characters c ON c.id=o.character_id
        WHERE o.battle_id=?
        """,
        (battle_id,),
    )
    assert dummy is not None
    assert (int(dummy["current_hp"]), int(dummy["max_hp"])) == (9999, 9999)
    assert (int(dummy["current_actions"]), int(dummy["max_actions"])) == (0, 0)

    messages = engine.end_friendly_phase()
    status = engine.battle_status()
    assert "敌方行动阶段" in messages
    assert status["phase"] == BattlePhase.FRIENDLY_ACTION.value
    assert int(status["current_turn"]) == 2


def test_startup_cleanup_repairs_legacy_completed_battle(database: object) -> None:
    engine = _engine(database)
    setup_id = engine.prepare_encounter("encounter.training_ground")
    jue = engine.get_core_character("珏")
    persona = next(
        item for item in engine.list_personas(int(jue["id"])) if item["is_default"]
    )
    engine.add_core_to_setup(int(jue["id"]), int(persona["id"]), setup_id=setup_id)
    battle_id, _ = engine.launch_prepared_battle(setup_id)
    lock_enemy_planning(engine)
    enemy_ids = [
        int(row["character_id"])
        for row in database.fetch_all(
            "SELECT character_id FROM battle_spawn_origins WHERE battle_id=?",
            (battle_id,),
        )
    ]
    with database.transaction() as connection:
        connection.execute(
            "UPDATE characters SET current_hp=1 WHERE id=?", (int(jue["id"]),)
        )
        connection.execute(
            """
            UPDATE battles SET status='COMPLETE',phase='BATTLE_END',
                result='ABORTED',ended_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (battle_id,),
        )
        connection.execute(
            "UPDATE battle_setups SET status='COMPLETE' WHERE id=?", (setup_id,)
        )

    assert engine.cleanup_completed_battles() == len(enemy_ids)
    assert engine.cleanup_completed_battles() == 0
    healed = engine.get_character(int(jue["id"]))
    assert int(healed["current_hp"]) == int(healed["max_hp"])
    assert not database.fetch_all(
        "SELECT id FROM characters WHERE id IN ("
        + ",".join("?" for _ in enemy_ids)
        + ")",
        tuple(enemy_ids),
    )


def test_encounter_formation_applies_core_persona_and_spawns_stage_enemies(
    database: object,
) -> None:
    engine = _engine(database)
    setup_id = engine.prepare_encounter("encounter.training_ground", created_by=7)
    jue = engine.get_core_character("珏")
    persona = next(
        item for item in engine.list_personas(int(jue["id"]))
        if item["persona_key"] == "persona.jue.stray_hound_boss"
    )
    engine.add_core_to_setup(int(jue["id"]), int(persona["id"]))

    helper = engine.spawn_character("unit.training_assistant", Faction.FRIENDLY)
    engine.add_noncore_friendlies_to_setup([helper])
    engine.add_enemy_to_formation(
        "enemy.training_shell", stage=2, amount=1, name="临时增援"
    )

    setup = engine.battle_setup_status()
    assert setup["id"] == setup_id
    assert [int(item["stage_number"]) for item in setup["stages"]] == [1, 2]
    assert {item["id"] for item in setup["friendlies"]} == {int(jue["id"]), helper}
    assert sum(
        int(item["amount"]) for item in setup["enemies"]
        if int(item["stage_number"]) == 2
    ) == 4

    battle_id, _ = engine.launch_prepared_battle()
    lock_enemy_planning(engine)
    assert engine.list_battle_setups()[0]["id"] == setup_id
    assert engine.list_battle_setups()[0]["status"] == "ACTIVE"
    assert engine.get_character(int(jue["id"]))["max_hp"] == 150
    status = engine.battle_status()
    assert status["id"] == battle_id
    assert status["total_stages"] == 2
    assert sum(
        1 for item in status["participants"]
        if item["faction"] == Faction.ENEMY.value and int(item["active_in_stage"])
    ) == 2


def test_enemy_can_be_added_after_the_encounter_has_started(database: object) -> None:
    engine = _engine(database)
    engine.prepare_encounter("encounter.training_ground")
    jue = engine.get_core_character("珏")
    initial = next(
        item for item in engine.list_personas(int(jue["id"])) if item["is_default"]
    )
    engine.add_core_to_setup(int(jue["id"]), int(initial["id"]))
    engine.launch_prepared_battle()
    lock_enemy_planning(engine)

    message = engine.add_enemy_to_formation(
        "enemy.training_shell", amount=1, name="途中介入者"
    )
    assert "追加 1 名敌人" in message
    status = engine.battle_status()
    assert sum(
        1 for item in status["participants"]
        if item["faction"] == Faction.ENEMY.value and int(item["active_in_stage"])
    ) == 3
    manual = next(
        item for item in engine.battle_setup_status()["enemies"]
        if item["source"] == "MANUAL" and item["display_name"] == "途中介入者"
    )
    origins = database.fetch_all(
        "SELECT character_id FROM battle_spawn_origins WHERE setup_enemy_id=?",
        (manual["id"],),
    )
    assert len(origins) == 1


def test_multiple_named_setups_keep_separate_admin_selections(database: object) -> None:
    engine = _engine(database)
    first = engine.prepare_encounter(
        "encounter.training_ground", name="人格测试战", created_by=11
    )
    second = engine.prepare_encounter(
        "encounter.training_ground", name="技能测试战", created_by=22
    )

    assert first != second
    assert engine.selected_battle_setup_id(11) == first
    assert engine.selected_battle_setup_id(22) == second
    assert {item["name"] for item in engine.list_battle_setups()} == {
        "人格测试战", "技能测试战"
    }

    jue = engine.get_core_character("珏")
    initial = next(
        item for item in engine.list_personas(int(jue["id"])) if item["is_default"]
    )
    engine.add_core_to_setup(int(jue["id"]), int(initial["id"]), setup_id=first)

    assert len(engine.battle_setup_status(first)["friendlies"]) == 1
    assert engine.battle_setup_status(second)["friendlies"] == []


def test_one_admin_can_select_different_battles_in_different_chats(
    database: object,
) -> None:
    engine = _engine(database)
    first = engine.prepare_encounter(
        "encounter.training_ground", name="群组战斗", created_by=11,
        selection_chat_id=-1001,
    )
    second = engine.prepare_encounter(
        "encounter.training_ground", name="私聊战斗", created_by=11,
        selection_chat_id=11,
    )

    assert engine.selected_battle_setup_id(11, chat_id=-1001) == first
    assert engine.selected_battle_setup_id(11, chat_id=11) == second


def test_legacy_selection_is_used_until_a_chat_selects_its_own_battle(
    database: object,
) -> None:
    engine = _engine(database)
    legacy = engine.prepare_encounter(
        "encounter.training_ground", name="迁移前选择", created_by=11
    )

    assert engine.selected_battle_setup_id(11, chat_id=-1001) == legacy

    local = engine.prepare_encounter("encounter.training_ground", name="群组选择")
    engine.select_battle_setup(11, local, chat_id=-1001)
    assert engine.selected_battle_setup_id(11, chat_id=-1001) == local


def test_ready_revision_guard_rejects_a_changed_formation(database: object) -> None:
    engine = _engine(database)
    setup_id = engine.prepare_encounter("encounter.training_ground")
    revision = int(engine.battle_setup_status(setup_id)["revision"])
    jue = engine.get_core_character("珏")
    initial = next(
        item for item in engine.list_personas(int(jue["id"])) if item["is_default"]
    )
    engine.add_core_to_setup(int(jue["id"]), int(initial["id"]), setup_id=setup_id)

    with pytest.raises(BattleRuleError, match="发生变化"):
        engine.launch_prepared_battle(setup_id, expected_revision=revision)
        lock_enemy_planning(engine)

    assert engine.battle_setup_status(setup_id)["status"] == "STANDBY"


def test_manual_enemy_can_be_removed_before_launch(database: object) -> None:
    engine = _engine(database)
    setup_id = engine.prepare_encounter("encounter.training_ground")
    engine.add_enemy_to_formation(
        "enemy.training_shell", stage=1, name="误编假人", setup_id=setup_id
    )
    manual = next(
        item for item in engine.battle_setup_status(setup_id)["enemies"]
        if item["source"] == "MANUAL"
    )

    message = engine.remove_manual_enemy_from_setup(
        int(manual["id"]), setup_id=setup_id
    )

    assert "误编假人" in message
    assert all(
        int(item["id"]) != int(manual["id"])
        for item in engine.battle_setup_status(setup_id)["enemies"]
    )


def test_dead_noncore_ally_cannot_enter_a_new_formation(database: object) -> None:
    engine = _engine(database)
    setup_id = engine.prepare_encounter("encounter.training_ground")
    helper = engine.spawn_character("unit.training_assistant", Faction.FRIENDLY)
    with database.transaction() as connection:
        connection.execute("UPDATE characters SET current_hp=0 WHERE id=?", (helper,))

    with pytest.raises(BattleRuleError, match="无法行动"):
        engine.add_noncore_friendlies_to_setup([helper], setup_id=setup_id)


def test_noncore_ally_cannot_replace_required_core_trigger(database: object) -> None:
    engine = _engine(database)
    setup_id = engine.prepare_encounter("encounter.training_ground")
    helper = engine.spawn_character("unit.training_assistant", Faction.FRIENDLY)
    engine.add_noncore_friendlies_to_setup([helper], setup_id=setup_id)

    with pytest.raises(BattleRuleError, match="核心角色"):
        engine.launch_prepared_battle(setup_id)
        lock_enemy_planning(engine)


def test_target_hp_condition_can_end_stage_while_other_enemies_live(database: object) -> None:
    engine = _engine(database)
    setup_id = engine.prepare_encounter("encounter.training_ground")
    jue = engine.get_core_character("珏")
    initial = next(
        item for item in engine.list_personas(int(jue["id"])) if item["is_default"]
    )
    engine.add_core_to_setup(int(jue["id"]), int(initial["id"]), setup_id=setup_id)
    battle_id, _ = engine.launch_prepared_battle(setup_id)
    lock_enemy_planning(engine)
    with database.transaction() as connection:
        connection.execute(
            """
            UPDATE battle_setup_stages SET clear_condition_json=?
            WHERE setup_id=? AND stage_number=1
            """,
            (
                json.dumps(
                    {"type": "TARGET_HP_BELOW", "target": "frontline", "ratio": 0.5}
                ),
                setup_id,
            ),
        )
        target = connection.execute(
            """
            SELECT c.id,c.max_hp FROM battle_spawn_origins o
            JOIN characters c ON c.id=o.character_id
            WHERE o.battle_id=? AND o.enemy_key='frontline' LIMIT 1
            """, (battle_id,)
        ).fetchone()
        connection.execute(
            "UPDATE characters SET current_hp=? WHERE id=?",
            (int(target["max_hp"]) // 2, target["id"]),
        )

    engine.end_friendly_phase()
    engine.end_turn()
    lock_enemy_planning(engine)
    assert engine.battle_status()["phase"] == BattlePhase.STAGE_END.value


def test_replace_core_formation_is_atomic_and_preserves_noncore_allies(
    database: object,
) -> None:
    engine = _engine(database)
    setup_id = engine.prepare_encounter("encounter.training_ground")
    helper = engine.spawn_character("unit.training_assistant", Faction.FRIENDLY)
    engine.add_noncore_friendlies_to_setup([helper], setup_id=setup_id)
    jue = engine.get_core_character("珏")
    lu = engine.get_core_character("露")
    jue_persona = next(item for item in engine.list_personas(int(jue["id"])) if item["is_default"])
    lu_persona = next(item for item in engine.list_personas(int(lu["id"])) if item["is_default"])
    engine.add_core_to_setup(int(jue["id"]), int(jue_persona["id"]), setup_id=setup_id)

    engine.replace_core_formation(
        setup_id, [(int(lu["id"]), int(lu_persona["id"]))]
    )
    friendlies = engine.battle_setup_status(setup_id)["friendlies"]
    assert {int(item["id"]) for item in friendlies} == {helper, int(lu["id"])}

    with pytest.raises(BattleRuleError, match="重复"):
        engine.replace_core_formation(
            setup_id,
            [
                (int(jue["id"]), int(jue_persona["id"])),
                (int(jue["id"]), int(jue_persona["id"])),
            ],
        )
    assert {int(item["id"]) for item in engine.battle_setup_status(setup_id)["friendlies"]} == {
        helper,
        int(lu["id"]),
    }

    engine.replace_core_formation(setup_id, [])
    assert [
        int(item["id"]) for item in engine.battle_setup_status(setup_id)["friendlies"]
    ] == [helper]

    engine.remove_noncore_friendly_from_setup(helper, setup_id=setup_id)
    assert engine.battle_setup_status(setup_id)["friendlies"] == []


def test_launch_rolls_back_persona_spawns_and_battle_as_one_transaction(
    database: object,
) -> None:
    engine = _engine(database)
    setup_id = engine.prepare_encounter("encounter.training_ground")
    jue = engine.get_core_character("珏")
    special = next(
        item for item in engine.list_personas(int(jue["id"]))
        if item["persona_key"] == "persona.jue.stray_hound_boss"
    )
    engine.add_core_to_setup(int(jue["id"]), int(special["id"]), setup_id=setup_id)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE battle_setups SET abnormalities_json=? WHERE id=?",
            (json.dumps(["missing.abnormality"]), setup_id),
        )
    before_count = int(database.fetch_one("SELECT COUNT(*) amount FROM characters")["amount"])
    before_character = engine.get_character(int(jue["id"]))

    with pytest.raises(BattleRuleError, match="异想体未登记"):
        engine.launch_prepared_battle(setup_id)
        lock_enemy_planning(engine)

    assert int(database.fetch_one("SELECT COUNT(*) amount FROM characters")["amount"]) == before_count
    assert database.fetch_one("SELECT 1 FROM battles WHERE status='ACTIVE'") is None
    assert database.fetch_one("SELECT status FROM battle_setups WHERE id=?", (setup_id,))["status"] == "STANDBY"
    after_character = engine.get_character(int(jue["id"]))
    assert after_character["active_persona_id"] == before_character["active_persona_id"]
    assert after_character["max_hp"] == before_character["max_hp"]


def test_last_stage_next_stage_misconfiguration_finishes_as_victory(database: object) -> None:
    engine = _engine(database)
    setup_id = engine.prepare_encounter("encounter.training_ground")
    jue = engine.get_core_character("珏")
    initial = next(item for item in engine.list_personas(int(jue["id"])) if item["is_default"])
    engine.add_core_to_setup(int(jue["id"]), int(initial["id"]), setup_id=setup_id)
    battle_id, _ = engine.launch_prepared_battle(setup_id)
    lock_enemy_planning(engine)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE battle_setup_stages SET clear_outcome='NEXT_STAGE' WHERE setup_id=? AND stage_number=2",
            (setup_id,),
        )
        connection.execute(
            "UPDATE battles SET current_stage=2 WHERE id=?", (battle_id,)
        )
        connection.execute(
            """
            UPDATE characters SET current_hp=0 WHERE id IN (
                SELECT character_id FROM battle_participants
                WHERE battle_id=? AND faction='ENEMY' AND active_in_stage=1
            )
            """,
            (battle_id,),
        )

    engine.end_friendly_phase()
    engine.end_turn()
    lock_enemy_planning(engine)
    battle = database.fetch_one("SELECT status,result FROM battles WHERE id=?", (battle_id,))
    assert battle["status"] == "COMPLETE"
    assert battle["result"] == "VICTORY"


def test_battle_scoped_registered_behavior_cannot_follow_a_retired_owner(
    database: object,
) -> None:
    engine = _engine(database)
    setup_id = engine.prepare_encounter("encounter.training_ground")
    jue = engine.get_core_character("珏")
    initial = next(item for item in engine.list_personas(int(jue["id"])) if item["is_default"])
    engine.add_core_to_setup(int(jue["id"]), int(initial["id"]), setup_id=setup_id)
    battle_id, _ = engine.launch_prepared_battle(setup_id)
    lock_enemy_planning(engine)
    status = engine.battle_status()
    old_enemy = next(
        item for item in status["participants"]
        if item["faction"] == Faction.ENEMY.value and int(item["active_in_stage"])
    )
    hp_before = int(engine.get_character(int(jue["id"]))["current_hp"])
    old_enemy_hp = int(old_enemy["current_hp"])
    with database.transaction() as connection:
        behavior = connection.execute(
            "SELECT id FROM skill_behaviors WHERE behavior_key='behavior.common.strike.damage'"
        ).fetchone()
        connection.execute(
            "UPDATE skill_behaviors SET timing='TURN_START' WHERE id=?",
            (behavior["id"],),
        )
        registration = connection.execute(
            """
            INSERT INTO battle_registered_behaviors(
                battle_id,behavior_id,owner_character_id,source_type,source_key,
                active_from,remaining_turns,remaining_triggers,lifecycle_scope,status,
                target_snapshot_json
            ) VALUES(?,?,?,?,?,'NEXT_TURN_START',5,5,'BATTLE','ACTIVE',?)
            """,
            (
                battle_id,
                behavior["id"],
                old_enemy["id"],
                "SKILL",
                "test.retired_owner",
                json.dumps([int(jue["id"])]),
            ),
        )
        registration_id = int(registration.lastrowid)
        retired_target_registration = connection.execute(
            """
            INSERT INTO battle_registered_behaviors(
                battle_id,behavior_id,owner_character_id,source_type,source_key,
                active_from,remaining_turns,remaining_triggers,lifecycle_scope,status,
                target_snapshot_json
            ) VALUES(?,?,?,?,?,'NEXT_TURN_START',5,5,'BATTLE','ACTIVE',?)
            """,
            (
                battle_id,
                behavior["id"],
                jue["id"],
                "SKILL",
                "test.retired_target",
                json.dumps([int(old_enemy["id"])]),
            ),
        )
        retired_target_registration_id = int(retired_target_registration.lastrowid)
        engine._finish_stage(connection, battle_id)

    engine.start_prepared_stage()
    lock_enemy_planning(engine)
    assert int(engine.get_character(int(jue["id"]))["current_hp"]) == hp_before
    assert int(engine.get_character(int(old_enemy["id"]))["current_hp"]) == old_enemy_hp
    assert database.fetch_one(
        "SELECT status FROM battle_registered_behaviors WHERE id=?", (registration_id,)
    )["status"] == "EXHAUSTED"
    assert database.fetch_one(
        "SELECT status FROM battle_registered_behaviors WHERE id=?",
        (retired_target_registration_id,),
    )["status"] == "EXHAUSTED"


def _register_strike_at_next_turn_start(
    database: object,
    *,
    battle_id: int,
    owner_id: int,
    target_id: int,
) -> None:
    with database.transaction() as connection:
        behavior = connection.execute(
            """
            SELECT id FROM skill_behaviors
            WHERE behavior_key='behavior.common.strike.damage'
            """
        ).fetchone()
        connection.execute(
            "UPDATE skill_behaviors SET timing='TURN_START' WHERE id=?",
            (behavior["id"],),
        )
        connection.execute(
            """
            INSERT INTO battle_registered_behaviors(
                battle_id,behavior_id,owner_character_id,source_type,source_key,
                active_from,remaining_turns,remaining_triggers,lifecycle_scope,status,
                target_snapshot_json
            ) VALUES(?,?,?,?,?,'NEXT_TURN_START',1,1,'TURN','PENDING',?)
            """,
            (
                battle_id,
                behavior["id"],
                owner_id,
                "SKILL",
                "test.turn_start_resolution",
                json.dumps([target_id]),
            ),
        )


def test_turn_start_behavior_resolves_friendly_wipe_before_action_phase(
    database: object,
) -> None:
    engine = _engine(database)
    setup_id = engine.prepare_encounter("encounter.training_ground")
    jue = engine.get_core_character("珏")
    initial = next(
        item for item in engine.list_personas(int(jue["id"])) if item["is_default"]
    )
    engine.add_core_to_setup(int(jue["id"]), int(initial["id"]), setup_id=setup_id)
    battle_id, _ = engine.launch_prepared_battle(setup_id)
    lock_enemy_planning(engine)
    enemy = next(
        item
        for item in engine.battle_status()["participants"]
        if item["faction"] == Faction.ENEMY.value and int(item["active_in_stage"])
    )
    with database.transaction() as connection:
        connection.execute(
            "UPDATE characters SET current_hp=1 WHERE id=?", (jue["id"],)
        )
    _register_strike_at_next_turn_start(
        database,
        battle_id=battle_id,
        owner_id=int(enemy["id"]),
        target_id=int(jue["id"]),
    )

    engine.end_friendly_phase()
    engine.end_turn()
    lock_enemy_planning(engine)

    battle = database.fetch_one(
        "SELECT status,result,phase FROM battles WHERE id=?", (battle_id,)
    )
    assert battle["status"] == "COMPLETE"
    assert battle["result"] == "DEFEAT"
    assert battle["phase"] == BattlePhase.BATTLE_END.value


def test_turn_start_behavior_resolves_stage_condition_before_action_phase(
    database: object,
) -> None:
    engine = _engine(database)
    setup_id = engine.prepare_encounter("encounter.training_ground")
    with database.transaction() as connection:
        connection.execute(
            """
            UPDATE battle_setup_enemies SET amount=1
            WHERE setup_id=? AND stage_number=1 AND enemy_key='frontline'
            """,
            (setup_id,),
        )
        connection.execute(
            """
            UPDATE battle_setup_stages SET clear_condition_json=?
            WHERE setup_id=? AND stage_number=1
            """,
            (
                json.dumps({"type": "TARGET_DEFEATED", "target": "frontline"}),
                setup_id,
            ),
        )
    engine.add_enemy_to_formation(
        "enemy.training_shell",
        stage=1,
        amount=1,
        name="旁观假人",
        setup_id=setup_id,
    )
    jue = engine.get_core_character("珏")
    initial = next(
        item for item in engine.list_personas(int(jue["id"])) if item["is_default"]
    )
    engine.add_core_to_setup(int(jue["id"]), int(initial["id"]), setup_id=setup_id)
    battle_id, _ = engine.launch_prepared_battle(setup_id)
    lock_enemy_planning(engine)
    target = database.fetch_one(
        """
        SELECT o.character_id FROM battle_spawn_origins o
        WHERE o.battle_id=? AND o.stage_number=1 AND o.enemy_key='frontline'
        """,
        (battle_id,),
    )
    assert target is not None
    with database.transaction() as connection:
        connection.execute(
            "UPDATE characters SET current_hp=1 WHERE id=?",
            (target["character_id"],),
        )
    _register_strike_at_next_turn_start(
        database,
        battle_id=battle_id,
        owner_id=int(jue["id"]),
        target_id=int(target["character_id"]),
    )

    engine.end_friendly_phase()
    engine.end_turn()
    lock_enemy_planning(engine)

    status = engine.battle_status()
    assert status["phase"] == BattlePhase.STAGE_END.value
    assert any(
        item["faction"] == Faction.ENEMY.value
        and int(item["current_hp"]) > 0
        for item in status["participants"]
    )
