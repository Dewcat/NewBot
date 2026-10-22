from __future__ import annotations

from conftest import lock_enemy_planning

import json
import sqlite3

import pytest

from dewbot.content import ContentLoader
from dewbot.engine import BattleEngine
from dewbot.models import BattleRuleError, ContentValidationError, Faction

from conftest import BASE_PACK


CORE_PERSONAS = BASE_PACK.with_name("core_personas.json")


def _load_core(database: object) -> BattleEngine:
    engine = BattleEngine(database)
    loader = ContentLoader(database, engine.registry.keys)
    loader.load_path(BASE_PACK)
    loader.load_path(CORE_PERSONAS)
    engine.validate_content_handlers()
    return engine


def test_core_roster_is_persistent_playable_and_idempotent(database: object) -> None:
    engine = _load_core(database)

    roster = {row["name"]: row for row in engine.list_characters(Faction.FRIENDLY)}
    assert set(roster) == {"珏", "露", "莹", "笙", "曦"}
    assert all(row["template_key"] is None and row["is_core"] for row in roster.values())
    assert database.fetch_one(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='character_roles'"
    ) is None
    assert "role_key" not in {
        row["name"] for row in database.fetch_all("PRAGMA table_info(characters)")
    }

    expected = {
        "珏": "persona.jue.initial",
        "露": "persona.lu.initial",
        "莹": "persona.ying.initial",
        "笙": "persona.sheng.core_initial",
        "曦": "persona.xi.core_initial",
    }
    for name, persona_key in expected.items():
        active = next(
            item
            for item in engine.list_personas(int(roster[name]["id"]))
            if item["is_active"]
        )
        assert active["persona_key"] == persona_key

    before = {name: int(item["id"]) for name, item in roster.items()}
    ContentLoader(database, engine.registry.keys).load_path(CORE_PERSONAS)
    after = {
        row["name"]: int(row["id"])
        for row in engine.list_characters(Faction.FRIENDLY)
    }
    assert after == before

    jue = int(roster["珏"]["id"])
    engine.switch_persona(jue, "persona.jue.stray_hound_boss")
    assert engine.get_character(jue)["max_hp"] == 150
    engine.switch_persona(jue, "persona.jue.initial")
    assert engine.get_character(jue)["max_hp"] == 100


def test_once_per_battle_skill_is_actually_exhausted(database: object) -> None:
    engine = _load_core(database)
    ying = int(engine.get_core_character("莹")["id"])
    engine.switch_persona(ying, "persona.ying.wandering_band_leader")
    enemy = engine.spawn_character("enemy.training_shell", Faction.ENEMY)
    engine.start_battle([ying], [enemy])
    lock_enemy_planning(engine)
    with database.transaction() as connection:
        connection.execute("UPDATE characters SET current_actions=3 WHERE id=?", (ying,))
    pinata = next(
        item for item in engine.list_skills(ying) if item["skill_key"] == "skill.ying.pinata_party"
    )

    engine.use_skill(ying, pinata["id"], [enemy])
    assert next(
        item for item in engine.list_skills(ying) if item["id"] == pinata["id"]
    )["available"] is False
    with pytest.raises(BattleRuleError, match="使用次数已经耗尽"):
        engine.use_skill(ying, pinata["id"], [enemy])


def test_again_again_requires_mark_from_the_same_actor(database: object) -> None:
    engine = _load_core(database)
    jue = int(engine.get_core_character("珏")["id"])
    engine.switch_persona(jue, "persona.jue.stray_hound_boss")
    enemy = engine.spawn_character("enemy.training_shell", Faction.ENEMY)
    engine.start_battle([jue], [enemy])
    lock_enemy_planning(engine)
    with database.transaction() as connection:
        connection.execute("UPDATE characters SET current_actions=3 WHERE id=?", (jue,))
    skills = {item["skill_key"]: item for item in engine.list_skills(jue)}

    with pytest.raises(BattleRuleError, match="先使用「放松肌肉」"):
        engine.use_skill(jue, skills["skill.jue.again_again"]["id"], [enemy])
    assert engine.get_character(jue)["current_actions"] == 3

    engine.use_skill(jue, skills["skill.jue.loosen_muscles"]["id"], [enemy])
    result = engine.use_skill(jue, skills["skill.jue.again_again"]["id"], [enemy])
    assert "再来再来" in result.text


