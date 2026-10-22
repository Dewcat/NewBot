from __future__ import annotations

import json
from pathlib import Path

import pytest

from dewbot.content import ContentLoader
from dewbot.db import Database
from dewbot.models import ContentValidationError

from conftest import BASE_PACK, make_extension_pack


EXAMPLE_PACK = BASE_PACK.parents[1] / "content" / "example_extension.json"
CORE_PERSONAS = BASE_PACK.parents[1] / "content" / "core_personas.json"
SHOWCASE_PACK = BASE_PACK.parents[1] / "content" / "test_showcase.json"


def _count(database: Database, table: str) -> int:
    row = database.fetch_one(f"SELECT COUNT(*) AS amount FROM {table}")
    assert row is not None
    return int(row["amount"])


def _content(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_loading_the_same_pack_twice_is_idempotent(database: Database) -> None:
    loader = ContentLoader(database)

    first = loader.load_path(BASE_PACK)
    second = loader.load_path(BASE_PACK)

    assert second == first
    assert _count(database, "content_packs") == 1
    assert _count(database, "effect_definitions") == first.effects
    assert _count(database, "skills") == first.skills
    assert _count(database, "skill_behaviors") == first.behaviors
    assert _count(database, "character_templates") == first.characters
    assert _count(database, "personas") == first.personas

    enabled_skills = database.fetch_one(
        "SELECT COUNT(*) AS amount FROM skills WHERE pack_key=? AND enabled=1",
        (first.pack_key,),
    )
    assert enabled_skills is not None
    assert int(enabled_skills["amount"]) == first.skills


def test_extension_pack_adds_content_and_reuses_base_definitions(database: Database) -> None:
    loader = ContentLoader(database)
    base = loader.load_path(BASE_PACK)
    extension_pack = make_extension_pack()

    first_extension = loader.load(extension_pack)
    second_extension = loader.load(extension_pack)

    assert second_extension == first_extension
    assert _count(database, "content_packs") == 2
    assert _count(database, "effect_definitions") == base.effects + first_extension.effects
    assert _count(database, "skills") == base.skills + first_extension.skills
    assert _count(database, "character_templates") == (
        base.characters + first_extension.characters
    )

    cross_pack_skill = database.fetch_one(
        """
        SELECT s.skill_key,s.pack_key,t.pack_key AS template_pack
        FROM template_skills ts
        JOIN skills s ON s.id=ts.skill_id
        JOIN character_templates t ON t.template_key=ts.template_key
        WHERE ts.template_key=? AND s.skill_key=?
        """,
        ("unit.test_hero", "skill.common.guard"),
    )
    assert cross_pack_skill is not None
    assert cross_pack_skill["pack_key"] == "dewbot.base"
    assert cross_pack_skill["template_pack"] == "test.extension"

    new_skill = database.fetch_one(
        "SELECT enabled FROM skills WHERE skill_key=? AND pack_key=?",
        ("skill.test.focus", "test.extension"),
    )
    assert new_skill is not None
    assert int(new_skill["enabled"]) == 1


def test_showcase_pack_defines_zero_action_persona_dummy(
    database: Database,
) -> None:
    loader = ContentLoader(database)
    loader.load_path(BASE_PACK)
    result = loader.load_path(SHOWCASE_PACK)

    assert result.version == "1.4.0"
    dummy = database.fetch_one(
        """
        SELECT max_hp,max_actions,max_stagger
        FROM character_templates
        WHERE template_key='enemy.showcase.persona_dummy'
        """
    )
    assert dummy is not None
    assert (
        int(dummy["max_hp"]),
        int(dummy["max_actions"]),
        int(dummy["max_stagger"]),
    ) == (9999, 0, 9999)
    encounter = database.fetch_one(
        """
        SELECT name FROM encounters
        WHERE encounter_key='encounter.showcase.persona_dummy'
        """
    )
    assert encounter is not None
    assert encounter["name"] == "人格打桩测试"


def test_declared_pack_dependency_enforces_load_order(database: Database) -> None:
    loader = ContentLoader(database)
    with pytest.raises(ContentValidationError, match="dewbot.base"):
        loader.load_path(EXAMPLE_PACK)

    loader.load_path(BASE_PACK)
    with pytest.raises(ContentValidationError, match="dewbot.core_personas"):
        loader.load_path(EXAMPLE_PACK)
    loader.load_path(CORE_PERSONAS)
    result = loader.load_path(EXAMPLE_PACK)
    assert result.pack_key == "dewbot.example"
    dependency = database.fetch_one(
        """
        SELECT min_version FROM content_pack_dependencies
        WHERE pack_key='dewbot.example' AND required_pack_key='dewbot.base'
        """
    )
    assert dependency is not None
    assert dependency["min_version"] == "2.0.0"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda data: data["encounters"][-1]["stages"][-1].update(
                {"on_clear": "NEXT_STAGE"}
            ),
            "最后一个 stage",
        ),
        (
            lambda data: data["encounters"][-1]["stages"][0].update(
                {
                    "clear_when": {
                        "type": "TARGET_DEFEATED",
                        "target": "frontline",
                    }
                }
            ),
            "必须且只能生成 1 名敌人",
        ),
        (
            lambda data: data["encounters"][-1].update(
                {"abnormalities": ["missing.abnormality"]}
            ),
            "异想体不存在或已停用",
        ),
        (
            lambda data: data["skills"][0].update({"type": "EGO", "emotion": 0}),
            "EGO 的 emotion 必须在1-5之间",
        ),
        (
            lambda data: data["characters"][0].update(
                {"skills": ["skill.common.strike", "skill.common.strike"]}
            ),
            "存在重复引用",
        ),
    ],
)
def test_content_semantics_fail_during_load(
    database: Database, mutate: object, message: str
) -> None:
    data = _content(BASE_PACK)
    mutate(data)

    with pytest.raises(ContentValidationError, match=message):
        ContentLoader(database).load(data)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("cooldown", 1),
        ("max_uses_per_battle", 2),
    ],
)
def test_ego_is_always_cooldown_free_and_once_per_battle(
    database: Database, field: str, invalid_value: int
) -> None:
    data = _content(BASE_PACK)
    skill = data["skills"][0]
    skill.update(
        {
            "type": "EGO",
            "emotion": 1,
            "cooldown": 0,
            "max_uses_per_battle": 1,
        }
    )
    skill[field] = invalid_value

    with pytest.raises(ContentValidationError, match="EGO"):
        ContentLoader(database).load(data)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update({"skillz": []}),
        lambda data: data["characters"][0].update({"max_healt": 999}),
        lambda data: data["encounters"][0]["stages"][0].update(
            {"clear_whem": {"type": "ALL_ENEMIES_DEFEATED"}}
        ),
    ],
)
def test_unknown_content_fields_are_rejected_as_likely_typos(
    database: Database, mutate: object
) -> None:
    data = _content(BASE_PACK)
    mutate(data)

    with pytest.raises(ContentValidationError, match="未知字段"):
        ContentLoader(database).load(data)


