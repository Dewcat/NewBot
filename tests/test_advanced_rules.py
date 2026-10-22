from __future__ import annotations

from conftest import lock_enemy_planning

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from dewbot.content import ContentLoader
from dewbot.db import Database
from dewbot.effects import EffectExecutionContext, SpecialEffectRegistry
from dewbot.engine import BattleEngine
from dewbot.models import BattlePhase, BattleRuleError, ContentValidationError, Faction

from conftest import BASE_PACK


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PACK = ROOT / "content" / "example_extension.json"
CORE_PERSONAS = ROOT / "content" / "core_personas.json"


def _immunity_pack() -> dict[str, object]:
    return {
        "pack": {"key": "test.hooks", "name": "Hooks", "version": "1.0.0"},
        "effects": [
            {
                "key": "status.test_undying",
                "name": "Undying",
                "category": "SPECIAL",
                "handler": "test.undying",
                "default_params": {
                    "persist": True,
                    "events": ["ON_AFTER_DAMAGE"],
                    "event_subject": "OWNER_TARGET",
                    "triggers": 0,
                },
            }
        ],
        "skills": [
            {
                "key": "skill.test.undying",
                "name": "Undying Mark",
                "type": "NORMAL",
                "target_scope": "SELF",
                "target_method": "SELF",
                "behaviors": [
                    {
                        "key": "behavior.test.undying.apply",
                        "timing": "ON",
                        "effect_type": "APPLY_EFFECT",
                        "effect_key": "status.test_undying",
                    }
                ],
            },
            {
                "key": "skill.test.execution",
                "name": "Execution",
                "type": "NORMAL",
                "target_scope": "ENEMY",
                "target_method": "SELECT_TARGET",
                "behaviors": [
                    {
                        "key": "behavior.test.execution.damage",
                        "timing": "ON",
                        "effect_type": "DAMAGE",
                        "value": "999",
                    }
                ],
            },
        ],
        "characters": [
            {
                "key": "unit.test.undying",
                "name": "Undying Subject",
                "max_hp": 30,
                "max_actions": 1,
                "max_stagger": 20,
                "tags": [],
                "skills": ["skill.test.undying"],
            },
            {
                "key": "enemy.test.executioner",
                "name": "Executioner",
                "max_hp": 30,
                "max_actions": 1,
                "max_stagger": 20,
                "tags": [],
                "skills": ["skill.test.execution"],
            },
        ],
    }


def _recursive_ego_pack() -> dict[str, object]:
    ego_b = {
        "key": "skill.test.ego_b",
        "name": "EGO B",
        "type": "EGO",
        "emotion": 1,
        "target_scope": "ENEMY",
        "target_method": "SELECT_TARGET",
        "behaviors": [
            {
                "key": "behavior.test.ego_b.damage",
                "timing": "ON",
                "effect_type": "DAMAGE",
                "value": "1",
            }
        ],
    }
    return {
        "pack": {"key": "test.ego_recursive", "name": "EGO", "version": "1.0.0"},
        "skills": [
            {
                "key": "skill.test.ego_a",
                "name": "EGO A",
                "type": "EGO",
                "emotion": 1,
                "target_scope": "ENEMY",
                "target_method": "SELECT_TARGET",
                "behaviors": [
                    {
                        "key": "behavior.test.ego_a.invoke",
                        "timing": "ON",
                        "effect_type": "SPECIAL",
                        "value": "invoke_skill",
                        "params": {"skill_key": "skill.test.ego_b"},
                    }
                ],
            },
            ego_b,
            {
                "key": "skill.test.idle",
                "name": "Idle",
                "type": "NORMAL",
                "target_scope": "ENEMY",
                "target_method": "SELECT_TARGET",
                "behaviors": [
                    {
                        "key": "behavior.test.idle.damage",
                        "timing": "ON",
                        "effect_type": "DAMAGE",
                        "value": "0",
                    }
                ],
            },
        ],
        "characters": [
            {
                "key": "unit.test.ego_actor",
                "name": "EGO Actor",
                "max_hp": 20,
                "max_stagger": 20,
                "tags": [],
                "skills": ["skill.test.ego_a", "skill.test.ego_b"],
            },
            {
                "key": "enemy.test.ego_target",
                "name": "EGO Target",
                "max_hp": 20,
                "max_stagger": 20,
                "tags": [],
                "skills": ["skill.test.idle"],
            },
        ],
    }