def test_legacy_sanity_effects_now_shift_emotion(database: object) -> None:
    engine = _load_core(database)
    ying = int(engine.get_core_character("莹")["id"])
    engine.switch_persona(ying, "persona.ying.wandering_band_leader")
    enemy = engine.spawn_character("enemy.training_shell", Faction.ENEMY)
    engine.start_battle([ying], [enemy])
    lock_enemy_planning(engine)
    skill = next(
        item
        for item in engine.list_skills(ying)
        if item["skill_key"] == "skill.ying.maraca_dance"
    )

    engine.use_skill(ying, skill["id"], [enemy])
    assert engine.get_character(enemy)["negative_emotion_coins"] == 1


def test_equipped_persona_content_update_rewrites_character_data(database: object) -> None:
    engine = _load_core(database)
    jue = int(engine.get_core_character("珏")["id"])
    engine.switch_persona(jue, "persona.jue.stray_hound_boss")
    updated = json.loads(CORE_PERSONAS.read_text(encoding="utf-8"))
    updated["pack"]["version"] = "2.1.0"
    persona = next(
        item
        for item in updated["personas"]
        if item["key"] == "persona.jue.stray_hound_boss"
    )
    persona["max_hp"] = 166

    ContentLoader(database, engine.registry.keys).load(updated)

    character = engine.get_character(jue)
    assert character["max_hp"] == 166
    assert character["current_hp"] == 166


def test_database_rejects_cross_character_persona_assignment(database: object) -> None:
    engine = _load_core(database)
    jue = engine.get_core_character("珏")
    lu_persona = next(
        item
        for item in engine.list_personas(int(engine.get_core_character("露")["id"]))
        if item["persona_key"] == "persona.lu.ting_tang_boss"
    )

    with pytest.raises(sqlite3.IntegrityError, match="does not belong"):
        with database.transaction() as connection:
            connection.execute(
                "UPDATE characters SET active_persona_id=? WHERE id=?",
                (lu_persona["id"], jue["id"]),
            )


def test_extension_pack_cannot_replace_a_core_characters_default_persona(
    database: object,
) -> None:
    engine = _load_core(database)
    extension = {
        "pack": {
            "key": "test.default_override",
            "name": "Default Override",
            "version": "1.0.0",
            "requires": [{"key": "dewbot.core_personas", "min_version": "2.0.0"}],
        },
        "personas": [{
            "key": "test.persona.jue.override",
            "character": "珏",
            "name": "错误的初始人格",
            "default": True,
            "max_hp": 100,
            "max_actions": 1,
            "max_stagger": 45,
            "skills": ["skill.common.guard"],
        }],
    }

    with pytest.raises(ContentValidationError, match="只有拥有核心角色"):
        ContentLoader(database, engine.registry.keys).load(extension)

    defaults = database.fetch_all(
        """
        SELECT p.persona_key FROM personas p
        JOIN characters c ON c.id=p.character_id
        WHERE c.name='珏' AND p.enabled=1 AND p.is_default=1
        """
    )
    assert [item["persona_key"] for item in defaults] == ["persona.jue.initial"]


def test_default_persona_must_match_the_core_initial_stats(database: object) -> None:
    engine = BattleEngine(database)
    loader = ContentLoader(database, engine.registry.keys)
    loader.load_path(BASE_PACK)
    changed = json.loads(CORE_PERSONAS.read_text(encoding="utf-8"))
    default = next(item for item in changed["personas"] if item.get("default"))
    default["max_hp"] += 1

    with pytest.raises(ContentValidationError, match="初始数据一致"):
        loader.load(changed)


def test_existing_persona_key_cannot_be_moved_to_another_core_character(
    database: object,
) -> None:
    engine = _load_core(database)
    changed = json.loads(CORE_PERSONAS.read_text(encoding="utf-8"))
    persona = next(
        item
        for item in changed["personas"]
        if item["key"] == "persona.jue.stray_hound_boss"
    )
    persona["character"] = "露"

    with pytest.raises(ContentValidationError):
        ContentLoader(database, engine.registry.keys).load(changed)

    owner = database.fetch_one(
        """
        SELECT c.name FROM personas p
        JOIN characters c ON c.id=p.character_id
        WHERE p.persona_key='persona.jue.stray_hound_boss'
        """
    )
    assert owner is not None
    assert owner["name"] == "珏"


