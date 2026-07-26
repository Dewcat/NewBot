from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dewbot.content import ContentLoader
from dewbot.db import Database
from dewbot.engine import BattleEngine
from dewbot.models import Faction


BASE_PACK = ROOT / "content" / "base_pack.json"


def make_extension_pack() -> dict[str, object]:
    """A data-only pack used to exercise cross-pack composition in tests."""

    return {
        "pack": {
            "key": "test.extension",
            "name": "Test Extension",
            "version": "1.0.0",
            "description": "Extends the base rules without Python changes.",
        },
        "effects": [
            {
                "key": "status.test_focus",
                "name": "Test Focus",
                "category": "GENERIC",
            }
        ],
        "skills": [
            {
                "key": "skill.test.wait",
                "name": "Wait",
                "type": "NORMAL",
                "cooldown": 0,
                "emotion": 0,
                "target_scope": "ENEMY",
                "target_method": "SELECT_TARGET",
                "behaviors": [
                    {
                        "key": "behavior.test.wait.damage",
                        "timing": "ON",
                        "effect_type": "DAMAGE",
                        "value": "0",
                    }
                ],
            },
            {
                "key": "skill.test.cooldown",
                "name": "Measured Interval",
                "type": "NORMAL",
                "cooldown": 2,
                "emotion": 0,
                "target_scope": "ENEMY",
                "target_method": "SELECT_TARGET",
                "behaviors": [
                    {
                        "key": "behavior.test.cooldown.damage",
                        "timing": "ON",
                        "effect_type": "DAMAGE",
                        "value": "0",
                    }
                ],
            },
            {
                "key": "skill.test.focus",
                "name": "Focus",
                "type": "NORMAL",
                "cooldown": 0,
                "emotion": 0,
                "target_scope": "SELF",
                "target_method": "SELF",
                "behaviors": [
                    {
                        "key": "behavior.test.focus.apply",
                        "timing": "ON",
                        "effect_type": "APPLY_EFFECT",
                        "effect_key": "status.test_focus",
                        "params": {"intensity": 3},
                    }
                ],
            },
            {
                "key": "skill.test.ignite",
                "name": "Ignite",
                "type": "NORMAL",
                "cooldown": 0,
                "emotion": 0,
                "target_scope": "ENEMY",
                "target_method": "SELECT_TARGET",
                "behaviors": [
                    {
                        "key": "behavior.test.ignite.apply",
                        "timing": "ON",
                        "effect_type": "APPLY_EFFECT",
                        "effect_key": "status.burn",
                        "params": {"intensity": 7, "stacks": 1},
                    }
                ],
            },
            {
                "key": "skill.test.ego_one",
                "name": "E.G.O One",
                "type": "EGO",
                "cooldown": 0,
                "emotion": 1,
                "target_scope": "ENEMY",
                "target_method": "SELECT_TARGET",
                "behaviors": [
                    {
                        "key": "behavior.test.ego_one.damage",
                        "timing": "ON",
                        "effect_type": "DAMAGE",
                        "value": "0",
                    }
                ],
            },
            {
                "key": "skill.test.ego_two",
                "name": "E.G.O Two",
                "type": "EGO",
                "cooldown": 0,
                "emotion": 1,
                "target_scope": "ENEMY",
                "target_method": "SELECT_TARGET",
                "behaviors": [
                    {
                        "key": "behavior.test.ego_two.damage",
                        "timing": "ON",
                        "effect_type": "DAMAGE",
                        "value": "0",
                    }
                ],
            },
        ],
        "characters": [
            {
                "key": "unit.test_hero",
                "name": "Test Hero",
                "max_hp": 200,
                "max_actions": 2,
                "max_stagger": 150,
                "tags": [],
                # These base-pack references are intentional: extension packs
                # must be able to compose existing skills with new content.
                "skills": [
                    "skill.common.guard",
                    "skill.test.wait",
                    "skill.test.cooldown",
                    "skill.test.focus",
                    "skill.test.ignite",
                    "skill.test.ego_two",
                ],
                "ego_skill": "skill.test.ego_one",
            },
            {
                "key": "enemy.test_dummy",
                "name": "Test Dummy",
                "max_hp": 500,
                "max_actions": 2,
                "max_stagger": 120,
                "tags": [],
                "skills": [
                    "skill.test.wait",
                    "skill.common.delayed_weakness",
                ],
            },
        ],
        "abnormalities": [],
        "manager_skills": [],
    }


@pytest.fixture
def database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test_game.sqlite3")
    database.initialize()
    return database


@pytest.fixture
def loaded_database(database: Database) -> Database:
    loader = ContentLoader(database)
    loader.load_path(BASE_PACK)
    loader.load(make_extension_pack())
    return database


@pytest.fixture
def world(loaded_database: Database) -> SimpleNamespace:
    engine = BattleEngine(loaded_database)
    hero_id = engine.spawn_character("unit.test_hero", Faction.FRIENDLY)
    enemy_id = engine.spawn_character("enemy.test_dummy", Faction.ENEMY)
    skill_ids = {
        row["skill_key"]: int(row["id"])
        for row in loaded_database.fetch_all("SELECT id,skill_key FROM skills WHERE enabled=1")
    }
    return SimpleNamespace(
        database=loaded_database,
        engine=engine,
        hero_id=hero_id,
        enemy_id=enemy_id,
        skill_ids=skill_ids,
    )