def test_persona_skill_references_must_be_unique(database: Database) -> None:
    loader = ContentLoader(database)
    loader.load_path(BASE_PACK)
    core = _content(CORE_PERSONAS)
    core["personas"][0]["skills"] = [
        "skill.common.strike",
        "skill.common.strike",
    ]

    with pytest.raises(ContentValidationError, match="存在重复引用"):
        loader.load(core)


@pytest.mark.parametrize(
    ("field", "skill_key"),
    [
        ("skills", "skill.test.wait"),
        ("ego_skills", "skill.test.ego_one"),
    ],
)
def test_character_extension_skill_references_must_be_unique(
    database: Database, field: str, skill_key: str
) -> None:
    loader = ContentLoader(database)
    loader.load_path(BASE_PACK)
    extension = make_extension_pack()
    extension["character_extensions"] = [
        {
            "template_key": "unit.training_assistant",
            field: [skill_key, skill_key],
        }
    ]

    with pytest.raises(ContentValidationError, match="存在重复引用"):
        loader.load(extension)


@pytest.mark.parametrize(
    "phase",
    [
        "BATTLE_START",
        "STAGE_SELECTION",
        "TURN_START",
        "TURN_END",
        "BATTLE_END",
    ],
)
def test_manager_skill_rejects_noninteractive_phase(
    database: Database, phase: str
) -> None:
    loader = ContentLoader(database)
    loader.load_path(BASE_PACK)
    loader.load_path(CORE_PERSONAS)
    extension = _content(EXAMPLE_PACK)
    extension["manager_skills"][0]["allowed_phase"] = phase

    with pytest.raises(ContentValidationError, match="allowed_phase 只允许"):
        loader.load(extension)


def test_regular_effects_outside_builtin_five_are_rejected(database: Database) -> None:
    loader = ContentLoader(database)
    pack = {
        "pack": {"key": "test.regular", "name": "Regular Guard", "version": "1.0.0"},
        "effects": [
            {"key": "status.custom_dot", "name": "Custom DoT", "category": "REGULAR"}
        ],
    }
    with pytest.raises(ContentValidationError, match="REGULAR 仅限五种内置常规效果"):
        loader.load(pack)