def test_assists_act_before_player_cores(database: object) -> None:
    """2026-07-26 裁定：回合顺序为 助战 → 玩家核心 → 敌方，可由 GM 让行跳过。"""
    engine = _load_core(database)
    ying = int(engine.get_core_character("莹")["id"])
    assist = engine.spawn_character("enemy.training_shell", Faction.FRIENDLY)
    enemy = engine.spawn_character("enemy.training_shell", Faction.ENEMY)
    engine.start_battle([ying, assist], [enemy])
    lock_enemy_planning(engine)

    skill = next(
        item for item in engine.list_skills(ying)
        if item["available"] and item["target_scope"] == "ENEMY"
        and item["target_method"] == "SELECT_TARGET"
    )
    with pytest.raises(BattleRuleError, match="助战"):
        engine.use_skill(ying, int(skill["id"]), [enemy])

    messages = engine.forfeit_assist_actions()
    assert messages == ()  # 让行是静默流程操作，不播报（2026-07-27 反馈）
    engine.use_skill(ying, int(skill["id"]), [enemy])

    # 我方行动全部耗尽 → 自动移交敌方阶段（2026-07-27 裁定）。
    assert engine.battle_status()["phase"] == "ENEMY_ACTION"
    with pytest.raises(BattleRuleError, match="仅能在我方行动阶段"):
        engine.forfeit_assist_actions()


def test_page_levels_gate_by_team_emotion_and_carry_activates(database: object) -> None:
    """2026-07-27 裁定 2：书页按团队情感分段解锁；携带被动开战即生效。"""
    engine = _load_core(database)
    ContentLoader(database, engine.registry.keys).load_path(
        BASE_PACK.with_name("test_showcase.json")
    )
    ying = int(engine.get_core_character("莹")["id"])
    enemy = engine.spawn_character("enemy.training_shell", Faction.ENEMY)
    engine.start_battle([ying], [enemy])
    lock_enemy_planning(engine)
    battle_id = int(database.fetch_one("SELECT id FROM battles WHERE status='ACTIVE'")["id"])

    with database.transaction() as connection:
        messages = engine._prepare_abnormality_pool(
            connection, battle_id, ["showcase.abnormality.lantern_case"]
        )
    assert any("携带被动生效" in item for item in messages)
    # CARRY 页不进抽取池，但已作为携带被动激活。
    assert database.fetch_one(
        """SELECT COUNT(*) AS n FROM battle_page_pool pool
           JOIN abnormality_pages p ON p.id=pool.page_id
           WHERE pool.battle_id=? AND p.page_type='CARRY'""",
        (battle_id,),
    )["n"] == 0
    assert database.fetch_one(
        """SELECT COUNT(*) AS n FROM battle_active_pages ap
           JOIN abnormality_pages p ON p.id=ap.page_id
           WHERE ap.battle_id=? AND p.page_type='CARRY'""",
        (battle_id,),
    )["n"] == 1

    # 团队情感 3 → 只出 2 级书页候选。
    with database.transaction() as connection:
        connection.execute(
            "UPDATE characters SET emotion_level=3 WHERE id=?", (ying,)
        )
    with database.transaction() as connection:
        offer_messages = engine._create_page_offer(
            connection, battle_id, ying, 3, positive=1, negative=0
        )
    assert any("书页候选" in item for item in offer_messages)
    levels = [
        int(row["level"])
        for row in database.fetch_all(
            """SELECT p.level FROM battle_page_offers o
               JOIN abnormality_pages p ON p.id=o.page_id
               WHERE o.battle_id=? AND o.status='OPEN'""",
            (battle_id,),
        )
    ]
    # 情感 3 级 = 解锁至Ⅱ级：候选只会是 Ⅰ/Ⅱ 级页，Ⅲ 级页不出现。
    assert levels and all(level <= 2 for level in levels)


def test_page_offer_distinguishes_empty_and_exhausted_pool(database: object) -> None:
    engine = _load_core(database)
    ContentLoader(database, engine.registry.keys).load_path(
        BASE_PACK.with_name("test_showcase.json")
    )
    ying = int(engine.get_core_character("莹")["id"])
    enemy = engine.spawn_character("enemy.training_shell", Faction.ENEMY)
    engine.start_battle([ying], [enemy])
    lock_enemy_planning(engine)
    battle_id = int(database.fetch_one("SELECT id FROM battles WHERE status='ACTIVE'")["id"])

    with database.transaction() as connection:
        empty_messages = engine._create_page_offer(
            connection, battle_id, ying, 5, positive=1, negative=0
        )
    assert empty_messages == ["◇ 携带的异想体没有可选书页，本次选择跳过。"]

    with database.transaction() as connection:
        engine._prepare_abnormality_pool(
            connection, battle_id, ["showcase.abnormality.lantern_case"]
        )
        connection.execute(
            "UPDATE battle_page_pool SET status='USED' WHERE battle_id=?",
            (battle_id,),
        )
        exhausted_messages = engine._create_page_offer(
            connection, battle_id, ying, 5, positive=1, negative=0
        )
    assert exhausted_messages == ["◇ 携带的异想体书页已用尽，本次选择跳过。"]