def test_extension_pack_can_add_persona_to_an_existing_core(database: Database) -> None:
    loader = ContentLoader(database)
    loader.load_path(BASE_PACK)
    loader.load_path(CORE_PERSONAS)
    loader.load_path(EXAMPLE_PACK)
    engine = BattleEngine(database)

    character_id = int(engine.get_core_character("珏")["id"])
    personas = engine.list_personas(character_id)
    assert {item["persona_key"] for item in personas} >= {
        "persona.jue.initial",
        "example.persona.jue.echo",
    }

    engine.switch_persona(character_id, "example.persona.jue.echo")
    active = next(item for item in engine.list_personas(character_id) if item["is_active"])
    assert active["pack_key"] == "dewbot.example"

    updated = json.loads(EXAMPLE_PACK.read_text(encoding="utf-8"))
    updated["pack"]["version"] = "1.1.0"
    updated["personas"] = []
    loader.load(updated)
    active_after_removal = next(
        item for item in engine.list_personas(character_id) if item["is_active"]
    )
    assert active_after_removal["persona_key"] == "persona.jue.initial"


def test_pack_cannot_remove_a_persona_selected_by_a_standby_battle(
    database: Database,
) -> None:
    loader = ContentLoader(database)
    loader.load_path(BASE_PACK)
    loader.load_path(CORE_PERSONAS)
    loader.load_path(EXAMPLE_PACK)
    engine = BattleEngine(database)
    setup_id = engine.prepare_encounter(
        "encounter.training_ground", name="人格依赖测试"
    )
    jue = engine.get_core_character("珏")
    persona = next(
        item for item in engine.list_personas(int(jue["id"]))
        if item["persona_key"] == "example.persona.jue.echo"
    )
    engine.add_core_to_setup(int(jue["id"]), int(persona["id"]), setup_id=setup_id)
    updated = json.loads(EXAMPLE_PACK.read_text(encoding="utf-8"))
    updated["pack"]["version"] = "1.1.0"
    updated["personas"] = []

    with pytest.raises(ContentValidationError, match="待触发/进行中的战斗"):
        loader.load(updated)


def test_pack_update_cannot_remove_local_or_exported_dependencies(database: Database) -> None:
    loader = ContentLoader(database)
    loader.load_path(BASE_PACK)
    loader.load_path(CORE_PERSONAS)
    loader.load_path(EXAMPLE_PACK)
    base = json.loads(BASE_PACK.read_text(encoding="utf-8"))

    # Same-pack reference: delayed_weakness still needs this effect.
    missing_effect = json.loads(json.dumps(base))
    missing_effect["pack"]["version"] = "2.1.0"
    missing_effect["effects"] = [
        item for item in missing_effect["effects"] if item["key"] != "status.weakness"
    ]
    with pytest.raises(ContentValidationError, match="status.weakness"):
        loader.load(missing_effect)

    # Cross-pack reverse dependency: the example persona uses common.guard.
    missing_export = json.loads(json.dumps(base))
    missing_export["pack"]["version"] = "2.1.0"
    missing_export["skills"] = [
        item for item in missing_export["skills"] if item["key"] != "skill.common.guard"
    ]
    with pytest.raises(ContentValidationError, match="skill.common.guard"):
        loader.load(missing_export)


def test_pack_update_cannot_remove_template_used_by_standby_setup(
    database: Database,
) -> None:
    loader = ContentLoader(database)
    loader.load_path(BASE_PACK)
    BattleEngine(database).prepare_encounter("encounter.training_ground", name="保留战斗")
    updated = json.loads(BASE_PACK.read_text(encoding="utf-8"))
    updated["pack"]["version"] = "2.1.0"
    updated["encounters"] = []
    updated["characters"] = [
        item
        for item in updated["characters"]
        if item["key"] != "enemy.training_shell"
    ]

    with pytest.raises(ContentValidationError, match="待触发/进行中的战斗"):
        loader.load(updated)


def test_pack_update_cannot_remove_abnormality_used_by_external_encounter(
    database: Database,
) -> None:
    loader = ContentLoader(database)
    loader.load_path(BASE_PACK)
    loader.load_path(CORE_PERSONAS)
    loader.load_path(EXAMPLE_PACK)
    loader.load(
        {
            "pack": {
                "key": "test.encounter_consumer",
                "name": "Encounter Consumer",
                "version": "1.0.0",
                "requires": [
                    {"key": "dewbot.base", "min_version": "2.0.0"},
                    {"key": "dewbot.example", "min_version": "1.0.0"},
                ],
            },
            "encounters": [
                {
                    "key": "test.encounter.abnormality",
                    "name": "异想体引用测试",
                    "abnormalities": ["example.abnormality.second_hand"],
                    "stages": [
                        {
                            "name": "唯一阶段",
                            "on_clear": "VICTORY",
                            "enemies": [
                                {
                                    "id": "target",
                                    "template": "enemy.training_shell",
                                    "count": 1,
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )
    updated = json.loads(EXAMPLE_PACK.read_text(encoding="utf-8"))
    updated["pack"]["version"] = "1.1.0"
    updated["abnormalities"] = []

    with pytest.raises(ContentValidationError, match="test.encounter.abnormality"):
        loader.load(updated)


def test_standby_setup_keeps_its_abnormality_snapshot_dependency(
    database: Database,
) -> None:
    loader = ContentLoader(database)
    loader.load_path(BASE_PACK)
    loader.load_path(CORE_PERSONAS)
    loader.load_path(EXAMPLE_PACK)
    consumer = {
        "pack": {
            "key": "test.snapshot_consumer",
            "name": "Snapshot Consumer",
            "version": "1.0.0",
            "requires": [
                {"key": "dewbot.base", "min_version": "2.0.0"},
                {"key": "dewbot.example", "min_version": "1.0.0"},
            ],
        },
        "encounters": [{
            "key": "test.encounter.snapshot",
            "name": "异想体快照测试",
            "abnormalities": ["example.abnormality.second_hand"],
            "stages": [{
                "name": "唯一阶段",
                "on_clear": "VICTORY",
                "enemies": [{
                    "id": "target",
                    "template": "enemy.training_shell",
                    "count": 1,
                }],
            }],
        }],
    }
    loader.load(consumer)
    BattleEngine(database).prepare_encounter(
        "test.encounter.snapshot", name="保留异想体池"
    )

    consumer["pack"]["version"] = "1.1.0"
    consumer["encounters"][0]["abnormalities"] = []
    loader.load(consumer)
    updated = json.loads(EXAMPLE_PACK.read_text(encoding="utf-8"))
    updated["pack"]["version"] = "1.1.0"
    updated["abnormalities"] = []

    with pytest.raises(ContentValidationError, match="待触发/进行中的战斗"):
        loader.load(updated)


def test_lethal_after_damage_hook_can_prevent_final_death(database: Database) -> None:
    loader = ContentLoader(database)
    loader.load(_immunity_pack())
    registry = SpecialEffectRegistry()

    def undying(context: EffectExecutionContext) -> None:
        if context.event != "ON_AFTER_DAMAGE":
            return
        owner = context.engine._character(context.connection, context.hook_owner_id)
        if int(owner["current_hp"]) <= 0:
            context.connection.execute(
                "UPDATE characters SET current_hp=1 WHERE id=?", (owner["id"],)
            )
            context.params["triggers"] = int(context.params.get("triggers", 0)) + 1
            context.messages.append("└ 死亡判定被特殊记录改写。")

    registry.register("test.undying", undying)
    engine = BattleEngine(database, registry=registry)
    hero = engine.spawn_character("unit.test.undying", Faction.FRIENDLY)
    enemy = engine.spawn_character("enemy.test.executioner", Faction.ENEMY)
    engine.start_battle([hero], [enemy])
    execute = engine.list_skills(enemy)[0]
    engine.use_skill(enemy, execute["id"], [hero])
    lock_enemy_planning(engine)
    apply_skill = engine.list_skills(hero)[0]
    engine.use_skill(hero, apply_skill["id"])
    # 我方行动耗尽会自动移交敌方阶段；未耗尽时仍需手动移交。
    if engine.battle_status()["phase"] == "FRIENDLY_ACTION":
        engine.end_friendly_phase()
    result = "\n".join(engine.end_turn())

    assert engine.get_character(hero)["current_hp"] == 1
    assert "死亡判定被特殊记录改写" in result
    assert "倒下了，退出战斗" not in result
    state = database.fetch_one(
        "SELECT params_json FROM active_effects WHERE character_id=? AND effect_key=?",
        (hero, "status.test_undying"),
    )
    assert state is not None
    assert json.loads(state["params_json"])["triggers"] == 1


def test_migrations_are_safe_under_concurrent_initialization(tmp_path: Path) -> None:
    path = tmp_path / "concurrent.sqlite3"

    def initialize(_: int) -> int:
        database = Database(path)
        database.initialize()
        row = database.fetch_one("SELECT COUNT(*) AS amount FROM schema_migrations")
        assert row is not None
        return int(row["amount"])

    from dewbot.schema import MIGRATIONS

    with ThreadPoolExecutor(max_workers=8) as executor:
        versions = list(executor.map(initialize, range(8)))
    assert versions == [len(MIGRATIONS)] * 8


def test_memory_database_is_shared_across_unit_of_work_connections() -> None:
    database = Database(":memory:")
    database.initialize()
    assert database.fetch_one("SELECT version FROM schema_migrations WHERE version=12")
    database.close()


def test_select_target_rejects_more_than_one_selection(world: object) -> None:
    battle_id, _ = world.engine.start_battle([world.hero_id], [world.enemy_id])
    lock_enemy_planning(world.engine)
    world.battle_id = battle_id
    skill_id = world.skill_ids["skill.test.wait"]
    with pytest.raises(BattleRuleError, match="只能指定一个"):
        world.engine.use_skill(
            world.hero_id, skill_id, [world.enemy_id, world.enemy_id]
        )


def test_changed_content_cannot_reload_during_active_battle(world: object) -> None:
    battle_id, _ = world.engine.start_battle([world.hero_id], [world.enemy_id])
    lock_enemy_planning(world.engine)
    world.battle_id = battle_id
    assert ContentLoader(world.database).load_path(BASE_PACK).pack_key == "dewbot.base"
    changed = json.loads(BASE_PACK.read_text(encoding="utf-8"))
    changed["pack"]["version"] = "2.0.1"
    changed["pack"]["description"] += " changed"

    with pytest.raises(ContentValidationError, match="战斗记录仍在展开"):
        ContentLoader(world.database).load(changed)


def test_multistage_battle_requires_explicit_next_stage_roster(world: object) -> None:
    battle_id, _ = world.engine.start_battle(
        [world.hero_id], [world.enemy_id], total_stages=2
    )
    lock_enemy_planning(world.engine)
    world.battle_id = battle_id
    with world.database.transaction() as connection:
        connection.execute(
            "UPDATE characters SET current_hp=0 WHERE id=?", (world.enemy_id,)
        )
    world.engine.end_friendly_phase()
    world.engine.end_turn()
    lock_enemy_planning(world.engine)
    assert world.engine.battle_status()["phase"] == BattlePhase.STAGE_END.value

    with pytest.raises(BattleRuleError, match="至少需要"):
        world.engine.start_stage([world.hero_id], [])
        lock_enemy_planning(world.engine)
    next_enemy = world.engine.spawn_character("enemy.test_dummy", Faction.ENEMY)
    world.engine.start_stage([world.hero_id], [next_enemy])
    lock_enemy_planning(world.engine)
    status = world.engine.battle_status()
    assert status["current_stage"] == 2
    assert status["phase"] == BattlePhase.FRIENDLY_ACTION.value
    active_ids = {
        int(item["id"])
        for item in status["participants"]
        if int(item["active_in_stage"])
    }
    assert active_ids == {world.hero_id, next_enemy}


def test_ego_is_reserved_before_recursive_skill_invocation(database: Database) -> None:
    ContentLoader(database).load(_recursive_ego_pack())
    engine = BattleEngine(database)
    hero = engine.spawn_character("unit.test.ego_actor", Faction.FRIENDLY)
    enemy = engine.spawn_character("enemy.test.ego_target", Faction.ENEMY)
    battle_id, _ = engine.start_battle([hero], [enemy])
    lock_enemy_planning(engine)
    with database.transaction() as connection:
        connection.execute(
            "UPDATE characters SET emotion_level=1 WHERE id=?", (hero,)
        )
    ego_a = next(
        item for item in engine.list_skills(hero) if item["skill_key"] == "skill.test.ego_a"
    )

    with pytest.raises(BattleRuleError, match="已经展开过 E.G.O"):
        engine.use_skill(hero, ego_a["id"], [enemy])

    assert database.fetch_one(
        "SELECT 1 FROM battle_ego_usage WHERE battle_id=? AND character_id=?",
        (battle_id, hero),
    ) is None
    assert engine.get_character(hero)["current_actions"] == 1


def test_hardblood_uses_independent_accumulating_amount(loaded_database: Database) -> None:
    pack = {
        "pack": {"key": "test.hardblood", "name": "Hardblood", "version": "1.0.0"},
        "skills": [
            {
                "key": "skill.test.hardblood",
                "name": "Gather Hardblood",
                "type": "NORMAL",
                "target_scope": "SELF",
                "target_method": "SELF",
                "behaviors": [
                    {
                        "key": "behavior.test.hardblood.apply",
                        "timing": "ON",
                        "effect_type": "APPLY_EFFECT",
                        "effect_key": "status.hardblood",
                        "params": {"amount": 5},
                    }
                ],
            },
            {
                "key": "skill.test.hardblood_strike",
                "name": "Hardblood Strike",
                "type": "NORMAL",
                "target_scope": "ENEMY",
                "target_method": "SELECT_TARGET",
                "behaviors": [
                    {
                        "key": "behavior.test.hardblood_strike.consume",
                        "timing": "ON",
                        "order": 0,
                        "effect_type": "SPECIAL",
                        "value": "consume_resource",
                        "params": {
                            "resource_key": "status.hardblood",
                            "resource_owner": "ACTOR",
                            "amount": 6,
                            "damage_multiplier_per_unit": 0.1,
                        },
                    },
                    {
                        "key": "behavior.test.hardblood_strike.damage",
                        "timing": "ON",
                        "order": 1,
                        "effect_type": "DAMAGE",
                        "value": "10",
                    },
                ],
            }
        ],
        "characters": [
            {
                "key": "unit.test.hardblood",
                "name": "Hardblood User",
                "max_hp": 50,
                "max_actions": 3,
                "max_stagger": 30,
                "tags": [],
                "skills": ["skill.test.hardblood", "skill.test.hardblood_strike"],
            }
        ],
    }
    ContentLoader(loaded_database).load(pack)
    engine = BattleEngine(loaded_database)
    hero = engine.spawn_character("unit.test.hardblood", Faction.FRIENDLY)
    enemy = engine.spawn_character("enemy.test_dummy", Faction.ENEMY)
    battle_id, _ = engine.start_battle([hero], [enemy])
    lock_enemy_planning(engine)
    skills = {item["skill_key"]: item for item in engine.list_skills(hero)}
    engine.use_skill(hero, skills["skill.test.hardblood"]["id"])
    result = engine.use_skill(hero, skills["skill.test.hardblood"]["id"])

    effect = loaded_database.fetch_one(
        """
        SELECT params_json FROM active_effects
        WHERE battle_id=? AND character_id=? AND effect_key='status.hardblood'
        """,
        (battle_id, hero),
    )
    assert effect is not None
    assert json.loads(effect["params_json"])["amount"] == 10
    assert "硬血」现为 10 点" in result.text

    before = engine.get_character(enemy)["current_hp"]
    strike = engine.use_skill(
        hero, skills["skill.test.hardblood_strike"]["id"], [enemy]
    )
    after = engine.get_character(enemy)["current_hp"]
    assert before - after == 16
    effect = loaded_database.fetch_one(
        "SELECT params_json FROM active_effects WHERE battle_id=? AND character_id=? "
        "AND effect_key='status.hardblood'",
        (battle_id, hero),
    )
    assert effect is not None
    assert json.loads(effect["params_json"])["amount"] == 4
    assert "消耗「硬血」 6，剩余 4" in strike.text


def test_heal_and_apply_effect_skip_dead_targets(loaded_database: Database) -> None:
    pack = {
        "pack": {"key": "test.deadcare", "name": "Dead Care", "version": "1.0.0"},
        "skills": [
            {
                "key": "skill.test.smite_mend",
                "name": "Smite Mend",
                "type": "NORMAL",
                "target_scope": "ENEMY",
                "target_method": "SELECT_TARGET",
                "behaviors": [
                    {
                        "key": "behavior.test.smite_mend.damage",
                        "timing": "ON",
                        "order": 0,
                        "effect_type": "DAMAGE",
                        "value": "999",
                    },
                    {
                        "key": "behavior.test.smite_mend.heal",
                        "timing": "ON",
                        "order": 1,
                        "effect_type": "HEAL",
                        "value": "50",
                    },
                    {
                        "key": "behavior.test.smite_mend.mark",
                        "timing": "ON",
                        "order": 2,
                        "effect_type": "APPLY_EFFECT",
                        "effect_key": "status.rupture",
                        "params": {"intensity": 3, "stacks": 2},
                    },
                ],
            }
        ],
        "character_extensions": [
            {"template_key": "unit.test_hero", "skills": ["skill.test.smite_mend"]}
        ],
    }
    ContentLoader(loaded_database).load(pack)
    engine = BattleEngine(loaded_database)
    hero = engine.spawn_character("unit.test_hero", Faction.FRIENDLY)
    enemy = engine.spawn_character("enemy.test_dummy", Faction.ENEMY)
    battle_id, _ = engine.start_battle([hero], [enemy])
    lock_enemy_planning(engine)
    skills = {item["skill_key"]: item for item in engine.list_skills(hero)}

    result = engine.use_skill(hero, skills["skill.test.smite_mend"]["id"], [enemy])

    assert "治疗无效" in result.text
    assert "该效果不再生效" in result.text
    assert engine.get_character(enemy)["current_hp"] == 0
    assert loaded_database.fetch_one(
        "SELECT 1 FROM active_effects WHERE battle_id=? AND character_id=? "
        "AND effect_key='status.rupture'",
        (battle_id, enemy),
    ) is None


def test_consume_resource_between_damage_behaviors_boosts_next_damage(
    loaded_database: Database,
) -> None:
    pack = {
        "pack": {"key": "test.hardblood2", "name": "Hardblood Two", "version": "1.0.0"},
        "skills": [
            {
                "key": "skill.test.hb_gather",
                "name": "Gather",
                "type": "NORMAL",
                "target_scope": "SELF",
                "target_method": "SELF",
                "behaviors": [
                    {
                        "key": "behavior.test.hb_gather.apply",
                        "timing": "ON",
                        "effect_type": "APPLY_EFFECT",
                        "effect_key": "status.hardblood",
                        "params": {"amount": 10},
                    }
                ],
            },
            {
                "key": "skill.test.hb_burst",
                "name": "Burst",
                "type": "NORMAL",
                "target_scope": "ENEMY",
                "target_method": "SELECT_TARGET",
                "behaviors": [
                    {
                        "key": "behavior.test.hb_burst.first",
                        "timing": "ON",
                        "order": 0,
                        "effect_type": "DAMAGE",
                        "value": "10",
                    },
                    {
                        "key": "behavior.test.hb_burst.consume",
                        "timing": "ON",
                        "order": 1,
                        "effect_type": "SPECIAL",
                        "value": "consume_resource",
                        "params": {
                            "resource_key": "status.hardblood",
                            "resource_owner": "ACTOR",
                            "amount": 10,
                            "damage_multiplier_per_unit": 0.1,
                        },
                    },
                    {
                        "key": "behavior.test.hb_burst.second",
                        "timing": "ON",
                        "order": 2,
                        "effect_type": "DAMAGE",
                        "value": "10",
                    },
                ],
            },
        ],
        "characters": [
            {
                "key": "unit.test.hardblood2",
                "name": "Hardblood Burst User",
                "max_hp": 50,
                "max_actions": 3,
                "max_stagger": 30,
                "tags": [],
                "skills": ["skill.test.hb_gather", "skill.test.hb_burst"],
            }
        ],
    }
    ContentLoader(loaded_database).load(pack)
    engine = BattleEngine(loaded_database)
    hero = engine.spawn_character("unit.test.hardblood2", Faction.FRIENDLY)
    enemy = engine.spawn_character("enemy.test_dummy", Faction.ENEMY)
    engine.start_battle([hero], [enemy])
    lock_enemy_planning(engine)
    skills = {item["skill_key"]: item for item in engine.list_skills(hero)}
    engine.use_skill(hero, skills["skill.test.hb_gather"]["id"])

    before = engine.get_character(enemy)["current_hp"]
    engine.use_skill(hero, skills["skill.test.hb_burst"]["id"], [enemy])
    after = engine.get_character(enemy)["current_hp"]

    # 10 + 10×(1 + 10×0.1) = 30：消耗的硬血必须作用于下一段伤害。
    assert before - after == 30
