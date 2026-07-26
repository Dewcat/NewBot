from __future__ import annotations

import json
import math
import random
import sqlite3
from dataclasses import asdict, replace as dataclass_replace
from typing import Any, Iterable

from .db import Database
from .dice import roll_formula
from .effects import EffectExecutionContext, SpecialEffectRegistry
from .models import (
    ActionResult,
    BattleEvent,
    BattleEventSnapshot,
    BattlePhase,
    BattleRuleError,
    ContentValidationError,
    EffectCategory,
    Faction,
    HitSnapshot,
    SkillType,
    TargetMethod,
    TargetScope,
    Timing,
    TriggerCondition,
    TriggerScope,
)
from .narration import EFFECT_NAMES, Narrator


EMOTION_THRESHOLDS = {0: 3, 1: 3, 2: 5, 3: 7, 4: 9}
from .models import GENERIC_EFFECTS, REGULAR_EFFECTS  # noqa: F401  (re-export)


def _loads(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class BattleEngine:
    """Transactional, data-driven battle engine."""

    def __init__(
        self,
        database: Database,
        *,
        registry: SpecialEffectRegistry | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.database = database
        self.registry = registry or SpecialEffectRegistry()
        self.rng = rng or random.Random()
        self.narrator = Narrator()
        self._register_builtin_special_effects()
        self.validate_content_handlers()

    def validate_content_handlers(self) -> None:
        """Fail fast when enabled data references an unregistered mechanism."""
        missing: set[str] = set()
        with self.database.reading() as connection:
            for row in connection.execute(
                """
                SELECT handler_key FROM effect_definitions
                WHERE enabled=1 AND handler_key IS NOT NULL
                UNION ALL
                SELECT p.handler_key FROM abnormality_pages p
                JOIN abnormalities a ON a.id=p.abnormality_id
                WHERE p.enabled=1 AND a.enabled=1 AND p.handler_key IS NOT NULL
                UNION ALL
                SELECT handler_key FROM manager_skills
                WHERE enabled=1
                """
            ):
                if not self.registry.contains(row["handler_key"]):
                    missing.add(str(row["handler_key"]))
            for row in connection.execute(
                """
                SELECT effect_value,effect_params_json FROM skill_behaviors
                WHERE enabled=1 AND effect_type='SPECIAL'
                """
            ):
                params = _loads(row["effect_params_json"], {})
                handler = row["effect_value"] or params.get("handler")
                if handler and not self.registry.contains(str(handler)):
                    missing.add(str(handler))
        if missing:
            raise ContentValidationError(
                "内容引用了未注册的特殊处理器：" + ", ".join(sorted(missing))
            )

    # ------------------------------------------------------------------
    # Content-backed roster
    # ------------------------------------------------------------------
    def spawn_character(
        self,
        template_key: str,
        faction: Faction | str,
        *,
        name: str | None = None,
    ) -> int:
        faction = Faction(faction)
        with self.database.transaction() as connection:
            return self._spawn_character(connection, template_key, faction, name=name)

    def _spawn_character(
        self,
        connection: sqlite3.Connection,
        template_key: str,
        faction: Faction,
        *,
        name: str | None = None,
    ) -> int:
        template = connection.execute(
            "SELECT * FROM character_templates WHERE template_key=? AND enabled=1",
            (template_key,),
        ).fetchone()
        if template is None:
            raise BattleRuleError(f"未找到可用角色模板：{template_key}")
        max_hp = int(template["max_hp"])
        max_actions = int(template["max_actions"])
        max_stagger = int(template["max_stagger"])
        cursor = connection.execute(
            """
            INSERT INTO characters(
                template_key,name,description,faction,is_core,content_pack_key,
                ego_skill_id,active_persona_id,current_hp,max_hp,current_actions,
                max_actions,current_stagger,max_stagger,tags_json
            ) VALUES(?,?,?, ?,0,NULL,NULL,NULL,?,?,?,?,?,?,?)
            """,
            (
                template_key,name or template["name"],template["description"],faction.value,
                max_hp,max_hp,max_actions,max_actions,
                max_stagger,max_stagger,template["tags_json"],
            ),
        )
        return int(cursor.lastrowid)

    def switch_persona(
        self, character_id: int, persona_key: str, *, enforce_access: bool = False
    ) -> None:
        with self.database.transaction() as connection:
            if self._is_active_participant(connection, character_id):
                raise BattleRuleError("战斗记录仍在展开，不能切换人格。")
            character = self._character(connection, character_id)
            if not int(character["is_core"]):
                raise BattleRuleError("生成单位不具备人格切换记录。")
            persona = connection.execute(
                """
                SELECT * FROM personas
                WHERE persona_key=? AND character_id=? AND enabled=1
                """,
                (persona_key, character_id),
            ).fetchone()
            if persona is None:
                raise BattleRuleError("该角色无法使用指定人格。")
            # 玩家侧切换：人格须已对玩家开放（默认人格恒视为开放）。
            if enforce_access and not int(persona["is_default"]):
                opened = connection.execute(
                    "SELECT 1 FROM persona_access WHERE persona_key=?",
                    (persona_key,),
                ).fetchone()
                if opened is None:
                    raise BattleRuleError(
                        f"人格「{persona['name']}」尚未对玩家开放。"
                    )
            if int(character["active_persona_id"] or 0) == int(persona["id"]):
                raise BattleRuleError(f"{character['name']} 当前已经装备该人格。")
            max_hp = int(persona["max_hp"])
            max_actions = int(persona["max_actions"])
            max_stagger = int(persona["max_stagger"])
            connection.execute(
                """
                UPDATE characters SET active_persona_id=?,max_hp=?,current_hp=?,
                    max_actions=?,current_actions=?,max_stagger=?,current_stagger=?
                WHERE id=?
                """,
                (
                    persona["id"], max_hp, max_hp, max_actions, max_actions,
                    max_stagger, max_stagger, character_id,
                ),
            )

    def list_characters(self, faction: Faction | str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT c.*,COALESCE(t.enabled,0) AS template_enabled "
            "FROM characters c LEFT JOIN character_templates t ON t.template_key=c.template_key"
        )
        params: tuple[object, ...] = ()
        if faction is not None:
            sql += " WHERE c.faction=?"
            params = (Faction(faction).value,)
        sql += " ORDER BY c.faction DESC,c.id"
        return [dict(row) for row in self.database.fetch_all(sql, params)]


    def get_core_character(self, name: str) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT * FROM characters WHERE is_core=1 AND name=?", (name,)
        )
        if row is None:
            raise BattleRuleError(f"核心角色不存在：{name}")
        return dict(row)

    def get_character(self, character_id: int) -> dict[str, Any]:
        row = self.database.fetch_one("SELECT * FROM characters WHERE id=?", (character_id,))
        if row is None:
            raise BattleRuleError(f"角色 #{character_id} 不存在。")
        return dict(row)

    def list_templates(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.database.fetch_all(
                "SELECT * FROM character_templates WHERE enabled=1 ORDER BY name"
            )
        ]

    def list_personas(self, character_id: int) -> list[dict[str, Any]]:
        with self.database.reading() as connection:
            character = self._character(connection, character_id)
            rows = connection.execute(
                """
                SELECT p.*,
                       CASE WHEN p.id=? THEN 1 ELSE 0 END AS is_active,
                       CASE WHEN p.is_default=1 OR acc.persona_key IS NOT NULL
                            THEN 1 ELSE 0 END AS opened
                FROM personas p
                LEFT JOIN persona_access acc ON acc.persona_key=p.persona_key
                WHERE p.character_id=? AND p.enabled=1
                ORDER BY p.is_default DESC,p.id
                """,
                (character["active_persona_id"], character_id),
            ).fetchall()
            return [dict(row) for row in rows]

    def set_persona_access(
        self, persona_keys: Iterable[str], opened: bool
    ) -> list[str]:
        """GM 面板：控制人格是否对玩家开放；默认人格恒开放，不可收回。"""
        keys = list(dict.fromkeys(str(key) for key in persona_keys))
        if not keys:
            raise BattleRuleError("至少指定一个人格。")
        names = []
        with self.database.transaction() as connection:
            for key in keys:
                row = connection.execute(
                    "SELECT name,is_default FROM personas"
                    " WHERE persona_key=? AND enabled=1",
                    (key,),
                ).fetchone()
                if row is None:
                    raise BattleRuleError(f"人格未登记：{key}")
                if not opened and int(row["is_default"]):
                    raise BattleRuleError(
                        f"「{row['name']}」是默认人格，不能对玩家关闭。"
                    )
                names.append(str(row["name"]))
                if opened:
                    connection.execute(
                        "INSERT OR IGNORE INTO persona_access(persona_key) VALUES(?)",
                        (key,),
                    )
                else:
                    connection.execute(
                        "DELETE FROM persona_access WHERE persona_key=?", (key,)
                    )
        return names

    def skill_catalog(self, character_id: int) -> list[dict[str, Any]]:
        """Return the active persona's skill definitions outside battle state."""
        with self.database.reading() as connection:
            character = self._character(connection, character_id)
            return [dict(row) for row in self._character_skill_rows(connection, character)]

    # ------------------------------------------------------------------
    # Encounter-backed battle formation
    # ------------------------------------------------------------------
    def list_encounters(self) -> list[dict[str, Any]]:
        return [
            dict(row) for row in self.database.fetch_all(
                """
                SELECT e.*,COUNT(s.id) AS total_stages
                FROM encounters e
                LEFT JOIN encounter_stages s ON s.encounter_key=e.encounter_key
                WHERE e.enabled=1
                GROUP BY e.encounter_key ORDER BY e.name
                """
            )
        ]

    def prepare_encounter(
        self, encounter_key: str, *, name: str | None = None,
        created_by: int | None = None, selection_chat_id: int = 0,
    ) -> int:
        with self.database.transaction() as connection:
            encounter = connection.execute(
                "SELECT * FROM encounters WHERE encounter_key=? AND enabled=1",
                (encounter_key,),
            ).fetchone()
            if encounter is None:
                raise BattleRuleError(f"未找到可用关卡：{encounter_key}")
            display_name = (name or str(encounter["name"])).strip()
            if not display_name:
                raise BattleRuleError("战斗名称不能为空。")
            if len(display_name) > 80:
                raise BattleRuleError("战斗名称不能超过 80 个字符。")
            cursor = connection.execute(
                """
                INSERT INTO battle_setups(
                    encounter_key,created_by,name,abnormalities_json
                ) VALUES(?,?,?,?)
                """,
                (
                    encounter_key, created_by, display_name,
                    encounter["abnormalities_json"],
                ),
            )
            setup_id = int(cursor.lastrowid)
            if created_by is not None:
                connection.execute(
                    """
                    INSERT INTO battle_setup_selections(user_id,chat_id,setup_id)
                    VALUES(?,?,?) ON CONFLICT(user_id,chat_id) DO UPDATE SET
                        setup_id=excluded.setup_id,selected_at=CURRENT_TIMESTAMP
                    """, (created_by, int(selection_chat_id), setup_id)
                )
            connection.execute(
                """
                INSERT INTO battle_setup_stages(
                    setup_id,stage_number,name,description,
                    clear_condition_json,clear_outcome
                )
                SELECT ?,stage_number,name,description,
                       clear_condition_json,clear_outcome
                FROM encounter_stages WHERE encounter_key=?
                ORDER BY stage_number
                """, (setup_id, encounter_key)
            )
            connection.execute(
                """
                INSERT INTO battle_setup_enemies(
                    setup_id,stage_number,template_key,amount,display_name,source,enemy_key
                )
                SELECT ?,s.stage_number,e.template_key,e.amount,e.display_name,'ENCOUNTER',
                       e.enemy_key
                FROM encounter_stages s
                JOIN encounter_stage_enemies e ON e.stage_id=s.id
                WHERE s.encounter_key=? ORDER BY s.stage_number,e.position,e.id
                """,
                (setup_id, encounter_key),
            )
            return setup_id

    def list_battle_setups(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.database.fetch_all(
            """
            SELECT bs.*,e.name AS encounter_name,
                   b.current_stage,b.phase,
                   (SELECT COUNT(*) FROM battle_setup_stages s
                    WHERE s.setup_id=bs.id) AS total_stages,
                   (SELECT COUNT(*) FROM battle_setup_friendlies f
                    WHERE f.setup_id=bs.id) AS friendly_count
            FROM battle_setups bs JOIN encounters e ON e.encounter_key=bs.encounter_key
            LEFT JOIN battles b ON b.id=bs.battle_id AND b.status='ACTIVE'
            WHERE bs.status='STANDBY'
               OR (bs.status='ACTIVE' AND EXISTS(
                    SELECT 1 FROM battles b
                    WHERE b.id=bs.battle_id AND b.status='ACTIVE'
               ))
            ORDER BY CASE bs.status WHEN 'ACTIVE' THEN 0 ELSE 1 END,bs.id DESC
            """
        )]

    def select_battle_setup(
        self, user_id: int, setup_id: int, *, chat_id: int = 0
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            setup = self._preparing_setup(
                connection, setup_id=setup_id, allow_active=True
            )
            connection.execute(
                """
                INSERT INTO battle_setup_selections(user_id,chat_id,setup_id)
                VALUES(?,?,?) ON CONFLICT(user_id,chat_id) DO UPDATE SET
                    setup_id=excluded.setup_id,selected_at=CURRENT_TIMESTAMP
                """, (int(user_id), int(chat_id), int(setup["id"]))
            )
            return dict(setup)

    def selected_battle_setup_id(self, user_id: int, *, chat_id: int = 0) -> int:
        with self.database.reading() as connection:
            return int(self._preparing_setup(
                connection, user_id=user_id, chat_id=chat_id, allow_active=True
            )["id"])

    def battle_setup_status(
        self, setup_id: int | None = None, *, user_id: int | None = None,
        chat_id: int = 0,
    ) -> dict[str, Any]:
        params: tuple[object, ...] = ()
        selector = ""
        if setup_id is not None:
            selector = "AND bs.id=?"
            params = (int(setup_id),)
        elif user_id is not None:
            selector = (
                "AND bs.id=(SELECT setup_id FROM battle_setup_selections "
                "WHERE user_id=? AND chat_id IN (?,0) "
                "ORDER BY CASE WHEN chat_id=? THEN 0 ELSE 1 END LIMIT 1)"
            )
            params = (int(user_id), int(chat_id), int(chat_id))
        setup = self.database.fetch_one(
            """
            SELECT bs.*,e.name AS encounter_name,e.description,
                   b.current_stage,b.phase,
                   (SELECT COUNT(*) FROM battle_setup_stages s
                    WHERE s.setup_id=bs.id) AS total_stages
            FROM battle_setups bs JOIN encounters e ON e.encounter_key=bs.encounter_key
            LEFT JOIN battles b ON b.id=bs.battle_id AND b.status='ACTIVE'
            WHERE (bs.status='STANDBY'
               OR (bs.status='ACTIVE' AND EXISTS(
                    SELECT 1 FROM battles b WHERE b.id=bs.battle_id AND b.status='ACTIVE'
               )))
            """ + selector + " ORDER BY bs.id DESC LIMIT 1",
            params,
        )
        if setup is None:
            if setup_id is not None:
                raise BattleRuleError(
                    "该战斗不存在、已结束或已撤销；使用 /battles 查看可选战斗。"
                )
            raise BattleRuleError(
                "当前没有选中的待触发战斗；请先用 /new <名称> 建立，"
                "或用 /battles 查看后 /use <编号> 选中。"
            )
        result = dict(setup)
        result["friendlies"] = [dict(row) for row in self.database.fetch_all(
            """
            SELECT c.id,c.name,c.is_core,c.current_hp,
                   COALESCE(t.enabled,0) AS template_enabled,
                   p.persona_key,p.name AS persona_name
            FROM battle_setup_friendlies f
            JOIN characters c ON c.id=f.character_id
            LEFT JOIN character_templates t ON t.template_key=c.template_key
            LEFT JOIN personas p ON p.id=f.persona_id
            WHERE f.setup_id=? ORDER BY c.is_core DESC,c.id
            """, (setup["id"],)
        )]
        result["enemies"] = [dict(row) for row in self.database.fetch_all(
            """
            SELECT se.*,t.name AS template_name
            FROM battle_setup_enemies se
            JOIN character_templates t ON t.template_key=se.template_key
            WHERE se.setup_id=? ORDER BY se.stage_number,se.id
            """, (setup["id"],)
        )]
        result["stages"] = [dict(row) for row in self.database.fetch_all(
            """
            SELECT stage_number,name,description,clear_condition_json,clear_outcome
            FROM battle_setup_stages
            WHERE setup_id=? ORDER BY stage_number
            """, (setup["id"],)
        )]
        return result

    def cancel_battle_setup(
        self, setup_id: int | None = None, *, user_id: int | None = None
    ) -> None:
        with self.database.transaction() as connection:
            setup = self._preparing_setup(
                connection, setup_id=setup_id, user_id=user_id
            )
            connection.execute(
                "UPDATE battle_setups SET status='CANCELLED' WHERE id=?",
                (setup["id"],),
            )

    def add_core_to_setup(
        self, character_id: int, persona_id: int, *, setup_id: int | None = None
    ) -> None:
        with self.database.transaction() as connection:
            setup = self._preparing_setup(connection, setup_id=setup_id)
            character = self._character(connection, character_id)
            if not int(character["is_core"]):
                raise BattleRuleError("该角色不是核心角色，请使用普通友方编成命令。")
            persona = connection.execute(
                "SELECT id FROM personas WHERE id=? AND character_id=? AND enabled=1",
                (persona_id, character_id),
            ).fetchone()
            if persona is None:
                raise BattleRuleError("所选人格不属于该核心角色。")
            connection.execute(
                """
                INSERT INTO battle_setup_friendlies(setup_id,character_id,persona_id)
                VALUES(?,?,?) ON CONFLICT(setup_id,character_id) DO UPDATE SET
                    persona_id=excluded.persona_id,added_at=CURRENT_TIMESTAMP
                """, (setup["id"], character_id, persona_id)
            )
            connection.execute(
                "UPDATE battle_setups SET revision=revision+1 WHERE id=?",
                (setup["id"],),
            )

    def set_setup_core_pool(
        self, character_ids: Iterable[int], *, setup_id: int | None = None
    ) -> list[str]:
        """GM 圈定本场"可参战核心"（2026-07-26 裁定：出战与人格由玩家决定）。

        同步维护编成：池外核心移出编成；池内核心若尚未编入，则以当前
        激活人格补进，保证 GM「直接触发」路径依旧可用。
        """
        ids = list(dict.fromkeys(int(item) for item in character_ids))
        with self.database.transaction() as connection:
            setup = self._preparing_setup(connection, setup_id=setup_id)
            names = []
            for character_id in ids:
                character = self._character(connection, character_id)
                if not int(character["is_core"]):
                    raise BattleRuleError(f"{character['name']} 不是核心角色。")
                names.append(str(character["name"]))
            connection.execute(
                "UPDATE battle_setups SET core_pool_json=?,revision=revision+1"
                " WHERE id=?",
                (_dumps(ids), setup["id"]),
            )
            # 池外核心移出编成。
            placeholders = ",".join("?" for _ in ids) or "NULL"
            connection.execute(
                f"""
                DELETE FROM battle_setup_friendlies
                WHERE setup_id=? AND character_id IN (
                    SELECT id FROM characters WHERE is_core=1
                ) AND character_id NOT IN ({placeholders})
                """,
                (setup["id"], *ids),
            )
            # 池内核心补进编成（默认用当前激活人格，玩家确认时可改）。
            for character_id in ids:
                existing = connection.execute(
                    "SELECT 1 FROM battle_setup_friendlies"
                    " WHERE setup_id=? AND character_id=?",
                    (setup["id"], character_id),
                ).fetchone()
                if existing is not None:
                    continue
                character = self._character(connection, character_id)
                if character["active_persona_id"] is None:
                    raise BattleRuleError(
                        f"{character['name']} 没有激活人格，无法加入可参战池。"
                    )
                connection.execute(
                    "INSERT INTO battle_setup_friendlies(setup_id,character_id,persona_id)"
                    " VALUES(?,?,?)",
                    (setup["id"], character_id, int(character["active_persona_id"])),
                )
            return names

    def replace_core_formation(
        self,
        setup_id: int,
        choices: Iterable[tuple[int, int]],
    ) -> None:
        """Atomically replace every core selection in one standby battle."""
        normalized = [(int(character_id), int(persona_id)) for character_id, persona_id in choices]
        character_ids = [character_id for character_id, _ in normalized]
        if len(character_ids) != len(set(character_ids)):
            raise BattleRuleError("同一名核心角色不能在编成中重复出现。")
        with self.database.transaction() as connection:
            setup = self._preparing_setup(connection, setup_id=int(setup_id))
            pool = {int(item) for item in _loads(setup["core_pool_json"], [])}
            for character_id, persona_id in normalized:
                if pool and character_id not in pool:
                    character = self._character(connection, character_id)
                    raise BattleRuleError(
                        f"{character['name']} 不在本场可参战核心之列。"
                    )
            for character_id, persona_id in normalized:
                character = self._character(connection, character_id)
                if not int(character["is_core"]):
                    raise BattleRuleError(f"{character['name']} 不是核心角色。")
                persona = connection.execute(
                    """
                    SELECT id,persona_key,name,is_default FROM personas
                    WHERE id=? AND character_id=? AND enabled=1
                    """,
                    (persona_id, character_id),
                ).fetchone()
                if persona is None:
                    raise BattleRuleError(f"所选人格不属于 {character['name']}。")
                # 未开放人格不可编入（默认人格与当前装备中的人格豁免）。
                if (
                    not int(persona["is_default"])
                    and int(character["active_persona_id"] or 0) != int(persona["id"])
                    and connection.execute(
                        "SELECT 1 FROM persona_access WHERE persona_key=?",
                        (persona["persona_key"],),
                    ).fetchone() is None
                ):
                    raise BattleRuleError(
                        f"人格「{persona['name']}」尚未对玩家开放。"
                    )
            connection.execute(
                """
                DELETE FROM battle_setup_friendlies
                WHERE setup_id=? AND character_id IN (
                    SELECT id FROM characters WHERE is_core=1
                )
                """,
                (setup["id"],),
            )
            connection.executemany(
                """
                INSERT INTO battle_setup_friendlies(setup_id,character_id,persona_id)
                VALUES(?,?,?)
                """,
                [
                    (int(setup["id"]), character_id, persona_id)
                    for character_id, persona_id in normalized
                ],
            )
            connection.execute(
                "UPDATE battle_setups SET revision=revision+1 WHERE id=?",
                (setup["id"],),
            )

    def list_abnormalities(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.database.fetch_all(
                """
                SELECT a.id,a.abnormality_key,a.name,a.description,
                       COUNT(p.id) AS page_count
                FROM abnormalities a
                LEFT JOIN abnormality_pages p
                    ON p.abnormality_id=a.id AND p.enabled=1
                WHERE a.enabled=1 GROUP BY a.id ORDER BY a.id
                """
            )
        ]

    def set_setup_abnormalities(
        self, abnormality_keys: Iterable[str], *, setup_id: int | None = None
    ) -> list[str]:
        """战前装备异想体：整套替换待触发战斗的书页池来源（todo 规则F）。"""
        keys = list(dict.fromkeys(str(key) for key in abnormality_keys))
        if len(keys) > 5:
            raise BattleRuleError("最多携带 5 个异想体。")
        with self.database.transaction() as connection:
            setup = self._preparing_setup(connection, setup_id=setup_id)
            for key in keys:
                abnormality = connection.execute(
                    "SELECT id FROM abnormalities WHERE abnormality_key=? AND enabled=1",
                    (key,),
                ).fetchone()
                if abnormality is None:
                    raise BattleRuleError(f"异想体未登记：{key}")
            self._assert_abnormalities_opened(connection, keys)
            connection.execute(
                "UPDATE battle_setups SET abnormalities_json=?,revision=revision+1"
                " WHERE id=?",
                (_dumps(keys), setup["id"]),
            )
        return keys

    def get_page_deck(self) -> list[dict[str, Any]]:
        """玩家常备异想体书页卡组（跨战斗持久，2026-07-26 裁定 §7.5-4）。"""
        return [
            dict(row)
            for row in self.database.fetch_all(
                """
                SELECT a.abnormality_key,a.name,a.description,
                       COUNT(p.id) AS page_count
                FROM player_page_deck d
                JOIN abnormalities a
                    ON a.abnormality_key=d.abnormality_key AND a.enabled=1
                LEFT JOIN abnormality_pages p
                    ON p.abnormality_id=a.id AND p.enabled=1
                GROUP BY a.id ORDER BY d.added_at,a.id
                """
            )
        ]

    def set_page_deck(self, abnormality_keys: Iterable[str]) -> list[str]:
        """整套替换玩家常备卡组；开战（发布编成）时自动带入书页池。"""
        keys = list(dict.fromkeys(str(key) for key in abnormality_keys))
        if len(keys) > 5:
            raise BattleRuleError("最多携带 5 个异想体。")
        with self.database.transaction() as connection:
            for key in keys:
                row = connection.execute(
                    "SELECT 1 FROM abnormalities WHERE abnormality_key=? AND enabled=1",
                    (key,),
                ).fetchone()
                if row is None:
                    raise BattleRuleError(f"异想体未登记：{key}")
            self._assert_abnormalities_opened(connection, keys)
            connection.execute("DELETE FROM player_page_deck")
            for key in keys:
                connection.execute(
                    "INSERT INTO player_page_deck(abnormality_key) VALUES(?)", (key,)
                )
        return keys

    def set_abnormality_access(
        self, abnormality_keys: Iterable[str], opened: bool
    ) -> list[str]:
        """GM 面板：控制异想体是否对玩家开放（2026-07-27 裁定）。"""
        keys = list(dict.fromkeys(str(key) for key in abnormality_keys))
        if not keys:
            raise BattleRuleError("至少指定一个异想体。")
        names = []
        with self.database.transaction() as connection:
            for key in keys:
                row = connection.execute(
                    "SELECT name FROM abnormalities WHERE abnormality_key=? AND enabled=1",
                    (key,),
                ).fetchone()
                if row is None:
                    raise BattleRuleError(f"异想体未登记：{key}")
                names.append(str(row["name"]))
                if opened:
                    connection.execute(
                        "INSERT OR IGNORE INTO abnormality_access(abnormality_key)"
                        " VALUES(?)",
                        (key,),
                    )
                else:
                    connection.execute(
                        "DELETE FROM abnormality_access WHERE abnormality_key=?", (key,)
                    )
        return names

    def _assert_abnormalities_opened(
        self, connection: sqlite3.Connection, keys: Iterable[str]
    ) -> None:
        for key in keys:
            row = connection.execute(
                "SELECT 1 FROM abnormality_access WHERE abnormality_key=?", (key,)
            ).fetchone()
            if row is None:
                name_row = connection.execute(
                    "SELECT name FROM abnormalities WHERE abnormality_key=?", (key,)
                ).fetchone()
                name = str(name_row["name"]) if name_row else key
                raise BattleRuleError(f"「{name}」尚未对玩家开放。")

    def abnormality_catalog(self) -> list[dict[str, Any]]:
        """带书页明细（含等级/类型/携带被动/开放状态）的异想体清单。"""
        opened_keys = {
            str(row["abnormality_key"])
            for row in self.database.fetch_all(
                "SELECT abnormality_key FROM abnormality_access"
            )
        }
        abnormalities = [
            dict(row)
            for row in self.database.fetch_all(
                "SELECT id,abnormality_key,name,description FROM abnormalities"
                " WHERE enabled=1 ORDER BY id"
            )
        ]
        for item in abnormalities:
            item["opened"] = str(item["abnormality_key"]) in opened_keys
        pages = self.database.fetch_all(
            """
            SELECT abnormality_id,page_key,name,page_type,level,description
            FROM abnormality_pages WHERE enabled=1 ORDER BY level,page_type,id
            """
        )
        by_owner: dict[int, list[dict[str, Any]]] = {}
        for row in pages:
            by_owner.setdefault(int(row["abnormality_id"]), []).append(dict(row))
        for item in abnormalities:
            owned = by_owner.get(int(item["id"]), [])
            item["pages"] = [p for p in owned if p["page_type"] != "CARRY"]
            item["carry_bonus"] = next(
                (p for p in owned if p["page_type"] == "CARRY"), None
            )
        return abnormalities

    def list_page_presets(self) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            "SELECT id,name,abnormality_keys_json,updated_at FROM page_deck_presets"
            " ORDER BY name"
        )
        result = []
        for row in rows:
            item = dict(row)
            item["abnormality_keys"] = _loads(row["abnormality_keys_json"], [])
            result.append(item)
        return result

    def save_page_preset(
        self, name: str, abnormality_keys: Iterable[str]
    ) -> dict[str, Any]:
        """按名称保存/覆盖一套携带预设（二游式编队，上限 5 个异想体）。"""
        title = str(name or "").strip()
        if not title or len(title) > 30:
            raise BattleRuleError("预设名称需为 1-30 个字符。")
        keys = list(dict.fromkeys(str(key) for key in abnormality_keys))
        if not keys:
            raise BattleRuleError("预设至少包含 1 个异想体。")
        if len(keys) > 5:
            raise BattleRuleError("最多携带 5 个异想体。")
        with self.database.transaction() as connection:
            for key in keys:
                row = connection.execute(
                    "SELECT 1 FROM abnormalities WHERE abnormality_key=? AND enabled=1",
                    (key,),
                ).fetchone()
                if row is None:
                    raise BattleRuleError(f"异想体未登记：{key}")
            self._assert_abnormalities_opened(connection, keys)
            connection.execute(
                """
                INSERT INTO page_deck_presets(name,abnormality_keys_json,updated_at)
                VALUES(?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(name) DO UPDATE SET
                    abnormality_keys_json=excluded.abnormality_keys_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (title, _dumps(keys)),
            )
            saved = connection.execute(
                "SELECT id,name,abnormality_keys_json FROM page_deck_presets WHERE name=?",
                (title,),
            ).fetchone()
            result = dict(saved)
            result["abnormality_keys"] = keys
            return result

    def delete_page_preset(self, preset_id: int) -> str:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT name FROM page_deck_presets WHERE id=?", (int(preset_id),)
            ).fetchone()
            if row is None:
                raise BattleRuleError("该预设不存在。")
            connection.execute(
                "DELETE FROM page_deck_presets WHERE id=?", (int(preset_id),)
            )
            return str(row["name"])

    def publish_setup(self, setup_id: int | None = None) -> dict[str, Any]:
        """GM 发布编成给玩家确认（裁定 §7.5-5）。

        发布同时把玩家常备卡组带入本场书页池（玩家可在确认前继续调整）。
        """
        with self.database.transaction() as connection:
            setup = self._preparing_setup(connection, setup_id=setup_id)
            deck = [
                str(row["abnormality_key"])
                for row in connection.execute(
                    """
                    SELECT d.abnormality_key FROM player_page_deck d
                    JOIN abnormalities a
                        ON a.abnormality_key=d.abnormality_key AND a.enabled=1
                    JOIN abnormality_access acc
                        ON acc.abnormality_key=d.abnormality_key
                    ORDER BY d.added_at
                    """
                ).fetchall()
            ]
            if deck:
                connection.execute(
                    "UPDATE battle_setups SET abnormalities_json=? WHERE id=?",
                    (_dumps(deck[:5]), setup["id"]),
                )
            # 出战核心的人格默认采用玩家阵容界面的当前配置（2026-07-27 裁定 4）。
            connection.execute(
                """
                UPDATE battle_setup_friendlies
                SET persona_id=(
                    SELECT c.active_persona_id FROM characters c
                    WHERE c.id=battle_setup_friendlies.character_id
                )
                WHERE setup_id=? AND character_id IN (
                    SELECT id FROM characters
                    WHERE is_core=1 AND active_persona_id IS NOT NULL
                )
                """,
                (setup["id"],),
            )
            connection.execute(
                "UPDATE battle_setups SET published=1,revision=revision+1 WHERE id=?",
                (setup["id"],),
            )
            updated = connection.execute(
                "SELECT * FROM battle_setups WHERE id=?", (setup["id"],)
            ).fetchone()
            return dict(updated)

    def remove_setup_stage(
        self, stage_number: int, *, setup_id: int | None = None
    ) -> str:
        """删除本场编成快照中的一个预设阶段（不影响关卡模板本体）。"""
        with self.database.transaction() as connection:
            setup = self._preparing_setup(connection, setup_id=setup_id)
            total = int(connection.execute(
                "SELECT COUNT(*) FROM battle_setup_stages WHERE setup_id=?",
                (setup["id"],),
            ).fetchone()[0])
            if total <= 1:
                raise BattleRuleError("战斗至少要保留一个阶段。")
            row = connection.execute(
                "SELECT * FROM battle_setup_stages WHERE setup_id=? AND stage_number=?",
                (setup["id"], int(stage_number)),
            ).fetchone()
            if row is None:
                raise BattleRuleError("该阶段不存在。")
            connection.execute(
                "DELETE FROM battle_setup_stages WHERE setup_id=? AND stage_number=?",
                (setup["id"], int(stage_number)),
            )
            connection.execute(
                "DELETE FROM battle_setup_enemies WHERE setup_id=? AND stage_number=?",
                (setup["id"], int(stage_number)),
            )
            # 后续阶段前移补位，保持 1..N 连续。
            for later in connection.execute(
                "SELECT stage_number FROM battle_setup_stages"
                " WHERE setup_id=? AND stage_number>? ORDER BY stage_number",
                (setup["id"], int(stage_number)),
            ).fetchall():
                old = int(later["stage_number"])
                connection.execute(
                    "UPDATE battle_setup_stages SET stage_number=?"
                    " WHERE setup_id=? AND stage_number=?",
                    (old - 1, setup["id"], old),
                )
                connection.execute(
                    "UPDATE battle_setup_enemies SET stage_number=?"
                    " WHERE setup_id=? AND stage_number=?",
                    (old - 1, setup["id"], old),
                )
            connection.execute(
                "UPDATE battle_setups SET revision=revision+1 WHERE id=?",
                (setup["id"],),
            )
            return f"已移除阶段 {int(stage_number)}「{row['name']}」，后续阶段前移补位。"

    def add_noncore_friendlies_to_setup(
        self, character_ids: Iterable[int], *, setup_id: int | None = None
    ) -> None:
        ids = list(dict.fromkeys(int(item) for item in character_ids))
        if not ids:
            raise BattleRuleError("至少需要指定一名普通友方角色。")
        with self.database.transaction() as connection:
            setup = self._preparing_setup(
                connection, setup_id=setup_id, allow_active=True
            )
            changed = False
            for character_id in ids:
                character = self._character(connection, character_id)
                if int(character["is_core"]) or character["faction"] != Faction.FRIENDLY.value:
                    raise BattleRuleError(f"{character['name']} 不是可由此命令编入的普通友方。")
                if int(character["current_hp"]) <= 0:
                    raise BattleRuleError(f"{character['name']} 已无法行动，不能编入战斗。")
                template = connection.execute(
                    "SELECT enabled FROM character_templates WHERE template_key=?",
                    (character["template_key"],),
                ).fetchone()
                if template is None or not int(template["enabled"]):
                    raise BattleRuleError(
                        f"{character['name']} 的单位定义已经停用，不能编入新的战斗。"
                    )
                inserted = connection.execute(
                    "INSERT OR IGNORE INTO battle_setup_friendlies(setup_id,character_id) VALUES(?,?)",
                    (setup["id"], character_id),
                )
                changed = changed or inserted.rowcount == 1
                if setup["status"] == "ACTIVE":
                    battle = connection.execute(
                        "SELECT * FROM battles WHERE id=? AND status='ACTIVE'",
                        (setup["battle_id"],),
                    ).fetchone()
                    if battle is None:
                        raise BattleRuleError("该战斗已经不在运行。")
                    self._add_participants(
                        connection, int(battle["id"]), [character_id],
                        Faction.FRIENDLY, int(battle["current_stage"]),
                    )
            if changed:
                connection.execute(
                    "UPDATE battle_setups SET revision=revision+1 WHERE id=?",
                    (setup["id"],),
                )

    def remove_noncore_friendly_from_setup(
        self, character_id: int, *, setup_id: int
    ) -> None:
        """Remove an optional ordinary ally before a battle is triggered."""
        with self.database.transaction() as connection:
            setup = self._preparing_setup(connection, setup_id=int(setup_id))
            character = self._character(connection, int(character_id))
            if int(character["is_core"]) or character["faction"] != Faction.FRIENDLY.value:
                raise BattleRuleError("只有普通友方可以从可选增援中移除。")
            removed = connection.execute(
                """
                DELETE FROM battle_setup_friendlies
                WHERE setup_id=? AND character_id=? AND persona_id IS NULL
                """,
                (setup["id"], character["id"]),
            )
            if removed.rowcount != 1:
                raise BattleRuleError(f"{character['name']} 当前不在这场战斗的友方编成中。")
            connection.execute(
                "UPDATE battle_setups SET revision=revision+1 WHERE id=?",
                (setup["id"],),
            )

    def add_enemy_to_formation(
        self, template_key: str, *, stage: int | None = None,
        amount: int = 1, name: str | None = None, setup_id: int | None = None,
    ) -> str:
        if amount < 1:
            raise BattleRuleError("敌人数量必须至少为 1。")
        with self.database.transaction() as connection:
            template = connection.execute(
                "SELECT 1 FROM character_templates WHERE template_key=? AND enabled=1",
                (template_key,),
            ).fetchone()
            if template is None:
                raise BattleRuleError(f"敌人模板不存在：{template_key}")
            setup = connection.execute(
                """
                SELECT bs.* FROM battle_setups bs
                WHERE (bs.status='STANDBY'
                   OR (bs.status='ACTIVE' AND EXISTS(
                        SELECT 1 FROM battles b
                        WHERE b.id=bs.battle_id AND b.status='ACTIVE'
                   ))) AND (? IS NULL OR bs.id=?)
                ORDER BY bs.id DESC LIMIT 1
                """, (setup_id, setup_id)
            ).fetchone()
            if setup is None:
                raise BattleRuleError("请先准备一个关卡。")
            battle = None
            if setup["battle_id"] is not None:
                battle = connection.execute(
                    "SELECT * FROM battles WHERE id=? AND status='ACTIVE'", (setup["battle_id"],)
                ).fetchone()
            if battle is not None:
                phase = BattlePhase(battle["phase"])
                default_stage = int(battle["current_stage"]) + (
                    1 if phase == BattlePhase.STAGE_END else 0
                )
            else:
                phase = None
                default_stage = 1
            target_stage = int(stage or default_stage)
            total_stages = connection.execute(
                "SELECT COUNT(*) FROM battle_setup_stages WHERE setup_id=?",
                (setup["id"],),
            ).fetchone()[0]
            if target_stage < 1 or target_stage > int(total_stages):
                raise BattleRuleError(f"阶段必须在 1 到 {total_stages} 之间。")
            if (
                battle is not None
                and target_stage < int(battle["current_stage"])
            ):
                raise BattleRuleError("不能向已经结束的历史阶段追加敌人。")
            if (
                battle is not None
                and phase == BattlePhase.STAGE_END
                and target_stage <= int(battle["current_stage"])
            ):
                raise BattleRuleError("当前阶段已经结束，敌方增援只能加入下一阶段。")
            if battle is not None and target_stage == int(battle["current_stage"]):
                if phase not in {
                    BattlePhase.FRIENDLY_ACTION, BattlePhase.ENEMY_ACTION
                }:
                    raise BattleRuleError("当前正在结算阶段，暂时不能让敌方增援入场。")
                setup_enemy = connection.execute(
                    """
                    INSERT INTO battle_setup_enemies(
                        setup_id,stage_number,template_key,amount,display_name,source
                    ) VALUES(?,?,?,?,?,'MANUAL')
                    """,
                    (setup["id"], target_stage, template_key, amount, name),
                )
                setup_enemy_id = int(setup_enemy.lastrowid)
                spawned = [
                    self._spawn_character(connection, template_key, Faction.ENEMY, name=name)
                    for _ in range(amount)
                ]
                self._add_participants(
                    connection, int(battle["id"]), spawned, Faction.ENEMY, target_stage
                )
                connection.executemany(
                    """
                    INSERT INTO battle_spawn_origins(
                        battle_id,character_id,stage_number,enemy_key,setup_enemy_id
                    ) VALUES(?,?,?,?,?)
                    """,
                    [
                        (int(battle["id"]), character_id, target_stage, None, setup_enemy_id)
                        for character_id in spawned
                    ],
                )
                connection.execute(
                    "UPDATE battle_setups SET revision=revision+1 WHERE id=?",
                    (setup["id"],),
                )
                return f"已向当前第 {target_stage} 阶段追加 {amount} 名敌人。"
            connection.execute(
                """
                INSERT INTO battle_setup_enemies(
                    setup_id,stage_number,template_key,amount,display_name,source
                ) VALUES(?,?,?,?,?,'MANUAL')
                """, (setup["id"], target_stage, template_key, amount, name)
            )
            connection.execute(
                "UPDATE battle_setups SET revision=revision+1 WHERE id=?",
                (setup["id"],),
            )
            return f"已向第 {target_stage} 阶段编入 {amount} 名敌人。"

    def remove_manual_enemy_from_setup(
        self, setup_enemy_id: int, *, setup_id: int
    ) -> str:
        """移除一条敌方编成记录（2026-07-27 裁定：关卡预设敌人同样可删，删的是本场副本）。"""
        with self.database.transaction() as connection:
            setup = self._preparing_setup(connection, setup_id=int(setup_id))
            enemy = connection.execute(
                """
                SELECT se.*,t.name AS template_name
                FROM battle_setup_enemies se
                JOIN character_templates t ON t.template_key=se.template_key
                WHERE se.id=? AND se.setup_id=?
                """,
                (int(setup_enemy_id), int(setup["id"])),
            ).fetchone()
            if enemy is None:
                raise BattleRuleError("该敌方编成记录不存在或已经被移除。")
            connection.execute(
                "DELETE FROM battle_setup_enemies WHERE id=?", (int(enemy["id"]),)
            )
            connection.execute(
                "UPDATE battle_setups SET revision=revision+1 WHERE id=?",
                (setup["id"],),
            )
            label = enemy["display_name"] or enemy["template_name"]
            return f"已从第 {enemy['stage_number']} 阶段移除 {label} ×{enemy['amount']}。"

    def set_setup_enemy_enabled(
        self, setup_enemy_id: int, enabled: bool, *, setup_id: int
    ) -> str:
        """切换一条敌方编成记录是否携带进战斗（不删除，保留随时切回）。"""
        with self.database.transaction() as connection:
            setup = self._preparing_setup(connection, setup_id=int(setup_id))
            enemy = connection.execute(
                """
                SELECT se.*,t.name AS template_name
                FROM battle_setup_enemies se
                JOIN character_templates t ON t.template_key=se.template_key
                WHERE se.id=? AND se.setup_id=?
                """,
                (int(setup_enemy_id), int(setup["id"])),
            ).fetchone()
            if enemy is None:
                raise BattleRuleError("该敌方编成记录不存在或已经被移除。")
            connection.execute(
                "UPDATE battle_setup_enemies SET enabled=? WHERE id=?",
                (1 if enabled else 0, int(enemy["id"])),
            )
            connection.execute(
                "UPDATE battle_setups SET revision=revision+1 WHERE id=?",
                (setup["id"],),
            )
            label = enemy["display_name"] or enemy["template_name"]
            state = "携带" if enabled else "不携带"
            return f"第 {enemy['stage_number']} 阶段的 {label} ×{enemy['amount']} 已改为{state}。"

    def launch_prepared_battle(
        self, setup_id: int | None = None, *, expected_revision: int | None = None
    ) -> tuple[int, tuple[str, ...]]:
        # Formation, persona application, enemy spawning, battle creation, and
        # setup claiming are one unit of work.  No other admin can cancel or
        # launch this standby record in the middle of the transition.
        with self.database.transaction() as connection:
            setup = self._preparing_setup(connection, setup_id=setup_id)
            setup_id = int(setup["id"])
            if (
                expected_revision is not None
                and int(setup["revision"]) != int(expected_revision)
            ):
                raise BattleRuleError(
                    "确认后战斗编成已经发生变化；本次没有触发，请重新使用 /ready 核对。"
                )
            friendly_rows = connection.execute(
                "SELECT * FROM battle_setup_friendlies WHERE setup_id=? ORDER BY character_id",
                (setup_id,),
            ).fetchall()
            if not friendly_rows:
                raise BattleRuleError("尚未编入任何友方角色。")
            if not any(row["persona_id"] is not None for row in friendly_rows):
                raise BattleRuleError("触发战斗前必须选择至少一名核心角色及其人格。")
            enemy_rows = connection.execute(
                "SELECT * FROM battle_setup_enemies"
                " WHERE setup_id=? AND stage_number=1 AND enabled=1 ORDER BY id",
                (setup_id,),
            ).fetchall()
            if not enemy_rows:
                raise BattleRuleError("第一阶段没有携带中的敌人。")
            total_stages = int(connection.execute(
                "SELECT COUNT(*) FROM battle_setup_stages WHERE setup_id=?",
                (setup_id,),
            ).fetchone()[0])
            friendly_ids = [int(row["character_id"]) for row in friendly_rows]
            persona_choices = [
                (int(row["character_id"]), int(row["persona_id"]))
                for row in friendly_rows if row["persona_id"] is not None
            ]
            enemy_specs = [dict(row) for row in enemy_rows]
            abnormalities = _loads(setup["abnormalities_json"], [])
            for row in friendly_rows:
                character = self._character(connection, int(row["character_id"]))
                if row["persona_id"] is None:
                    if int(character["current_hp"]) <= 0:
                        raise BattleRuleError(
                            f"普通友方 {character['name']} 已无法行动，不能加入战斗。"
                        )
                    template = connection.execute(
                        "SELECT enabled FROM character_templates WHERE template_key=?",
                        (character["template_key"],),
                    ).fetchone()
                    if template is None or not int(template["enabled"]):
                        raise BattleRuleError(
                            f"普通友方 {character['name']} 的单位定义已经停用，不能加入战斗。"
                        )
            for character_id, persona_id in persona_choices:
                persona = connection.execute(
                    "SELECT * FROM personas WHERE id=? AND character_id=? AND enabled=1",
                    (persona_id, character_id),
                ).fetchone()
                if persona is None:
                    raise BattleRuleError("编成中选择的人格已经不可用。")
                connection.execute(
                    """
                    UPDATE characters SET active_persona_id=?,max_hp=?,current_hp=?,
                        max_actions=?,current_actions=?,max_stagger=?,current_stagger=?
                    WHERE id=?
                    """,
                    (persona["id"],persona["max_hp"],persona["max_hp"],
                     persona["max_actions"],persona["max_actions"],
                     persona["max_stagger"],persona["max_stagger"],character_id),
                )
            enemy_ids: list[int] = []
            enemy_origins: list[tuple[int, str | None, int]] = []
            for spec in enemy_specs:
                for _ in range(int(spec["amount"])):
                    character_id = self._spawn_character(
                        connection, spec["template_key"], Faction.ENEMY,
                        name=spec["display_name"],
                    )
                    enemy_ids.append(character_id)
                    enemy_origins.append(
                        (character_id, spec.get("enemy_key"), int(spec["id"]))
                    )
            battle_id, messages = self._start_battle_in_transaction(
                connection,
                friendly_ids, enemy_ids, total_stages=total_stages,
                abnormality_keys=abnormalities,
            )
            for character_id, enemy_key, setup_enemy_id in enemy_origins:
                connection.execute(
                    """
                    INSERT INTO battle_spawn_origins(
                        battle_id,character_id,stage_number,enemy_key,setup_enemy_id
                    ) VALUES(?,?,?,?,?)
                    """, (battle_id,character_id,1,enemy_key,setup_enemy_id)
                )
            connection.execute(
                "UPDATE battles SET name=? WHERE id=?", (setup["name"], battle_id)
            )
            claimed = connection.execute(
                """
                UPDATE battle_setups SET status='ACTIVE',battle_id=?,launched_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='STANDBY'
                """, (battle_id, setup_id)
            )
            if claimed.rowcount != 1:
                raise BattleRuleError("待触发战斗已被其他操作修改，请重新选择。")
            return battle_id, messages

    def start_prepared_stage(
        self, friendly_ids: Iterable[int] | None = None
    ) -> tuple[str, ...]:
        with self.database.transaction() as connection:
            battle = self._active_battle(connection)
            next_stage = int(battle["current_stage"]) + 1
            setup = connection.execute(
                "SELECT * FROM battle_setups WHERE battle_id=? AND status='ACTIVE'",
                (battle["id"],),
            ).fetchone()
            if setup is None:
                raise BattleRuleError("当前战斗不是从关卡容器启动的。")
            specs = [dict(row) for row in connection.execute(
                "SELECT * FROM battle_setup_enemies"
                " WHERE setup_id=? AND stage_number=? AND enabled=1 ORDER BY id",
                (setup["id"], next_stage),
            )]
            candidate_ids = [int(row[0]) for row in connection.execute(
                """
                SELECT character_id FROM battle_participants
                WHERE battle_id=? AND faction='FRIENDLY' AND character_id IN (
                    SELECT id FROM characters WHERE current_hp>0
                ) ORDER BY character_id
                """, (battle["id"],)
            )]
            if friendly_ids is None:
                # 决策补充6：Stage Start 应有选人环节；未提供名单时沿用全部
                # 存活友方（兼容旧调用方），交互层负责提供显式选择。
                selected_friendly_ids = candidate_ids
            else:
                selected_friendly_ids = []
                candidate_set = set(candidate_ids)
                for raw_id in friendly_ids:
                    character_id = int(raw_id)
                    if character_id not in candidate_set:
                        raise BattleRuleError(
                            f"角色编号 {character_id} 不是本战斗的存活友方，无法编入下一阶段。"
                        )
                    if character_id not in selected_friendly_ids:
                        selected_friendly_ids.append(character_id)
            if not specs:
                raise BattleRuleError(f"关卡没有配置第 {next_stage} 阶段的敌人。")
            if not selected_friendly_ids:
                raise BattleRuleError("没有选定任何仍可行动的友方角色，无法进入下一阶段。")
            enemy_ids: list[int] = []
            origins: list[tuple[int, str | None, int]] = []
            for spec in specs:
                for _ in range(int(spec["amount"])):
                    character_id = self._spawn_character(
                        connection,
                        spec["template_key"],
                        Faction.ENEMY,
                        name=spec["display_name"],
                    )
                    enemy_ids.append(character_id)
                    origins.append(
                        (character_id, spec.get("enemy_key"), int(spec["id"]))
                    )
            messages = self._start_stage_in_transaction(
                connection, selected_friendly_ids, enemy_ids
            )
            for character_id, enemy_key, setup_enemy_id in origins:
                connection.execute(
                    """
                    INSERT INTO battle_spawn_origins(
                        battle_id,character_id,stage_number,enemy_key,setup_enemy_id
                    ) VALUES(?,?,?,?,?)
                    """, (battle["id"],character_id,next_stage,enemy_key,setup_enemy_id)
                )
            return messages

    @staticmethod
    def _preparing_setup(
        connection: sqlite3.Connection, *, setup_id: int | None = None,
        user_id: int | None = None, chat_id: int = 0,
        allow_active: bool = False,
    ) -> sqlite3.Row:
        statuses = "('STANDBY','ACTIVE')" if allow_active else "('STANDBY')"
        if setup_id is not None:
            setup = connection.execute(
                f"SELECT * FROM battle_setups WHERE id=? AND status IN {statuses}",
                (setup_id,),
            ).fetchone()
        elif user_id is not None:
            setup = connection.execute(
                """
                SELECT bs.* FROM battle_setup_selections s
                JOIN battle_setups bs ON bs.id=s.setup_id
                WHERE s.user_id=? AND s.chat_id IN (?,0) AND bs.status IN {statuses}
                ORDER BY CASE WHEN s.chat_id=? THEN 0 ELSE 1 END LIMIT 1
                """.format(statuses=statuses),
                (user_id, int(chat_id), int(chat_id)),
            ).fetchone()
        else:
            setup = connection.execute(
                "SELECT * FROM battle_setups WHERE status='STANDBY' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if setup is None:
            if setup_id is not None:
                raise BattleRuleError(
                    "该战斗不存在、已结束或已撤销；使用 /battles 查看可选战斗。"
                )
            raise BattleRuleError(
                "当前没有选中的待触发战斗；请先用 /new <名称> 建立，"
                "或用 /battles 查看后 /use <编号> 选中。"
            )
        return setup

    # ------------------------------------------------------------------
    # Battle lifecycle
    # ------------------------------------------------------------------
    def start_battle(
        self,
        friendly_ids: Iterable[int],
        enemy_ids: Iterable[int],
        *,
        total_stages: int = 1,
        abnormality_keys: Iterable[str] = (),
    ) -> tuple[int, tuple[str, ...]]:
        friendly_ids = list(dict.fromkeys(int(item) for item in friendly_ids))
        enemy_ids = list(dict.fromkeys(int(item) for item in enemy_ids))
        with self.database.transaction() as connection:
            return self._start_battle_in_transaction(
                connection,
                friendly_ids,
                enemy_ids,
                total_stages=total_stages,
                abnormality_keys=list(abnormality_keys),
            )

    def _start_battle_in_transaction(
        self,
        connection: sqlite3.Connection,
        friendly_ids: list[int],
        enemy_ids: list[int],
        *,
        total_stages: int,
        abnormality_keys: Iterable[str],
    ) -> tuple[int, tuple[str, ...]]:
        if not friendly_ids or not enemy_ids:
            raise BattleRuleError("开战至少需要一名我方和一名敌方角色。")
        if total_stages < 1:
            raise BattleRuleError("阶段数量必须至少为1。")
        if connection.execute(
            "SELECT 1 FROM battles WHERE status='ACTIVE'"
        ).fetchone():
            raise BattleRuleError("已有一份战斗记录仍在展开。")
        cursor = connection.execute(
            """
            INSERT INTO battles(total_stages,phase)
            VALUES(?,?)
            """,
            (total_stages, BattlePhase.BATTLE_START.value),
        )
        battle_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO battle_content_versions(battle_id,pack_key,version,checksum)
            SELECT ?,pack_key,version,checksum FROM content_packs
            """,
            (battle_id,),
        )
        self._add_participants(connection, battle_id, friendly_ids, Faction.FRIENDLY, 1)
        self._add_participants(connection, battle_id, enemy_ids, Faction.ENEMY, 1)
        for character_id in friendly_ids + enemy_ids:
            connection.execute(
                """
                UPDATE characters SET current_actions=max_actions,current_stagger=max_stagger,
                    is_staggered=0,stagger_turns=0,emotion_level=0,
                    positive_emotion_coins=0,negative_emotion_coins=0,
                    pending_emotion_upgrade=0,
                    max_actions=max_actions-emotion_bonus_actions,
                    current_actions=MAX(1,max_actions-emotion_bonus_actions),
                    emotion_bonus_actions=0
                WHERE id=?
                """,
                (character_id,),
            )
        carry_messages = self._prepare_abnormality_pool(
            connection, battle_id, list(abnormality_keys)
        )
        messages = [self.narrator.battle_started(battle_id, total_stages)]
        messages.extend(carry_messages)
        messages.extend(self._start_turn(connection, battle_id))
        self._log(
            connection, battle_id, "BATTLE_START", message="\n".join(messages)
        )
        return battle_id, tuple(messages)

    def _add_participants(
        self,
        connection: sqlite3.Connection,
        battle_id: int,
        character_ids: list[int],
        faction: Faction,
        stage: int,
    ) -> None:
        for character_id in character_ids:
            character = self._character(connection, character_id)
            if character["faction"] != faction.value:
                raise BattleRuleError(f"{character['name']} 的阵营与入战位置不一致。")
            if character["current_hp"] <= 0:
                raise BattleRuleError(f"{character['name']} 已无法行动，不能加入战斗。")
            connection.execute(
                """
                INSERT INTO battle_participants(
                    battle_id,character_id,faction,active_in_stage,stage_joined
                ) VALUES(?,?,?,?,?)
                ON CONFLICT(battle_id,character_id) DO UPDATE SET
                    faction=excluded.faction,active_in_stage=1,stage_joined=excluded.stage_joined
                """,
                (battle_id, character_id, faction.value, 1, stage),
            )

    def start_stage(
        self,
        friendly_ids: Iterable[int],
        enemy_ids: Iterable[int],
    ) -> tuple[str, ...]:
        friendly_ids = list(dict.fromkeys(int(item) for item in friendly_ids))
        enemy_ids = list(dict.fromkeys(int(item) for item in enemy_ids))
        with self.database.transaction() as connection:
            return self._start_stage_in_transaction(
                connection, friendly_ids, enemy_ids
            )

    def _start_stage_in_transaction(
        self,
        connection: sqlite3.Connection,
        friendly_ids: list[int],
        enemy_ids: list[int],
    ) -> tuple[str, ...]:
        if not friendly_ids or not enemy_ids:
            raise BattleRuleError("阶段开始至少需要一名我方和一名敌方角色。")
        battle = self._active_battle(connection)
        if BattlePhase(battle["phase"]) != BattlePhase.STAGE_END:
            raise BattleRuleError("当前不在阶段选择窗口。")
        next_stage = int(battle["current_stage"]) + 1
        if next_stage > int(battle["total_stages"]):
            raise BattleRuleError("没有尚未展开的后续阶段。")
        connection.execute(
            "UPDATE battle_participants SET active_in_stage=0 WHERE battle_id=?",
            (battle["id"],),
        )
        self._add_participants(
            connection, battle["id"], friendly_ids, Faction.FRIENDLY, next_stage
        )
        self._add_participants(
            connection, battle["id"], enemy_ids, Faction.ENEMY, next_stage
        )
        connection.execute(
            "UPDATE battles SET current_stage=?,phase=? WHERE id=?",
            (next_stage, BattlePhase.TURN_START.value, battle["id"]),
        )
        messages = [f"【第 {next_stage} 阶段开始】"]
        messages.extend(self._start_turn(connection, battle["id"]))
        self._log(
            connection,
            int(battle["id"]),
            "STAGE_START",
            payload={"stage": next_stage},
            message="\n".join(messages),  # 完整入库：升级/候选播报不能只活在实时流里
        )
        return tuple(messages)

    def end_friendly_phase(self) -> str:
        with self.database.transaction() as connection:
            battle = self._active_battle(connection)
            if BattlePhase(battle["phase"]) != BattlePhase.FRIENDLY_ACTION:
                raise BattleRuleError("当前并非我方行动阶段。")
            connection.execute(
                "UPDATE battles SET phase=? WHERE id=?",
                (BattlePhase.ENEMY_ACTION.value, battle["id"]),
            )
            message = self.narrator.phase_changed(BattlePhase.ENEMY_ACTION)
            self._log(connection, battle["id"], "PHASE_CHANGE", message=message)
            return message

    def end_turn(self) -> tuple[str, ...]:
        with self.database.transaction() as connection:
            battle = self._active_battle(connection)
            battle_id = int(battle["id"])
            if BattlePhase(battle["phase"]) != BattlePhase.ENEMY_ACTION:
                raise BattleRuleError("敌方行动尚未结束，不能进行回合清算。")
            return tuple(self._settle_turn(connection, battle_id))

    def _settle_turn(
        self, connection: sqlite3.Connection, battle_id: int
    ) -> list[str]:
        """回合清算主体：TURN_END 处理 → 状态清理 → 结算/开新回合。"""
        if battle_id:
            connection.execute(
                "UPDATE battles SET phase=? WHERE id=?",
                (BattlePhase.TURN_END.value, battle_id),
            )
            messages = [self.narrator.phase_changed(BattlePhase.TURN_END)]
            messages.extend(
                self._dispatch_hooks(
                    connection,
                    battle_id,
                    BattleEvent.TURN_END,
                    event_actor_id=None,
                    event_target_ids=[],
                    snapshot=None,
                )
            )
            messages.extend(self._execute_registered(connection, battle_id, Timing.TURN_END))
            self._age_registered_behaviors(connection, battle_id)
            messages.extend(self._process_turn_end_effects(connection, battle_id))
            connection.execute(
                "DELETE FROM active_effects WHERE battle_id=? AND category='GENERIC'",
                (battle_id,),
            )
            self._process_stagger_and_actions(connection, battle_id, messages)
            connection.execute(
                """
                UPDATE battle_skill_cooldowns SET remaining=MAX(0,remaining-1)
                WHERE battle_id=? AND skill_id IN (
                    SELECT id FROM skills WHERE skill_type='NORMAL'
                )
                """,
                (battle_id,),
            )
            connection.execute(
                "DELETE FROM battle_skill_cooldowns WHERE battle_id=? AND remaining=0",
                (battle_id,),
            )

            resolved, outcome_messages = self._resolve_battle_state(
                connection, battle_id
            )
            messages.extend(outcome_messages)
            if not resolved:
                messages.extend(self._start_turn(connection, battle_id))
            self._log(connection, battle_id, "TURN_END", message="\n".join(messages))
            return messages
        return []

    def _auto_advance_phase(
        self, connection: sqlite3.Connection, battle_id: int
    ) -> list[str]:
        """行动次数耗尽自动推进（2026-07-27 裁定）。

        我方全部（含核心）无行动 → 自动移交敌方阶段；
        敌方全部无行动 → 自动回合清算并开启下一回合。
        """
        battle = connection.execute(
            "SELECT * FROM battles WHERE id=? AND status='ACTIVE'", (battle_id,)
        ).fetchone()
        if battle is None:
            return []

        def _has_actions(faction: str) -> bool:
            return connection.execute(
                """
                SELECT 1 FROM characters c
                JOIN battle_participants bp ON bp.character_id=c.id
                WHERE bp.battle_id=? AND bp.active_in_stage=1 AND c.faction=?
                  AND c.current_hp>0 AND c.is_staggered=0 AND c.current_actions>0
                LIMIT 1
                """,
                (battle_id, faction),
            ).fetchone() is not None

        messages: list[str] = []
        phase = BattlePhase(battle["phase"])
        if phase == BattlePhase.FRIENDLY_ACTION and not _has_actions("FRIENDLY"):
            connection.execute(
                "UPDATE battles SET phase=? WHERE id=?",
                (BattlePhase.ENEMY_ACTION.value, battle_id),
            )
            message = self.narrator.phase_changed(BattlePhase.ENEMY_ACTION)
            self._log(connection, battle_id, "PHASE_CHANGE", message=message)
            messages.append(message)
            phase = BattlePhase.ENEMY_ACTION
        if phase == BattlePhase.ENEMY_ACTION and not _has_actions("ENEMY"):
            messages.extend(self._settle_turn(connection, battle_id))
        return messages

    def _stage_clear_outcome(
        self, connection: sqlite3.Connection, battle: sqlite3.Row
    ) -> str | None:
        stage = connection.execute(
            """
            SELECT ss.clear_condition_json,ss.clear_outcome
            FROM battle_setups bs
            JOIN battle_setup_stages ss ON ss.setup_id=bs.id
                AND ss.stage_number=?
            WHERE bs.battle_id=? AND bs.status='ACTIVE'
            """, (battle["current_stage"], battle["id"])
        ).fetchone()
        if stage is None:
            return None
        condition = _loads(stage["clear_condition_json"], {})
        condition_type = str(condition.get("type", "ALL_ENEMIES_DEFEATED")).upper()
        satisfied = False
        if condition_type == "ALL_ENEMIES_DEFEATED":
            satisfied = self._living_count(
                connection, int(battle["id"]), Faction.ENEMY
            ) == 0
        else:
            targets = connection.execute(
                """
                SELECT c.current_hp,c.max_hp FROM battle_spawn_origins o
                JOIN characters c ON c.id=o.character_id
                WHERE o.battle_id=? AND o.stage_number=? AND o.enemy_key=?
                """,
                (battle["id"], battle["current_stage"], condition.get("target")),
            ).fetchall()
            if condition_type == "TARGET_DEFEATED":
                satisfied = bool(targets) and all(int(row["current_hp"]) <= 0 for row in targets)
            elif condition_type == "TARGET_HP_BELOW":
                ratio = float(condition.get("ratio", 0.5))
                satisfied = bool(targets) and any(
                    int(row["current_hp"]) / max(1, int(row["max_hp"])) <= ratio
                    for row in targets
                )
        if not satisfied:
            return ""
        outcome = str(stage["clear_outcome"])
        if (
            outcome == "NEXT_STAGE"
            and int(battle["current_stage"]) >= int(battle["total_stages"])
        ):
            # A malformed last-stage configuration must not strand an ACTIVE
            # battle in STAGE_END with no legal next stage.
            return "VICTORY"
        return outcome

    def _resolve_battle_state(
        self, connection: sqlite3.Connection, battle_id: int
    ) -> tuple[bool, list[str]]:
        """Resolve defeat/stage completion after any behavior window.

        Damage and special handlers may run from skills, turn hooks, pending
        effects, or registered behavior windows.  Every such window must reach
        the same terminal-state decision before the phase is advanced.
        """
        battle = connection.execute(
            "SELECT * FROM battles WHERE id=? AND status='ACTIVE'",
            (int(battle_id),),
        ).fetchone()
        if battle is None:
            return True, []
        if self._living_count(connection, battle_id, Faction.FRIENDLY) == 0:
            return True, self._finish_battle(connection, battle_id, "DEFEAT")
        resolution = self._stage_clear_outcome(connection, battle)
        if resolution == "NEXT_STAGE":
            return True, self._finish_stage(connection, battle_id)
        if resolution == "VICTORY":
            return True, self._finish_battle(connection, battle_id, "VICTORY")
        if (
            resolution is None
            and self._living_count(connection, battle_id, Faction.ENEMY) == 0
        ):
            # Compatibility for battles created without an encounter container.
            if int(battle["current_stage"]) < int(battle["total_stages"]):
                return True, self._finish_stage(connection, battle_id)
            return True, self._finish_battle(connection, battle_id, "VICTORY")
        return False, []

    def end_battle(self, result: str = "ABORTED") -> tuple[str, ...]:
        with self.database.transaction() as connection:
            battle = self._active_battle(connection)
            return tuple(self._finish_battle(connection, int(battle["id"]), result))

    def _finish_stage(self, connection: sqlite3.Connection, battle_id: int) -> list[str]:
        connection.execute(
            "UPDATE battles SET phase=? WHERE id=?",
            (BattlePhase.STAGE_END.value, battle_id),
        )
        effects = connection.execute(
            "SELECT id,category,params_json FROM active_effects WHERE battle_id=?",
            (battle_id,),
        ).fetchall()
        for effect in effects:
            params = _loads(effect["params_json"], {})
            if effect["category"] == EffectCategory.SPECIAL.value and params.get("lifecycle_scope") == "BATTLE":
                continue
            connection.execute("DELETE FROM active_effects WHERE id=?", (effect["id"],))
        connection.execute("DELETE FROM battle_pending_effects WHERE battle_id=?", (battle_id,))
        connection.execute(
            "DELETE FROM battle_registered_behaviors WHERE battle_id=? AND lifecycle_scope!='BATTLE'",
            (battle_id,),
        )
        connection.execute(
            "UPDATE battle_participants SET active_in_stage=0 WHERE battle_id=?",
            (battle_id,),
        )
        participants = connection.execute(
            "SELECT character_id FROM battle_participants WHERE battle_id=?", (battle_id,)
        ).fetchall()
        for row in participants:
            connection.execute(
                """
                UPDATE characters SET current_stagger=max_stagger,is_staggered=0,
                    stagger_turns=0,current_actions=max_actions WHERE id=?
                """,
                (row["character_id"],),
            )
        # 流程提示不进播报（2026-07-27 反馈）：GM 操作条自有「进入下一阶段」按钮。
        message = self.narrator.phase_changed(BattlePhase.STAGE_END)
        self._log(connection, battle_id, "STAGE_END", message=message)
        return [message]

    def _finish_battle(
        self, connection: sqlite3.Connection, battle_id: int, result: str
    ) -> list[str]:
        participants = connection.execute(
            "SELECT character_id FROM battle_participants WHERE battle_id=?", (battle_id,)
        ).fetchall()
        for row in participants:
            connection.execute(
                """
                UPDATE characters SET
                    max_actions=MAX(1,max_actions-emotion_bonus_actions),
                    current_actions=MAX(1,max_actions-emotion_bonus_actions),
                    emotion_bonus_actions=0,emotion_level=0,
                    positive_emotion_coins=0,negative_emotion_coins=0,
                    pending_emotion_upgrade=0,current_stagger=max_stagger,
                    is_staggered=0,stagger_turns=0
                WHERE id=?
                """,
                (row["character_id"],),
            )
        connection.execute(
            """
            UPDATE battles SET status='COMPLETE',phase=?,result=?,ended_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (BattlePhase.BATTLE_END.value, result, battle_id),
        )
        connection.execute(
            "UPDATE battle_setups SET status='COMPLETE' WHERE battle_id=?",
            (battle_id,),
        )
        for table in (
            "active_effects",
            "battle_pending_effects",
            "battle_registered_behaviors",
            "battle_skill_cooldowns",
            "battle_skill_usage",
            "battle_ego_usage",
            "battle_page_offers",
            "battle_active_pages",
            "battle_page_pool",
            "battle_abnormalities",
            "manager_skill_usage",
        ):
            connection.execute(f"DELETE FROM {table} WHERE battle_id=?", (battle_id,))
        label = {"VICTORY": "胜利", "DEFEAT": "战败", "ABORTED": "中止"}.get(
            result, result
        )
        message = f"{self.narrator.phase_changed(BattlePhase.BATTLE_END)}\n结果：{label}"
        self._log(
            connection,
            battle_id,
            "BATTLE_END",
            payload={"result": result},
            message=message,
        )
        return [message]

    # ------------------------------------------------------------------
    # Skills and targeting
    # ------------------------------------------------------------------
    def list_skills(self, character_id: int, *, available_only: bool = False) -> list[dict[str, Any]]:
        with self.database.reading() as connection:
            battle = self._active_battle(connection)
            character = self._character(connection, character_id)
            rows = self._character_skill_rows(connection, character)
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["cooldown_remaining"] = self._cooldown(
                    connection, battle["id"], character_id, row["id"]
                )
                item["ego_used"] = self._ego_used(connection, battle["id"], character_id)
                item["uses_this_battle"] = self._skill_uses(
                    connection, battle["id"], character_id, row["id"]
                )
                max_uses = row["max_uses_per_battle"]
                item["available"] = (
                    item["cooldown_remaining"] == 0
                    and int(character["emotion_level"]) >= int(row["emotion_requirement"])
                    and not (row["skill_type"] == SkillType.EGO.value and item["ego_used"])
                    and (max_uses is None or item["uses_this_battle"] < int(max_uses))
                )
                if not available_only or item["available"]:
                    result.append(item)
            return result

    def legal_targets(self, character_id: int, skill_id: int) -> list[dict[str, Any]]:
        with self.database.reading() as connection:
            battle = self._active_battle(connection)
            actor = self._character(connection, character_id)
            skill = self._ensure_skill_owned(connection, actor, skill_id)
            return [
                dict(row)
                for row in self._target_pool(
                    connection, battle["id"], actor, TargetScope(skill["target_scope"])
                )
            ]

    def use_skill(
        self,
        character_id: int,
        skill_id: int,
        selected_target_ids: Iterable[int] | None = None,
    ) -> ActionResult:
        with self.database.transaction() as connection:
            return self._use_skill(
                connection,
                character_id,
                skill_id,
                list(selected_target_ids or []),
                consume_action=True,
                recursion_depth=0,
            )

    def _use_skill(
        self,
        connection: sqlite3.Connection,
        character_id: int,
        skill_id: int,
        selected_target_ids: list[int],
        *,
        consume_action: bool,
        recursion_depth: int,
        enforce_action_rules: bool = True,
        award_emotion: bool = True,
    ) -> ActionResult:
        if recursion_depth > 5:
            raise BattleRuleError("技能调用链超过安全深度。")
        battle = self._active_battle(connection)
        battle_id = int(battle["id"])
        actor = self._character(connection, character_id)
        participant = connection.execute(
            """
            SELECT * FROM battle_participants
            WHERE battle_id=? AND character_id=? AND active_in_stage=1
            """,
            (battle_id, character_id),
        ).fetchone()
        if participant is None:
            raise BattleRuleError("该角色不在当前阶段。")
        required_phase = (
            BattlePhase.FRIENDLY_ACTION
            if actor["faction"] == Faction.FRIENDLY.value
            else BattlePhase.ENEMY_ACTION
        )
        if enforce_action_rules and BattlePhase(battle["phase"]) != required_phase:
            raise BattleRuleError("行动阶段与角色阵营不一致。")
        if actor["current_hp"] <= 0:
            raise BattleRuleError("该角色已无法继续行动。")
        if enforce_action_rules and actor["is_staggered"]:
            raise BattleRuleError("该角色正处于混乱，行动已被封锁。")
        if consume_action and actor["current_actions"] <= 0:
            raise BattleRuleError("该角色本回合已无行动次数。")
        # 回合内行动顺序：助战（非核心友方）先于玩家核心；敌方阶段不受影响。
        if (
            enforce_action_rules
            and consume_action
            and actor["faction"] == Faction.FRIENDLY.value
            and int(actor["is_core"]) == 1
        ):
            waiting = connection.execute(
                """
                SELECT c.name FROM characters c
                JOIN battle_participants bp ON bp.character_id=c.id
                WHERE bp.battle_id=? AND bp.active_in_stage=1
                  AND c.faction='FRIENDLY' AND c.is_core=0
                  AND c.current_hp>0 AND c.is_staggered=0 AND c.current_actions>0
                ORDER BY c.id LIMIT 1
                """,
                (battle_id,),
            ).fetchone()
            if waiting is not None:
                raise BattleRuleError(
                    f"行动顺序为「助战 → 玩家 → 敌方」：{waiting['name']} 等助战单位"
                    "尚有行动次数。管理人可先操作助战，或使用「助战让行」跳过。"
                )

        skill = self._ensure_skill_owned(connection, actor, skill_id)
        if int(actor["emotion_level"]) < int(skill["emotion_requirement"]):
            raise BattleRuleError(f"情感等级不足，需要等级 {skill['emotion_requirement']}。")
        if skill["skill_type"] == SkillType.EGO.value:
            if self._ego_used(connection, battle_id, character_id):
                raise BattleRuleError("该角色本场战斗已经展开过 E.G.O。")
            # Reserve before executing any behavior. The enclosing transaction
            # rolls this back on failure, while recursive invoke_skill handlers
            # can no longer enter a second E.G.O before the outer one returns.
            connection.execute(
                """
                INSERT INTO battle_ego_usage(battle_id,character_id,ego_used,used_skill_id,used_at)
                VALUES(?,?,1,?,CURRENT_TIMESTAMP)
                ON CONFLICT(battle_id,character_id) DO UPDATE SET
                    ego_used=1,used_skill_id=excluded.used_skill_id,used_at=CURRENT_TIMESTAMP
                """,
                (battle_id, character_id, skill_id),
            )
        elif self._cooldown(connection, battle_id, character_id, skill_id) > 0:
            raise BattleRuleError("技能仍处于冷却记录中。")
        max_uses = skill["max_uses_per_battle"]
        if max_uses is not None:
            used = self._skill_uses(connection, battle_id, character_id, skill_id)
            if used >= int(max_uses):
                raise BattleRuleError("该技能本场战斗的使用次数已经耗尽。")
            connection.execute(
                """
                INSERT INTO battle_skill_usage(battle_id,character_id,skill_id,uses)
                VALUES(?,?,?,1)
                ON CONFLICT(battle_id,character_id,skill_id)
                DO UPDATE SET uses=uses+1
                """,
                (battle_id, character_id, skill_id),
            )
        if skill["skill_type"] == SkillType.NORMAL.value and int(skill["base_cooldown"]) > 0:
            connection.execute(
                """
                INSERT INTO battle_skill_cooldowns(battle_id,character_id,skill_id,remaining)
                VALUES(?,?,?,?)
                ON CONFLICT(battle_id,character_id,skill_id) DO UPDATE SET
                    remaining=excluded.remaining
                """,
                (battle_id, character_id, skill_id, int(skill["base_cooldown"])),
            )

        skill_targets = self._resolve_skill_targets(
            connection, battle_id, actor, skill, selected_target_ids
        )
        snapshot = BattleEventSnapshot(
            battle_id=battle_id,
            actor_id=character_id,
            skill_id=skill_id,
            skill_target_ids=[int(row["id"]) for row in skill_targets],
        )
        snapshot.metadata.update(
            damage_total=0,
            healing_total=0,
            positive_coins=0,
            negative_coins=0,
            skill_key=skill["skill_key"],
            skill_name=skill["name"],
            pack_key=skill["pack_key"],
        )
        messages = [
            self.narrator.skill(
                actor["name"], skill["name"], skill["skill_type"] == SkillType.EGO.value
            )
        ]
        snapshot.messages = messages
        behaviors = connection.execute(
            """
            SELECT * FROM skill_behaviors
            WHERE skill_id=? AND enabled=1
            ORDER BY CASE timing WHEN 'PRE' THEN 1 WHEN 'ON' THEN 2 WHEN 'POST' THEN 3 ELSE 4 END,
                     sort_order,id
            """,
            (skill_id,),
        ).fetchall()
        snapshot.metadata["behavior_keys"] = [row["behavior_key"] for row in behaviors]
        for timing in (Timing.PRE, Timing.ON, Timing.POST):
            for behavior in behaviors:
                if behavior["timing"] == timing.value:
                    self._execute_behavior(
                        connection,
                        battle,
                        actor,
                        behavior,
                        skill_targets,
                        snapshot,
                        recursion_depth=recursion_depth,
                    )

        self._register_deferred_skill_behaviors(
            connection, battle_id, actor, skill, behaviors, snapshot.skill_target_ids
        )
        if consume_action:
            connection.execute(
                "UPDATE characters SET current_actions=MAX(0,current_actions-1) WHERE id=?",
                (character_id,),
            )
            self._process_bleeding_after_action(connection, battle_id, character_id, messages)
            self._dispatch_hooks(
                connection,
                battle_id,
                BattleEvent.ACTION_END,
                event_actor_id=character_id,
                event_target_ids=snapshot.skill_target_ids,
                snapshot=snapshot,
                messages=messages,
                recursion_depth=recursion_depth,
            )
        if award_emotion:
            self._award_emotion_for_action(connection, actor, snapshot)
            self._award_emotion_for_defense(connection, snapshot)
        if recursion_depth == 0:
            _resolved, outcome_messages = self._resolve_battle_state(
                connection, battle_id
            )
            messages.extend(outcome_messages)
        self._log(
            connection,
            battle_id,
            "SKILL",
            actor_id=character_id,
            skill_id=skill_id,
            payload={"snapshot": asdict(snapshot)},
            message="\n".join(messages),
        )
        # 行动次数耗尽自动推进阶段/回合（自身有独立日志，不并入 SKILL 记录）。
        if recursion_depth == 0 and consume_action:
            messages.extend(self._auto_advance_phase(connection, battle_id))
        return ActionResult(
            battle_id=battle_id,
            actor_id=character_id,
            skill_id=skill_id,
            messages=tuple(messages),
            phase=BattlePhase(
                connection.execute("SELECT phase FROM battles WHERE id=?", (battle_id,)).fetchone()[0]
            ),
        )

    def _execute_behavior(
        self,
        connection: sqlite3.Connection,
        battle: sqlite3.Row,
        actor: sqlite3.Row,
        behavior: sqlite3.Row,
        skill_targets: list[sqlite3.Row],
        snapshot: BattleEventSnapshot,
        *,
        recursion_depth: int,
    ) -> None:
        repetitions = self._condition_repetitions(actor, behavior, snapshot)
        if repetitions is None:
            return
        for condition_target_id in repetitions:
            targets = self._resolve_behavior_targets(
                connection,
                battle["id"],
                actor,
                behavior,
                skill_targets,
                condition_target_id,
            )
            effect_type = behavior["effect_type"]
            params = _loads(behavior["effect_params_json"], {})
            if effect_type == "SPECIAL":
                handler_key = behavior["effect_value"] or params.get("handler")
                if not handler_key:
                    raise BattleRuleError(f"行为 {behavior['behavior_key']} 未指定特殊处理器。")
                self.registry.execute(
                    handler_key,
                    EffectExecutionContext(
                        engine=self,
                        connection=connection,
                        battle_id=battle["id"],
                        actor_id=actor["id"],
                        target_ids=[int(item["id"]) for item in targets],
                        params=params,
                        snapshot=snapshot,
                        messages=snapshot.messages,
                        recursion_depth=recursion_depth,
                    ),
                )
                continue
            for hit_index, target in enumerate(targets, start=1):
                if effect_type == "DAMAGE":
                    self._deal_damage(
                        connection,
                        battle,
                        actor,
                        target,
                        behavior,
                        params,
                        snapshot,
                        hit_index,
                        recursion_depth,
                    )
                elif effect_type == "HEAL":
                    self._heal(connection, actor, target, behavior, snapshot)
                elif effect_type == "APPLY_EFFECT":
                    self._apply_effect(
                        connection,
                        battle["id"],
                        actor,
                        target,
                        behavior["effect_key"],
                        params,
                        snapshot,
                    )

    def _condition_repetitions(
        self,
        actor: sqlite3.Row,
        behavior: sqlite3.Row,
        snapshot: BattleEventSnapshot,
    ) -> list[int | None] | None:
        condition = TriggerCondition(behavior["trigger_condition"])
        scope = TriggerScope(behavior["trigger_scope"])
        if condition == TriggerCondition.ALWAYS:
            return [None]
        hits = snapshot.hits
        matching_ids: list[int] = []
        if condition == TriggerCondition.ON_HIT:
            matching_ids = [hit.target_id for hit in hits if hit.hit]
        elif condition in {TriggerCondition.ON_CRIT_HIT, TriggerCondition.ON_CRIT_TRIGGER}:
            matching_ids = [hit.target_id for hit in hits if hit.hit and hit.critical]
        elif condition == TriggerCondition.ON_KILL:
            matching_ids = list(snapshot.killed_character_ids)
        elif condition == TriggerCondition.ON_CRIT_KILL:
            matching_ids = [hit.target_id for hit in hits if hit.critical and hit.killed]
        elif condition == TriggerCondition.ON_KILL_SELECTED_TARGET:
            matching_ids = [
                target_id
                for target_id in snapshot.killed_character_ids
                if target_id in snapshot.skill_target_ids
            ]
        elif condition == TriggerCondition.ON_NO_KILL_SELECTED_TARGET:
            matching_ids = [
                target_id
                for target_id in snapshot.skill_target_ids
                if target_id not in snapshot.killed_character_ids
            ]
            if scope == TriggerScope.PER_SKILL and len(matching_ids) != len(snapshot.skill_target_ids):
                return None
        elif condition in {TriggerCondition.ON_KILL_ALLY, TriggerCondition.ON_KILL_ENEMY}:
            actor_faction = Faction(actor["faction"])
            wanted = actor_faction if condition == TriggerCondition.ON_KILL_ALLY else (
                Faction.ENEMY if actor_faction == Faction.FRIENDLY else Faction.FRIENDLY
            )
            matching_ids = [
                hit.target_id
                for hit in hits
                if hit.killed and hit.target_faction == wanted
            ]
        if not matching_ids:
            return None
        if scope == TriggerScope.PER_SKILL:
            return [None]
        if scope == TriggerScope.PER_TARGET:
            return list(dict.fromkeys(int(item) for item in matching_ids))
        return [int(item) for item in matching_ids]

    # ------------------------------------------------------------------
    # Damage, healing and effects
    # ------------------------------------------------------------------
    def _deal_damage(
        self,
        connection: sqlite3.Connection,
        battle: sqlite3.Row,
        actor: sqlite3.Row,
        target: sqlite3.Row,
        behavior: sqlite3.Row,
        params: dict[str, Any],
        snapshot: BattleEventSnapshot,
        hit_index: int,
        recursion_depth: int,
    ) -> None:
        target = self._character(connection, int(target["id"]))
        damage_context = {
            "target_id": int(target["id"]),
            "behavior_id": int(behavior["id"]),
            "flat_bonus": 0,
            "multiplier": float(
                snapshot.metadata.pop("pending_damage_multiplier", 1.0)
            ),
            "labels": list(snapshot.metadata.pop("pending_damage_labels", [])),
        }
        snapshot.metadata["damage_context"] = damage_context
        self._dispatch_hooks(
            connection,
            int(battle["id"]),
            BattleEvent.BEFORE_DAMAGE,
            event_actor_id=int(actor["id"]),
            event_target_ids=[int(target["id"])],
            snapshot=snapshot,
            messages=snapshot.messages,
            recursion_depth=recursion_depth,
        )
        target = self._character(connection, int(target["id"]))
        if int(target["current_hp"]) <= 0:
            snapshot.messages.append(
                f"└ {target['name']} 已在此段伤害前倒下，伤害不再生效。"
            )
            return
        paralysis = self._active_effect(
            connection, battle["id"], actor["id"], "status.paralysis"
        )
        zero_dice = int(paralysis["intensity"]) if paralysis else 0
        roll = roll_formula(behavior["effect_value"] or "0", rng=self.rng, zero_dice=zero_dice)
        zeroed = sum(1 for value, _faces in roll.dice if value == 0)
        if paralysis and zeroed:
            remaining = max(0, int(paralysis["intensity"]) - zeroed)
            if remaining:
                connection.execute(
                    "UPDATE active_effects SET intensity=? WHERE id=?",
                    (remaining, paralysis["id"]),
                )
            else:
                connection.execute("DELETE FROM active_effects WHERE id=?", (paralysis["id"],))

        flat_bonus = int(damage_context.get("flat_bonus", 0))
        base = max(0, roll.total + flat_bonus)
        strength = self._effect_intensity(connection, battle["id"], actor["id"], "status.strength")
        weakness = self._effect_intensity(connection, battle["id"], actor["id"], "status.weakness")
        guard = self._effect_intensity(connection, battle["id"], target["id"], "status.guard")
        vulnerable = self._effect_intensity(
            connection, battle["id"], target["id"], "status.vulnerable"
        )
        # 精简的成因标注：只列实际生效的修正项（2026-07-27 反馈）。
        modifier_parts: list[str] = []
        context_labels = [str(item) for item in damage_context.get("labels", []) if str(item)]
        if flat_bonus:
            modifier_parts.append(
                ("、".join(context_labels) + f"+{flat_bonus}") if context_labels
                else f"额外+{flat_bonus}"
            )
        if strength:
            modifier_parts.append(f"强壮+{strength * 10}%")
        if weakness:
            modifier_parts.append(f"虚弱-{weakness * 10}%")
        if guard:
            modifier_parts.append(f"守护-{guard * 10}%")
        if vulnerable:
            modifier_parts.append(f"易伤+{vulnerable * 10}%")
        multiplier = max(0.0, 1 + 0.1 * (strength - weakness - guard + vulnerable))
        context_multiplier = max(0.0, float(damage_context.get("multiplier", 1.0)))
        if context_multiplier != 1.0:
            # 写实标注：如「消耗3点硬血×2」；无来源标签时退化为通用写法。
            prefix = "、".join(context_labels) if context_labels else "条件加成"
            modifier_parts.append(f"{prefix}×{context_multiplier:g}")
        multiplier *= context_multiplier
        snapshot.metadata.pop("damage_context", None)
        if target["is_staggered"]:
            multiplier *= 2
            modifier_parts.append("混乱×2")
        breathing = self._effect_intensity(
            connection, battle["id"], actor["id"], "status.breathing"
        )
        critical = breathing > 0 and self.rng.random() * 100 < breathing
        if critical:
            multiplier *= 1.2
            modifier_parts.append("暴击×1.2")
        damage = max(0, int(math.floor(base * multiplier)))
        shield = self._active_effect(
            connection, battle["id"], target["id"], "status.shield"
        )
        if shield and damage:
            absorbed = min(damage, int(shield["intensity"]))
            damage -= absorbed
            modifier_parts.append(f"护盾-{absorbed}")
            shield_remaining = int(shield["intensity"]) - absorbed
            if shield_remaining:
                connection.execute(
                    "UPDATE active_effects SET intensity=? WHERE id=?",
                    (shield_remaining, shield["id"]),
                )
            else:
                connection.execute("DELETE FROM active_effects WHERE id=?", (shield["id"],))

        old_hp = int(target["current_hp"])
        new_hp = max(0, old_hp - damage)
        connection.execute("UPDATE characters SET current_hp=? WHERE id=?", (new_hp, target["id"]))
        staggered_now = False
        if damage > 0 and not target["is_staggered"] and new_hp > 0:
            next_stagger = int(target["current_stagger"]) - damage
            if next_stagger <= 0:
                staggered_now = True
                connection.execute(
                    """
                    UPDATE characters SET current_stagger=max_stagger,is_staggered=1,
                        stagger_turns=2,current_actions=0 WHERE id=?
                    """,
                    (target["id"],),
                )
            else:
                connection.execute(
                    "UPDATE characters SET current_stagger=? WHERE id=?",
                    (next_stagger, target["id"]),
                )

        snapshot.messages.append(
            self.narrator.damage(
                target["name"], roll.expression, roll.detail, damage, critical,
                "｜".join(modifier_parts),
            )
        )
        if staggered_now:
            snapshot.messages.append(self.narrator.staggered(target["name"]))

        rupture = self._active_effect(
            connection, battle["id"], target["id"], "status.rupture"
        )
        hit = HitSnapshot(
            behavior_id=int(behavior["id"]),
            hit_index=hit_index,
            target_id=int(target["id"]),
            hit=True,
            critical=critical,
            damage=damage,
            killed=False,
            target_faction=Faction(target["faction"]),
            damage_source="SKILL",
            source_key=str(behavior["behavior_key"]),
            source_character_id=int(actor["id"]),
        )
        snapshot.hits.append(hit)
        snapshot.metadata["damage_total"] += damage
        snapshot.metadata["positive_coins"] += roll.positive_coins
        snapshot.metadata["negative_coins"] += roll.negative_coins
        events = [BattleEvent.HIT]
        if critical:
            events.append(BattleEvent.CRIT)
        events.append(BattleEvent.AFTER_DAMAGE)
        for event in events:
            self._dispatch_hooks(
                connection,
                int(battle["id"]),
                event,
                event_actor_id=int(actor["id"]),
                event_target_ids=[int(target["id"])],
                snapshot=snapshot,
                messages=snapshot.messages,
                recursion_depth=recursion_depth,
            )
        final_target = self._character(connection, int(target["id"]))
        killed = old_hp > 0 and int(final_target["current_hp"]) <= 0
        hit.killed = killed
        if killed:
            hit.killer_id = int(actor["id"])
            if target["id"] not in snapshot.killed_character_ids:
                snapshot.killed_character_ids.append(int(target["id"]))
            snapshot.messages.append(self.narrator.defeated(target["name"]))
            self._dispatch_hooks(
                connection,
                int(battle["id"]),
                BattleEvent.KILL,
                event_actor_id=int(actor["id"]),
                event_target_ids=[int(target["id"])],
                snapshot=snapshot,
                messages=snapshot.messages,
                recursion_depth=recursion_depth,
            )
        if rupture:
            current_target = self._character(connection, int(target["id"]))
            if int(current_target["current_hp"]) > 0:
                self._deal_status_damage(
                    connection,
                    int(battle["id"]),
                    rupture,
                    int(rupture["intensity"]),
                    snapshot.messages,
                    "破裂",
                    recursion_depth=recursion_depth,
                )
            self._consume_regular_stack(connection, rupture)

    def _heal(
        self,
        connection: sqlite3.Connection,
        actor: sqlite3.Row,
        target: sqlite3.Row,
        behavior: sqlite3.Row,
        snapshot: BattleEventSnapshot,
    ) -> None:
        target = self._character(connection, int(target["id"]))
        if int(target["current_hp"]) <= 0:
            snapshot.messages.append(
                f"└ {target['name']} 已在治疗生效前倒下，治疗无效。"
            )
            return
        roll = roll_formula(behavior["effect_value"] or "0", rng=self.rng)
        amount = max(0, min(roll.total, int(target["max_hp"]) - int(target["current_hp"])))
        connection.execute(
            "UPDATE characters SET current_hp=current_hp+? WHERE id=?", (amount, target["id"])
        )
        snapshot.hits.append(
            HitSnapshot(
                behavior_id=int(behavior["id"]),
                hit_index=1,
                target_id=int(target["id"]),
                hit=False,
                healing=amount,
                target_faction=Faction(target["faction"]),
                damage_source="SKILL",
                source_key=str(behavior["behavior_key"]),
                source_character_id=int(actor["id"]),
            )
        )
        snapshot.metadata["healing_total"] += amount
        snapshot.metadata["positive_coins"] += roll.positive_coins
        snapshot.metadata["negative_coins"] += roll.negative_coins
        snapshot.messages.append(self.narrator.heal(target["name"], amount))

    def _apply_effect(
        self,
        connection: sqlite3.Connection,
        battle_id: int,
        actor: sqlite3.Row,
        target: sqlite3.Row,
        effect_key: str,
        params: dict[str, Any],
        snapshot: BattleEventSnapshot,
    ) -> None:
        target = self._character(connection, int(target["id"]))
        if int(target["current_hp"]) <= 0:
            snapshot.messages.append(
                f"└ {target['name']} 已在效果生效前倒下，该效果不再生效。"
            )
            return
        definition = connection.execute(
            "SELECT * FROM effect_definitions WHERE effect_key=? AND enabled=1", (effect_key,)
        ).fetchone()
        if definition is None:
            raise BattleRuleError(f"未定义状态效果：{effect_key}")
        merged = _loads(definition["default_params_json"], {})
        merged.update(params)
        intensity = int(merged.get("intensity", 0))
        stacks = int(merged.get("stacks", 0))
        category = EffectCategory(definition["category"])
        if merged.get("activation_timing") == "NEXT_TURN_START":
            connection.execute(
                """
                INSERT INTO battle_pending_effects(
                    battle_id,character_id,effect_key,category,intensity,stacks,
                    activate_at,params_json,source_snapshot_json
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    battle_id, target["id"], effect_key, category.value, intensity, stacks,
                    "NEXT_TURN_START", _dumps(merged),
                    _dumps({"actor_id": actor["id"], "skill_id": snapshot.skill_id}),
                ),
            )
            display_name = (
                str(definition["name"] or "").strip()
                or EFFECT_NAMES.get(effect_key, effect_key)
            )
            snapshot.messages.append(
                self.narrator.pending_effect(target["name"], display_name, intensity)
            )
            return
        self._apply_active_effect(
            connection,
            battle_id,
            actor["id"],
            target,
            definition,
            intensity,
            stacks,
            merged,
            snapshot.messages,
            snapshot,
        )

    def _apply_active_effect(
        self,
        connection: sqlite3.Connection,
        battle_id: int,
        source_character_id: int | None,
        target: sqlite3.Row,
        definition: sqlite3.Row,
        intensity: int,
        stacks: int,
        params: dict[str, Any],
        messages: list[str],
        snapshot: BattleEventSnapshot | None = None,
        *,
        source_skill_id: int | None = None,
    ) -> None:
        category = EffectCategory(definition["category"])
        if category == EffectCategory.INSTANT:
            handler = definition["handler_key"]
            if not handler:
                raise BattleRuleError(f"即时效果 {definition['effect_key']} 没有处理器。")
            self.registry.execute(
                handler,
                EffectExecutionContext(
                    engine=self,
                    connection=connection,
                    battle_id=battle_id,
                    actor_id=source_character_id,
                    target_ids=[int(target["id"])],
                    params=params,
                    snapshot=snapshot,
                    messages=messages,
                ),
            )
            return
        existing = self._active_effect(
            connection, battle_id, target["id"], definition["effect_key"]
        )
        if category == EffectCategory.GENERIC:
            new_intensity = max(intensity, int(existing["intensity"]) if existing else 0)
            new_stacks = 0
        elif category == EffectCategory.REGULAR:
            if existing:
                new_intensity = int(existing["intensity"]) + intensity
                new_stacks = int(existing["stacks"]) + stacks
            else:
                new_intensity = intensity
                new_stacks = stacks if stacks > 0 else 1
        else:
            handler = definition["handler_key"]
            if handler:
                apply_params = dict(params)
                apply_params["_hook"] = "APPLY"
                self.registry.execute(
                    handler,
                    EffectExecutionContext(
                        engine=self,
                        connection=connection,
                        battle_id=battle_id,
                        actor_id=source_character_id,
                        target_ids=[int(target["id"])],
                        params=apply_params,
                        snapshot=snapshot,
                        messages=messages,
                        event="APPLY",
                        hook_owner_id=int(target["id"]),
                    ),
                )
                params = {
                    key: value
                    for key, value in apply_params.items()
                    if not str(key).startswith("_")
                }
            if not params.get("persist", True):
                return
            new_intensity = intensity
            new_stacks = stacks
        connection.execute(
            """
            INSERT INTO active_effects(
                battle_id,character_id,effect_key,category,intensity,stacks,
                remaining_turns,params_json,source_character_id,source_skill_id
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(battle_id,character_id,effect_key) DO UPDATE SET
                intensity=excluded.intensity,stacks=excluded.stacks,
                remaining_turns=excluded.remaining_turns,params_json=excluded.params_json,
                source_character_id=excluded.source_character_id,
                source_skill_id=excluded.source_skill_id
            """,
            (
                battle_id, target["id"], definition["effect_key"], category.value,
                new_intensity, new_stacks, params.get("remaining_turns"),
                _dumps(params), source_character_id,
                source_skill_id if source_skill_id is not None else (
                    snapshot.skill_id if snapshot is not None else None
                ),
            ),
        )
        # 播报优先使用内容包定义的中文名，避免把内部键名暴露给玩家。
        display_name = (
            str(definition["name"] or "").strip()
            or EFFECT_NAMES.get(definition["effect_key"], definition["effect_key"])
        )
        if category == EffectCategory.SPECIAL and "amount" in params:
            messages.append(
                self.narrator.resource(target["name"], display_name, int(params["amount"]))
            )
        else:
            messages.append(
                self.narrator.effect(target["name"], display_name, new_intensity, new_stacks)
            )

    # ------------------------------------------------------------------
    # Turn hooks, emotion and pages
    # ------------------------------------------------------------------
    def _start_turn(self, connection: sqlite3.Connection, battle_id: int) -> list[str]:
        connection.execute(
            "UPDATE battles SET phase=?,current_turn=current_turn+1 WHERE id=?",
            (BattlePhase.TURN_START.value, battle_id),
        )
        battle = connection.execute("SELECT * FROM battles WHERE id=?", (battle_id,)).fetchone()
        messages = [self.narrator.turn_started(int(battle["current_turn"]))]
        participant_ids = [
            row["character_id"]
            for row in connection.execute(
                """
                SELECT bp.character_id FROM battle_participants bp
                JOIN characters c ON c.id=bp.character_id
                WHERE bp.battle_id=? AND bp.active_in_stage=1 AND c.current_hp>0
                """,
                (battle_id,),
            )
        ]
        for character_id in participant_ids:
            messages.extend(self._process_emotion_upgrade(connection, battle_id, character_id))
        # 快照在钩子派发前入队的待生效效果与待激活行为：
        # TURN_START 钩子/注册行为期间新排入的内容必须等到下一次回合开始才激活。
        pending_effect_ids = [
            int(row["id"])
            for row in connection.execute(
                "SELECT id FROM battle_pending_effects"
                " WHERE battle_id=? AND activate_at='NEXT_TURN_START'",
                (battle_id,),
            )
        ]
        pending_behavior_ids = [
            int(row["id"])
            for row in connection.execute(
                "SELECT id FROM battle_registered_behaviors"
                " WHERE battle_id=? AND status='PENDING' AND active_from='NEXT_TURN_START'",
                (battle_id,),
            )
        ]
        messages.extend(
            self._dispatch_hooks(
                connection,
                battle_id,
                BattleEvent.TURN_START,
                event_actor_id=None,
                event_target_ids=[],
                snapshot=None,
            )
        )
        messages.extend(
            self._activate_pending_effects(connection, battle_id, pending_effect_ids)
        )
        if pending_behavior_ids:
            placeholders = ",".join("?" * len(pending_behavior_ids))
            connection.execute(
                "UPDATE battle_registered_behaviors SET status='ACTIVE'"
                " WHERE battle_id=? AND status='PENDING' AND active_from='NEXT_TURN_START'"
                f" AND id IN ({placeholders})",
                (battle_id, *pending_behavior_ids),
            )
        messages.extend(self._execute_registered(connection, battle_id, Timing.TURN_START))
        resolved, outcome_messages = self._resolve_battle_state(connection, battle_id)
        messages.extend(outcome_messages)
        if resolved:
            return messages
        connection.execute(
            "UPDATE battles SET phase=? WHERE id=?",
            (BattlePhase.FRIENDLY_ACTION.value, battle_id),
        )
        messages.append(self.narrator.phase_changed(BattlePhase.FRIENDLY_ACTION))
        return messages

    def _process_emotion_upgrade(
        self, connection: sqlite3.Connection, battle_id: int, character_id: int
    ) -> list[str]:
        character = self._character(connection, character_id)
        if not character["pending_emotion_upgrade"] or character["emotion_level"] >= 5:
            return []
        old_level = int(character["emotion_level"])
        new_level = old_level + 1
        positive = int(character["positive_emotion_coins"])
        negative = int(character["negative_emotion_coins"])
        connection.execute(
            """
            UPDATE characters SET emotion_level=?,positive_emotion_coins=0,
                negative_emotion_coins=0,pending_emotion_upgrade=0 WHERE id=?
            """,
            (new_level, character_id),
        )
        connection.execute(
            """
            UPDATE battle_skill_cooldowns SET remaining=MAX(0,remaining-1)
            WHERE battle_id=? AND character_id=? AND skill_id IN (
                SELECT id FROM skills WHERE skill_type='NORMAL'
            )
            """,
            (battle_id, character_id),
        )
        connection.execute(
            "DELETE FROM battle_skill_cooldowns WHERE battle_id=? AND character_id=? AND remaining=0",
            (battle_id, character_id),
        )
        messages = [f"◇ {character['name']} 的情感等级升至 {new_level}。普通技能冷却额外推进1。"]
        if new_level == 4:
            connection.execute(
                """
                UPDATE characters SET max_actions=max_actions+1,current_actions=current_actions+1,
                    emotion_bonus_actions=emotion_bonus_actions+1 WHERE id=?
                """,
                (character_id,),
            )
            messages.append(f"◇ {character['name']} 的行动上限在本场战斗中提高1。")
        character_kind = connection.execute(
            "SELECT is_core FROM characters WHERE id=?", (character_id,)
        ).fetchone()
        if character_kind and character_kind["is_core"]:
            messages.extend(
                self._create_page_offer(
                    connection, battle_id, character_id, new_level, positive, negative
                )
            )
        connection.execute(
            """
            INSERT INTO emotion_logs(
                battle_id,character_id,event_type,positive_delta,negative_delta,reason,payload_json
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                battle_id, character_id, "LEVEL_UP", -positive, -negative, "TURN_START",
                _dumps({"old_level": old_level, "new_level": new_level}),
            ),
        )
        return messages

    def _award_emotion_for_action(
        self, connection: sqlite3.Connection, actor: sqlite3.Row, snapshot: BattleEventSnapshot
    ) -> None:
        current = self._character(connection, int(actor["id"]))
        if current["pending_emotion_upgrade"] or current["emotion_level"] >= 5:
            return
        positive = int(snapshot.metadata.get("positive_coins", 0))
        negative = int(snapshot.metadata.get("negative_coins", 0))
        if snapshot.metadata.get("damage_total", 0) > 0:
            positive += 1
        if snapshot.metadata.get("healing_total", 0) > 0:
            positive += 1
        # 击杀硬币只统计敌对阵营的死亡：击杀友军不产生正面情感硬币。
        # 2026-07-27 裁定：每击杀一名敌人 +3 正面。
        actor_faction = Faction(current["faction"])
        enemy_kills = {
            hit.target_id
            for hit in snapshot.hits
            if hit.killed and hit.target_faction != actor_faction
        }
        positive += 3 * len(enemy_kills)
        if positive == 0 and negative == 0:
            return
        next_positive = int(current["positive_emotion_coins"]) + positive
        next_negative = int(current["negative_emotion_coins"]) + negative
        required = EMOTION_THRESHOLDS.get(int(current["emotion_level"]))
        pending = int(required is not None and next_positive + next_negative >= required)
        connection.execute(
            """
            UPDATE characters SET positive_emotion_coins=?,negative_emotion_coins=?,
                pending_emotion_upgrade=? WHERE id=?
            """,
            (next_positive, next_negative, pending, actor["id"]),
        )
        connection.execute(
            """
            INSERT INTO emotion_logs(
                battle_id,character_id,event_type,positive_delta,negative_delta,reason,payload_json
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                snapshot.battle_id, actor["id"], "COIN_GAIN", positive, negative,
                "SKILL_RESOLUTION", _dumps({"skill_id": snapshot.skill_id}),
            ),
        )
        if pending:
            snapshot.messages.append(
                f"└ {current['name']} 的情感硬币攒满，待升级。"
            )

    def _grant_negative_coins(
        self,
        connection: sqlite3.Connection,
        character_id: int,
        amount: int,
        snapshot: BattleEventSnapshot,
        reason: str,
    ) -> None:
        current = self._character(connection, character_id)
        if (
            int(current["current_hp"]) <= 0
            or current["pending_emotion_upgrade"]
            or int(current["emotion_level"]) >= 5
        ):
            return
        positive = int(current["positive_emotion_coins"])
        next_negative = int(current["negative_emotion_coins"]) + int(amount)
        required = EMOTION_THRESHOLDS.get(int(current["emotion_level"]))
        pending = int(required is not None and positive + next_negative >= required)
        connection.execute(
            """
            UPDATE characters SET negative_emotion_coins=?,pending_emotion_upgrade=?
            WHERE id=?
            """,
            (next_negative, pending, character_id),
        )
        connection.execute(
            """
            INSERT INTO emotion_logs(
                battle_id,character_id,event_type,positive_delta,negative_delta,reason,payload_json
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                snapshot.battle_id, character_id, "COIN_GAIN", 0, int(amount),
                reason, _dumps({"skill_id": snapshot.skill_id}),
            ),
        )
        if pending:
            snapshot.messages.append(
                f"└ {current['name']} 的情感硬币攒满，待升级。"
            )

    def _award_emotion_for_defense(
        self, connection: sqlite3.Connection, snapshot: BattleEventSnapshot
    ) -> None:
        """挨打与战友阵亡的负面情感（2026-07-27 裁定）。

        - 我方单位在一次行动中受到伤害：+1 负面。
        - 我方单位被击杀：全体存活友方各 +3 负面。
        """
        damaged: set[int] = set()
        fallen: list[int] = []
        for hit in snapshot.hits:
            if hit.target_faction != Faction.FRIENDLY:
                continue
            if hit.damage and int(hit.damage) > 0:
                damaged.add(int(hit.target_id))
            if hit.killed:
                fallen.append(int(hit.target_id))
        if not damaged and not fallen:
            return
        grief: list[int] = []
        if fallen:
            grief = [
                int(row["id"])
                for row in connection.execute(
                    """
                    SELECT c.id FROM characters c
                    JOIN battle_participants bp ON bp.character_id=c.id
                    WHERE bp.battle_id=? AND bp.active_in_stage=1
                      AND c.faction='FRIENDLY' AND c.current_hp>0
                    """,
                    (snapshot.battle_id,),
                ).fetchall()
            ]
            if grief:
                snapshot.messages.append(
                    "└ 战友倒下，全队获得 3 枚负面情感硬币。"
                )
        per_character: dict[int, int] = {}
        for character_id in damaged:
            per_character[character_id] = per_character.get(character_id, 0) + 1
        for character_id in grief:
            per_character[character_id] = per_character.get(character_id, 0) + 3
        for character_id, amount in per_character.items():
            self._grant_negative_coins(
                connection, character_id, amount, snapshot, "DAMAGE_TAKEN"
            )

    def _activate_pending_effects(
        self,
        connection: sqlite3.Connection,
        battle_id: int,
        only_ids: list[int] | None = None,
    ) -> list[str]:
        if only_ids is not None and not only_ids:
            return []
        sql = """
            SELECT p.id AS pending_id,p.battle_id,p.character_id,p.effect_key,
                   p.category,p.intensity,p.stacks,p.activate_at,p.params_json,
                   p.source_snapshot_json,d.name,d.handler_key,d.default_params_json,
                   d.metadata_json
            FROM battle_pending_effects p
            JOIN effect_definitions d ON d.effect_key=p.effect_key
            WHERE p.battle_id=? AND p.activate_at='NEXT_TURN_START'
            """
        query_params: list[Any] = [battle_id]
        if only_ids is not None:
            sql += f" AND p.id IN ({','.join('?' * len(only_ids))})"
            query_params.extend(only_ids)
        sql += " ORDER BY p.id"
        rows = connection.execute(sql, query_params).fetchall()
        messages: list[str] = []
        for row in rows:
            target = self._character(connection, row["character_id"])
            if int(target["current_hp"]) <= 0:
                connection.execute(
                    "DELETE FROM battle_pending_effects WHERE id=?", (row["pending_id"],)
                )
                continue
            source = _loads(row["source_snapshot_json"], {})
            self._apply_active_effect(
                connection,
                battle_id,
                source.get("actor_id"),
                target,
                row,
                int(row["intensity"]),
                int(row["stacks"]),
                _loads(row["params_json"], {}),
                messages,
                source_skill_id=source.get("skill_id"),
            )
            connection.execute(
                "DELETE FROM battle_pending_effects WHERE id=?", (row["pending_id"],)
            )
        return messages

    def _process_turn_end_effects(
        self, connection: sqlite3.Connection, battle_id: int
    ) -> list[str]:
        messages: list[str] = []
        rows = connection.execute(
            """
            SELECT e.*,c.name AS character_name,c.current_hp
            FROM active_effects e JOIN characters c ON c.id=e.character_id
            WHERE e.battle_id=? ORDER BY e.id
            """,
            (battle_id,),
        ).fetchall()
        for effect in rows:
            current_character = self._character(connection, int(effect["character_id"]))
            if current_character["current_hp"] <= 0:
                continue
            key = effect["effect_key"]
            if key == "status.burn":
                self._deal_status_damage(
                    connection,
                    battle_id,
                    effect,
                    int(effect["intensity"]),
                    messages,
                    "烧伤",
                )
                self._consume_regular_stack(connection, effect)
            elif key == "status.poison":
                damage = max(1, math.floor(current_character["current_hp"] * effect["intensity"] / 100))
                self._deal_status_damage(
                    connection, battle_id, effect, damage, messages, "中毒"
                )
                self._consume_regular_stack(connection, effect)
            elif key == "status.breathing":
                self._consume_regular_stack(connection, effect)
                messages.append(
                    self.narrator.stack_consumed(
                        effect["character_name"], key, max(0, int(effect["stacks"]) - 1)
                    )
                )
            elif effect["category"] == EffectCategory.SPECIAL.value:
                if effect["remaining_turns"] is not None:
                    remaining = int(effect["remaining_turns"]) - 1
                    if remaining <= 0:
                        connection.execute("DELETE FROM active_effects WHERE id=?", (effect["id"],))
                    else:
                        connection.execute(
                            "UPDATE active_effects SET remaining_turns=? WHERE id=?",
                            (remaining, effect["id"]),
                        )
        return messages

    def _process_bleeding_after_action(
        self,
        connection: sqlite3.Connection,
        battle_id: int,
        character_id: int,
        messages: list[str],
    ) -> None:
        bleeding = self._active_effect(
            connection, battle_id, character_id, "status.bleeding"
        )
        if bleeding:
            self._deal_status_damage(
                connection,
                battle_id,
                bleeding,
                int(bleeding["intensity"]),
                messages,
                "流血",
            )
            self._consume_regular_stack(connection, bleeding)

    def _process_stagger_and_actions(
        self, connection: sqlite3.Connection, battle_id: int, messages: list[str]
    ) -> None:
        rows = connection.execute(
            """
            SELECT c.* FROM characters c JOIN battle_participants bp ON bp.character_id=c.id
            WHERE bp.battle_id=? AND bp.active_in_stage=1
            """,
            (battle_id,),
        ).fetchall()
        for character in rows:
            if character["current_hp"] <= 0:
                connection.execute("UPDATE characters SET current_actions=0 WHERE id=?", (character["id"],))
                continue
            if character["is_staggered"]:
                remaining = max(0, int(character["stagger_turns"]) - 1)
                if remaining == 0:
                    connection.execute(
                        """
                        UPDATE characters SET is_staggered=0,stagger_turns=0,
                            current_stagger=max_stagger,current_actions=max_actions WHERE id=?
                        """,
                        (character["id"],),
                    )
                    messages.append(f"◇ {character['name']} 从混乱中恢复。")
                else:
                    connection.execute(
                        "UPDATE characters SET stagger_turns=?,current_actions=0 WHERE id=?",
                        (remaining, character["id"]),
                    )
            else:
                connection.execute(
                    "UPDATE characters SET current_actions=max_actions WHERE id=?", (character["id"],)
                )

    # ------------------------------------------------------------------
    # Abnormality pages and manager skills
    # ------------------------------------------------------------------
    def pending_page_offers(self, character_id: int | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT o.*,p.name,p.description,p.page_type,p.level,c.name AS character_name
            FROM battle_page_offers o
            JOIN abnormality_pages p ON p.id=o.page_id
            JOIN characters c ON c.id=o.character_id
            JOIN battles b ON b.id=o.battle_id
            WHERE b.status='ACTIVE' AND o.status='OPEN'
        """
        params: tuple[object, ...] = ()
        if character_id is not None:
            sql += " AND o.character_id=?"
            params = (character_id,)
        sql += " ORDER BY o.id"
        return [dict(row) for row in self.database.fetch_all(sql, params)]

    def choose_page(self, offer_id: int) -> str:
        with self.database.transaction() as connection:
            offer = connection.execute(
                """
                SELECT o.*,p.name,p.handler_key,p.params_json
                FROM battle_page_offers o
                JOIN abnormality_pages p ON p.id=o.page_id
                JOIN battle_page_pool pool ON pool.battle_id=o.battle_id AND pool.page_id=o.page_id
                JOIN battles b ON b.id=o.battle_id
                WHERE o.id=? AND o.status='OPEN' AND pool.status='AVAILABLE'
                  AND b.status='ACTIVE'
                """,
                (offer_id,),
            ).fetchone()
            if offer is None:
                raise BattleRuleError("该书页选择已经失效。")
            connection.execute(
                "UPDATE battle_page_offers SET status='EXPIRED' WHERE offer_group=? AND status='OPEN'",
                (offer["offer_group"],),
            )
            connection.execute(
                "UPDATE battle_page_offers SET status='CHOSEN' WHERE id=?", (offer_id,)
            )
            connection.execute(
                """
                UPDATE battle_page_offers SET status='EXPIRED'
                WHERE battle_id=? AND page_id=? AND id!=? AND status='OPEN'
                """,
                (offer["battle_id"], offer["page_id"], offer_id),
            )
            connection.execute(
                "UPDATE battle_page_pool SET status='USED' WHERE battle_id=? AND page_id=?",
                (offer["battle_id"], offer["page_id"]),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO battle_active_pages(battle_id,character_id,page_id)
                VALUES(?,?,?)
                """,
                (offer["battle_id"], offer["character_id"], offer["page_id"]),
            )
            character = self._character(connection, offer["character_id"])
            message = f"◇ {character['name']} 选取了异想体书页「{offer['name']}」。"
            self._log(
                connection,
                int(offer["battle_id"]),
                "PAGE_CHOSEN",
                actor_id=int(offer["character_id"]),
                payload={"page_id": int(offer["page_id"])},
                message=message,
            )
            return message

    def use_manager_skill(self, manager_skill_key: str) -> tuple[str, ...]:
        with self.database.transaction() as connection:
            battle = self._active_battle(connection)
            skill = connection.execute(
                "SELECT * FROM manager_skills WHERE manager_skill_key=? AND enabled=1",
                (manager_skill_key,),
            ).fetchone()
            if skill is None:
                raise BattleRuleError("该管理人能力尚未解锁或不存在。")
            if skill["unlock_key"] and connection.execute(
                "SELECT 1 FROM manager_unlocks WHERE unlock_key=?", (skill["unlock_key"],)
            ).fetchone() is None:
                raise BattleRuleError("剧情记录尚未解锁该管理人能力。")
            if skill["allowed_phase"] and skill["allowed_phase"] != battle["phase"]:
                raise BattleRuleError("当前并非该管理人能力的合法干预窗口。")
            usage = connection.execute(
                """
                SELECT uses FROM manager_skill_usage
                WHERE battle_id=? AND manager_skill_id=?
                """,
                (battle["id"], skill["id"]),
            ).fetchone()
            used = int(usage["uses"]) if usage else 0
            if used >= int(skill["max_uses_per_battle"]):
                raise BattleRuleError("该管理人能力的本场使用额度已经耗尽。")
            # 干预能力属于经理（玩家）在战局中的特殊手段，见 2026-07-26 裁定。
            messages = [f"【经理干预】「{skill['name']}」"]
            self.registry.execute(
                skill["handler_key"],
                EffectExecutionContext(
                    engine=self,
                    connection=connection,
                    battle_id=battle["id"],
                    actor_id=None,
                    target_ids=[],
                    params=_loads(skill["params_json"], {}),
                    snapshot=None,
                    messages=messages,
                ),
            )
            connection.execute(
                """
                INSERT INTO manager_skill_usage(battle_id,manager_skill_id,uses)
                VALUES(?,?,1)
                ON CONFLICT(battle_id,manager_skill_id) DO UPDATE SET uses=uses+1
                """,
                (battle["id"], skill["id"]),
            )
            _resolved, outcome_messages = self._resolve_battle_state(
                connection, int(battle["id"])
            )
            messages.extend(outcome_messages)
            self._log(
                connection,
                int(battle["id"]),
                "MANAGER_SKILL",
                payload={"manager_skill_key": manager_skill_key},
                message="\n".join(messages),
            )
            return tuple(messages)

    def forfeit_assist_actions(self) -> tuple[str, ...]:
        """助战让行：管理人放弃所有存活助战单位的剩余行动，让玩家核心开始行动。"""
        with self.database.transaction() as connection:
            battle = self._active_battle(connection)
            if BattlePhase(battle["phase"]) != BattlePhase.FRIENDLY_ACTION:
                raise BattleRuleError("助战让行仅能在我方行动阶段使用。")
            rows = connection.execute(
                """
                SELECT c.id,c.name FROM characters c
                JOIN battle_participants bp ON bp.character_id=c.id
                WHERE bp.battle_id=? AND bp.active_in_stage=1
                  AND c.faction='FRIENDLY' AND c.is_core=0
                  AND c.current_hp>0 AND c.current_actions>0
                ORDER BY c.id
                """,
                (int(battle["id"]),),
            ).fetchall()
            if not rows:
                raise BattleRuleError("当前没有待让行的助战行动。")
            connection.execute(
                """
                UPDATE characters SET current_actions=0
                WHERE id IN (
                    SELECT c.id FROM characters c
                    JOIN battle_participants bp ON bp.character_id=c.id
                    WHERE bp.battle_id=? AND bp.active_in_stage=1
                      AND c.faction='FRIENDLY' AND c.is_core=0
                )
                """,
                (int(battle["id"]),),
            )
            # 让行是流程操作，不进播报（2026-07-27 反馈）；界面靠 refresh 更新。
            # 若让行后我方已无人可动，同样触发自动推进。
            return tuple(self._auto_advance_phase(connection, int(battle["id"])))

    def unlock_manager_feature(
        self, unlock_key: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Persist a story unlock independently from any active battle."""
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO manager_unlocks(unlock_key,metadata_json)
                VALUES(?,?) ON CONFLICT(unlock_key) DO UPDATE SET
                    metadata_json=excluded.metadata_json
                """,
                (unlock_key, _dumps(metadata or {})),
            )

    # ------------------------------------------------------------------
    # Query helpers and extension hooks
    # ------------------------------------------------------------------
    def battle_status(self) -> dict[str, Any]:
        with self.database.reading() as connection:
            battle = self._active_battle(connection)
            participants = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT c.*,bp.active_in_stage FROM characters c
                    JOIN battle_participants bp ON bp.character_id=c.id
                    WHERE bp.battle_id=? ORDER BY c.faction DESC,c.id
                    """,
                    (battle["id"],),
                )
            ]
            effects_by_character: dict[int, list[dict[str, Any]]] = {}
            for row in connection.execute(
                """
                SELECT e.character_id,e.effect_key,e.category,e.intensity,e.stacks,
                       e.remaining_turns,e.params_json,d.name AS effect_name
                FROM active_effects e
                LEFT JOIN effect_definitions d ON d.effect_key=e.effect_key
                WHERE e.battle_id=? ORDER BY e.id
                """,
                (battle["id"],),
            ):
                entry = dict(row)
                entry["params"] = _loads(row["params_json"], {})
                effects_by_character.setdefault(int(row["character_id"]), []).append(entry)
            pending_by_character: dict[int, list[dict[str, Any]]] = {}
            for row in connection.execute(
                """
                SELECT p.character_id,p.effect_key,p.intensity,p.stacks,p.activate_at,
                       d.name AS effect_name
                FROM battle_pending_effects p
                LEFT JOIN effect_definitions d ON d.effect_key=p.effect_key
                WHERE p.battle_id=? ORDER BY p.id
                """,
                (battle["id"],),
            ):
                pending_by_character.setdefault(int(row["character_id"]), []).append(dict(row))
            pages_by_character: dict[int, list[dict[str, Any]]] = {}
            for row in connection.execute(
                """
                SELECT ap.character_id,p.name,p.page_type,p.level
                FROM battle_active_pages ap
                JOIN abnormality_pages p ON p.id=ap.page_id
                WHERE ap.battle_id=? ORDER BY ap.activated_at,p.id
                """,
                (battle["id"],),
            ):
                pages_by_character.setdefault(int(row["character_id"]), []).append(dict(row))
            for participant in participants:
                character_id = int(participant["id"])
                participant["effects"] = effects_by_character.get(character_id, [])
                participant["pending_effects"] = pending_by_character.get(character_id, [])
                participant["pages"] = pages_by_character.get(character_id, [])
            result = dict(battle)
            result["participants"] = participants
            return result

    def _register_builtin_special_effects(self) -> None:
        if not self.registry.contains("bonus_actions"):
            self.registry.register("bonus_actions", self._special_bonus_actions)
        if not self.registry.contains("summon_unit"):
            self.registry.register("summon_unit", self._special_summon_unit)
        if not self.registry.contains("invoke_skill"):
            self.registry.register("invoke_skill", self._special_invoke_skill)
        if not self.registry.contains("accumulate_resource"):
            self.registry.register("accumulate_resource", self._special_accumulate_resource)
        if not self.registry.contains("consume_resource"):
            self.registry.register("consume_resource", self._special_consume_resource)
        if not self.registry.contains("require_effect_from_actor"):
            self.registry.register(
                "require_effect_from_actor", self._special_require_effect_from_actor
            )
        if not self.registry.contains("fortune_verdict"):
            self.registry.register("fortune_verdict", self._special_fortune_verdict)
        if not self.registry.contains("emotion_shift"):
            self.registry.register("emotion_shift", self._special_emotion_shift)
        if not self.registry.contains("hook_sequence"):
            self.registry.register("hook_sequence", self._special_hook_sequence)
        if not self.registry.contains("hook_apply_effect"):
            self.registry.register("hook_apply_effect", self._special_hook_apply_effect)
        if not self.registry.contains("hook_heal"):
            self.registry.register("hook_heal", self._special_hook_heal)
        if not self.registry.contains("hook_damage"):
            self.registry.register("hook_damage", self._special_hook_damage)

    @staticmethod
    def _resolve_hook_targets(context: EffectExecutionContext, mode: str) -> list[int]:
        """书页/被动钩子的目标解析：SELF / ALL_FRIENDLY / ALL_ENEMY / RANDOM_ENEMY / RANDOM_FRIENDLY。"""
        normalized = str(mode or "SELF").upper()
        if normalized == "SELF":
            return [int(context.actor_id)] if context.actor_id else []
        faction = "FRIENDLY" if "FRIENDLY" in normalized else "ENEMY"
        rows = context.connection.execute(
            """
            SELECT c.id FROM characters c
            JOIN battle_participants bp ON bp.character_id=c.id
            WHERE bp.battle_id=? AND bp.active_in_stage=1
              AND c.faction=? AND c.current_hp>0
            ORDER BY c.id
            """,
            (context.battle_id, faction),
        ).fetchall()
        ids = [int(row["id"]) for row in rows]
        if normalized.startswith("RANDOM") and ids:
            return [context.engine.rng.choice(ids)]
        return ids

    @staticmethod
    def _hook_chance_passes(context: EffectExecutionContext) -> bool:
        chance = float(context.params.get("chance", 1.0))
        return chance >= 1.0 or context.engine.rng.random() < chance

    @staticmethod
    def _special_hook_sequence(context: EffectExecutionContext) -> None:
        """组合钩子：按顺序执行多个子处理器（双刃剑书页用：增益+代价）。

        params.steps = [{"handler": ..., "params": {...}}, ...]；不允许嵌套。
        """
        steps = context.params.get("steps")
        if not isinstance(steps, list) or not steps:
            raise BattleRuleError("hook_sequence 需要非空 steps 列表。")
        for step in steps:
            handler = str((step or {}).get("handler") or "")
            if not handler:
                raise BattleRuleError("hook_sequence 的 step 缺少 handler。")
            if handler == "hook_sequence":
                raise BattleRuleError("hook_sequence 不允许嵌套。")
            sub_context = dataclass_replace(
                context, params=dict((step or {}).get("params") or {})
            )
            context.engine.registry.execute(handler, sub_context)

    @staticmethod
    def _special_hook_apply_effect(context: EffectExecutionContext) -> None:
        """书页/携带被动钩子：向指定范围施加状态效果。

        params: effect_key（必填）、intensity、stacks、target、chance。
        """
        if not BattleEngine._hook_chance_passes(context):
            return
        effect_key = str(context.params.get("effect_key") or "")
        definition = context.connection.execute(
            "SELECT * FROM effect_definitions WHERE effect_key=? AND enabled=1",
            (effect_key,),
        ).fetchone()
        if definition is None:
            raise BattleRuleError(f"未定义状态效果：{effect_key}")
        intensity = max(0, int(context.params.get("intensity", 1)))
        stacks = max(0, int(context.params.get("stacks", 0)))
        for target_id in BattleEngine._resolve_hook_targets(
            context, context.params.get("target", "SELF")
        ):
            target = context.engine._character(context.connection, target_id)
            if int(target["current_hp"]) <= 0:
                continue
            context.engine._apply_active_effect(
                context.connection,
                context.battle_id,
                target_id,
                target,
                definition,
                intensity,
                stacks,
                {"intensity": intensity, "stacks": stacks},
                context.messages,
                context.snapshot,
            )

    @staticmethod
    def _special_hook_heal(context: EffectExecutionContext) -> None:
        """书页/携带被动钩子：治疗指定范围。params: amount、target、chance。"""
        if not BattleEngine._hook_chance_passes(context):
            return
        amount = max(0, int(context.params.get("amount", 1)))
        if amount == 0:
            return
        for target_id in BattleEngine._resolve_hook_targets(
            context, context.params.get("target", "SELF")
        ):
            target = context.engine._character(context.connection, target_id)
            if int(target["current_hp"]) <= 0:
                continue
            new_hp = min(int(target["max_hp"]), int(target["current_hp"]) + amount)
            healed = new_hp - int(target["current_hp"])
            if healed <= 0:
                continue
            context.connection.execute(
                "UPDATE characters SET current_hp=? WHERE id=?", (new_hp, target_id)
            )
            context.messages.append(
                context.engine.narrator.heal(str(target["name"]), healed)
            )

    @staticmethod
    def _special_hook_damage(context: EffectExecutionContext) -> None:
        """书页/携带被动钩子：对指定范围造成固定伤害。params: amount、target、chance、source。"""
        if not BattleEngine._hook_chance_passes(context):
            return
        amount = max(0, int(context.params.get("amount", 1)))
        if amount == 0:
            return
        source_name = str(context.params.get("source") or "书页效果")
        for target_id in BattleEngine._resolve_hook_targets(
            context, context.params.get("target", "RANDOM_ENEMY")
        ):
            target = context.engine._character(context.connection, target_id)
            if int(target["current_hp"]) <= 0:
                continue
            context.engine._fixed_damage(
                context.connection, target_id, amount, context.messages, source_name
            )

    @staticmethod
    def _special_bonus_actions(context: EffectExecutionContext) -> None:
        amount = max(0, int(context.params.get("amount", 1)))
        targets = context.target_ids
        if not targets and context.actor_id is not None:
            targets = [context.actor_id]
        if not targets and context.params.get("target_faction"):
            faction = Faction(str(context.params["target_faction"]))
            targets = [
                int(row["character_id"])
                for row in context.connection.execute(
                    """
                    SELECT bp.character_id FROM battle_participants bp
                    JOIN characters c ON c.id=bp.character_id
                    WHERE bp.battle_id=? AND bp.active_in_stage=1
                      AND c.faction=? AND c.current_hp>0
                    ORDER BY bp.character_id
                    """,
                    (context.battle_id, faction.value),
                )
            ]
        for character_id in targets:
            character = context.engine._character(context.connection, character_id)
            context.connection.execute(
                "UPDATE characters SET current_actions=current_actions+? WHERE id=?",
                (amount, character_id),
            )
            context.messages.append(f"└ {character['name']} 获得 {amount} 点额外行动。")

    @staticmethod
    def _special_summon_unit(context: EffectExecutionContext) -> None:
        template_key = str(context.params["template_key"])
        faction = Faction(context.params.get("faction", "ENEMY"))
        count = max(1, min(10, int(context.params.get("count", 1))))
        battle = context.engine._battle(context.connection, context.battle_id)
        for index in range(count):
            name = context.params.get("name")
            if name and count > 1:
                name = f"{name} {index + 1}"
            character_id = context.engine._spawn_character(
                context.connection, template_key, faction, name=name
            )
            context.engine._add_participants(
                context.connection,
                context.battle_id,
                [character_id],
                faction,
                int(battle["current_stage"]),
            )
            character = context.engine._character(context.connection, character_id)
            context.messages.append(f"└ {character['name']} 加入了战场。")

    @staticmethod
    def _special_invoke_skill(context: EffectExecutionContext) -> None:
        if context.recursion_depth >= 5:
            raise BattleRuleError("技能调用链超过安全深度。")
        actor_id = int(context.params.get("actor_id") or context.actor_id or 0)
        skill_key = str(context.params["skill_key"])
        skill = context.connection.execute(
            "SELECT id FROM skills WHERE skill_key=? AND enabled=1", (skill_key,)
        ).fetchone()
        if not actor_id or skill is None:
            raise BattleRuleError("调用其他技能时缺少合法使用者或技能。")
        result = context.engine._use_skill(
            context.connection,
            actor_id,
            int(skill["id"]),
            list(context.target_ids),
            consume_action=False,
            recursion_depth=context.recursion_depth + 1,
            enforce_action_rules=False,
            award_emotion=bool(context.params.get("award_emotion", False)),
        )
        context.messages.extend(result.messages)

    @staticmethod
    def _special_accumulate_resource(context: EffectExecutionContext) -> None:
        if context.event not in (None, "APPLY") and context.params.get("_hook") != "APPLY":
            return
        incoming = int(context.params.get("amount", 0))
        if not context.target_ids:
            return
        target_id = int(context.target_ids[0])
        effect_key = str(context.params.get("resource_key", "status.hardblood"))
        existing = context.engine._active_effect(
            context.connection, context.battle_id, target_id, effect_key
        )
        current = 0
        if existing is not None:
            current = int(_loads(existing["params_json"], {}).get("amount", 0))
        context.params["amount"] = max(0, current + incoming)

    @staticmethod
    def _special_consume_resource(context: EffectExecutionContext) -> None:
        owner_mode = str(context.params.get("resource_owner", "ACTOR")).upper()
        if owner_mode == "TARGET" and context.target_ids:
            owner_id = int(context.target_ids[0])
        else:
            owner_id = int(context.actor_id or 0)
        if not owner_id:
            raise BattleRuleError("资源消耗行为缺少合法持有者。")
        effect_key = str(context.params.get("resource_key", "status.hardblood"))
        effect = context.engine._active_effect(
            context.connection, context.battle_id, owner_id, effect_key
        )
        current = int(_loads(effect["params_json"], {}).get("amount", 0)) if effect else 0
        requested = max(0, int(context.params.get("amount", 0)))
        consumed = min(current, requested)
        if effect is not None:
            state = _loads(effect["params_json"], {})
            state["amount"] = current - consumed
            context.connection.execute(
                "UPDATE active_effects SET params_json=? WHERE id=?",
                (_dumps(state), effect["id"]),
            )
        context.params["consumed"] = consumed
        if context.snapshot is not None:
            resources = context.snapshot.metadata.setdefault("resources_consumed", {})
            resources[effect_key] = int(resources.get(effect_key, 0)) + consumed
            per_unit = float(context.params.get("damage_multiplier_per_unit", 0))
            damage_context = context.snapshot.metadata.get("damage_context")
            consume_label = (
                f"消耗{consumed}点{EFFECT_NAMES.get(effect_key, effect_key)}"
                if consumed else ""
            )
            if per_unit and isinstance(damage_context, dict):
                damage_context["multiplier"] = float(
                    damage_context.get("multiplier", 1.0)
                ) + consumed * per_unit
                if consume_label:
                    damage_context.setdefault("labels", []).append(consume_label)
            elif per_unit:
                context.snapshot.metadata["pending_damage_multiplier"] = (
                    float(context.snapshot.metadata.get("pending_damage_multiplier", 1.0))
                    + consumed * per_unit
                )
                if consume_label:
                    context.snapshot.metadata.setdefault(
                        "pending_damage_labels", []
                    ).append(consume_label)
        character = context.engine._character(context.connection, owner_id)
        context.messages.append(
            f"└ {character['name']} 消耗「{EFFECT_NAMES.get(effect_key, effect_key)}」"
            f" {consumed}，剩余 {current - consumed}。"
        )

    @staticmethod
    def _special_require_effect_from_actor(context: EffectExecutionContext) -> None:
        effect_key = str(context.params["effect_key"])
        actor_id = int(context.actor_id or 0)
        if not actor_id or not context.target_ids:
            raise BattleRuleError("条件技能缺少合法使用者或目标。")
        for target_id in context.target_ids:
            marked = context.connection.execute(
                """
                SELECT 1 FROM active_effects
                WHERE battle_id=? AND character_id=? AND effect_key=?
                  AND source_character_id=?
                """,
                (context.battle_id, target_id, effect_key, actor_id),
            ).fetchone()
            if marked is None:
                raise BattleRuleError(
                    str(context.params.get("error", "目标尚未满足该技能的使用条件。"))
                )

    @staticmethod
    def _special_fortune_verdict(context: EffectExecutionContext) -> None:
        actor_id = int(context.actor_id or 0)
        if not actor_id:
            raise BattleRuleError("幸运判定缺少合法使用者。")
        positive = context.engine.rng.random() < 0.5
        effect_key = "status.strength" if positive else "status.weakness"
        definition = context.connection.execute(
            "SELECT * FROM effect_definitions WHERE effect_key=? AND enabled=1",
            (effect_key,),
        ).fetchone()
        actor = context.engine._character(context.connection, actor_id)
        if definition is None:
            raise BattleRuleError(f"未定义状态效果：{effect_key}")
        intensity = max(1, int(context.params.get("intensity", 2)))
        context.engine._apply_active_effect(
            context.connection,
            context.battle_id,
            actor_id,
            actor,
            definition,
            intensity,
            0,
            {"intensity": intensity},
            context.messages,
            context.snapshot,
        )
        if context.snapshot is not None:
            coin_key = "positive_coins" if positive else "negative_coins"
            context.snapshot.metadata[coin_key] = int(
                context.snapshot.metadata.get(coin_key, 0)
            ) + 1
        verdict = "正面" if positive else "负面"
        context.messages.append(f"└ 幸运落在{verdict}一侧。")

    @staticmethod
    def _special_emotion_shift(context: EffectExecutionContext) -> None:
        polarity = str(context.params.get("polarity", "NEGATIVE")).upper()
        amount = max(0, int(context.params.get("amount", 1)))
        if amount == 0:
            return
        targets = list(context.target_ids)
        if not targets and context.actor_id is not None:
            targets = [int(context.actor_id)]
        for target_id in targets:
            target = context.engine._character(context.connection, int(target_id))
            if int(target["emotion_level"]) >= 5:
                context.messages.append(
                    f"└ {target['name']} 的情感已达上限，硬币不再累积。"
                )
                continue
            if int(target["pending_emotion_upgrade"]):
                context.messages.append(
                    f"└ {target['name']} 的情感硬币已攒满待升级，本次不再累积。"
                )
                continue
            positive = int(target["positive_emotion_coins"])
            negative = int(target["negative_emotion_coins"])
            if polarity == "POSITIVE":
                positive += amount
            else:
                negative += amount
            required = EMOTION_THRESHOLDS.get(int(target["emotion_level"]))
            pending = int(required is not None and positive + negative >= required)
            context.connection.execute(
                """
                UPDATE characters SET positive_emotion_coins=?,negative_emotion_coins=?,
                    pending_emotion_upgrade=? WHERE id=?
                """,
                (positive, negative, pending, target_id),
            )
            context.connection.execute(
                """
                INSERT INTO emotion_logs(
                    battle_id,character_id,event_type,positive_delta,negative_delta,
                    reason,payload_json
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    context.battle_id,
                    int(target_id),
                    "COIN_GAIN",
                    amount if polarity == "POSITIVE" else 0,
                    0 if polarity == "POSITIVE" else amount,
                    "EMOTION_SHIFT",
                    _dumps(
                        {
                            "skill_id": (
                                context.snapshot.skill_id
                                if context.snapshot is not None
                                else None
                            ),
                            "source_actor_id": context.actor_id,
                        }
                    ),
                ),
            )
            label = "正面" if polarity == "POSITIVE" else "负面"
            context.messages.append(
                f"└ {target['name']} 获得 {amount} 枚{label}情感硬币。"
            )
            if pending:
                context.messages.append(
                    f"└ {target['name']} 的情感硬币攒满，待升级。"
                )

    def _character_skill_rows(
        self, connection: sqlite3.Connection, character: sqlite3.Row
    ) -> list[sqlite3.Row]:
        if int(character["is_core"]):
            return connection.execute(
                """
                SELECT DISTINCT s.* FROM skills s
                WHERE s.enabled=1 AND (
                    s.id=?
                    OR s.id IN (SELECT skill_id FROM persona_skills WHERE persona_id=?)
                )
                ORDER BY CASE s.skill_type WHEN 'NORMAL' THEN 0 ELSE 1 END,s.id
                """,
                (character["ego_skill_id"], character["active_persona_id"]),
            ).fetchall()
        return connection.execute(
            """
            SELECT DISTINCT s.* FROM skills s
            JOIN character_templates t ON t.template_key=?
            WHERE s.enabled=1 AND (
                s.id=t.ego_skill_id
                OR s.id IN (
                    SELECT skill_id FROM character_ego_skills
                    WHERE template_key=t.template_key
                )
                OR s.id IN (SELECT skill_id FROM template_skills WHERE template_key=t.template_key)
                OR s.id IN (SELECT skill_id FROM persona_skills WHERE persona_id=?)
            )
            ORDER BY CASE s.skill_type WHEN 'NORMAL' THEN 0 ELSE 1 END,s.id
            """,
            (character["template_key"], character["active_persona_id"]),
        ).fetchall()

    def _ensure_skill_owned(
        self, connection: sqlite3.Connection, actor: sqlite3.Row, skill_id: int
    ) -> sqlite3.Row:
        for row in self._character_skill_rows(connection, actor):
            if int(row["id"]) == int(skill_id):
                return row
        raise BattleRuleError("该技能不属于当前角色/人格。")

    def _resolve_skill_targets(
        self,
        connection: sqlite3.Connection,
        battle_id: int,
        actor: sqlite3.Row,
        skill: sqlite3.Row,
        selected_target_ids: list[int],
    ) -> list[sqlite3.Row]:
        pool = self._target_pool(
            connection, battle_id, actor, TargetScope(skill["target_scope"])
        )
        method = TargetMethod(skill["target_method"])
        if method == TargetMethod.SELF:
            return [actor]
        if not pool:
            raise BattleRuleError("没有符合技能范围的存活目标。")
        if method == TargetMethod.ALL_TARGETS:
            return pool
        if method == TargetMethod.RANDOM:
            count = int(skill["target_param"])
            return [self.rng.choice(pool) for _ in range(count)]
        if len(selected_target_ids) != 1:
            raise BattleRuleError("选择目标技能必须且只能指定一个目标。")
        if len(set(int(item) for item in selected_target_ids)) != len(selected_target_ids):
            raise BattleRuleError("同一次交互不能重复指定同一目标。")
        pool_by_id = {int(row["id"]): row for row in pool}
        result: list[sqlite3.Row] = []
        for target_id in selected_target_ids:
            if int(target_id) not in pool_by_id:
                raise BattleRuleError("选择的目标不在技能合法范围内。")
            result.append(pool_by_id[int(target_id)])
        return result

    def _resolve_behavior_targets(
        self,
        connection: sqlite3.Connection,
        battle_id: int,
        actor: sqlite3.Row,
        behavior: sqlite3.Row,
        skill_targets: list[sqlite3.Row],
        condition_target_id: int | None,
    ) -> list[sqlite3.Row]:
        if behavior["target_source"] == "INHERIT_SKILL":
            if condition_target_id is None:
                return skill_targets
            for target in skill_targets:
                if int(target["id"]) == condition_target_id:
                    return [target]
            # 决策8：INHERIT_SKILL 只能作用于技能层目标快照；
            # 条件目标不在快照内时本次重复直接跳过，不得回退到全角色表。
            return []
        pool = self._target_pool(
            connection, battle_id, actor, TargetScope(behavior["target_scope"])
        )
        method = TargetMethod(behavior["target_method"])
        if method == TargetMethod.SELF:
            return [actor]
        if method == TargetMethod.ALL_TARGETS:
            return pool
        if method == TargetMethod.RANDOM:
            return [self.rng.choice(pool) for _ in range(int(behavior["target_param"]))] if pool else []
        raise BattleRuleError("行为层禁止交互式目标选择。")

    def _target_pool(
        self,
        connection: sqlite3.Connection,
        battle_id: int,
        actor: sqlite3.Row,
        scope: TargetScope,
    ) -> list[sqlite3.Row]:
        if scope == TargetScope.SELF:
            return [actor] if actor["current_hp"] > 0 else []
        rows = connection.execute(
            """
            SELECT c.* FROM characters c
            JOIN battle_participants bp ON bp.character_id=c.id
            WHERE bp.battle_id=? AND bp.active_in_stage=1 AND c.current_hp>0
            ORDER BY c.id
            """,
            (battle_id,),
        ).fetchall()
        actor_faction = Faction(actor["faction"])
        if scope == TargetScope.ALL:
            return rows
        wanted = actor_faction if scope == TargetScope.FRIENDLY else (
            Faction.ENEMY if actor_faction == Faction.FRIENDLY else Faction.FRIENDLY
        )
        return [row for row in rows if row["faction"] == wanted.value]

    def _register_deferred_skill_behaviors(
        self,
        connection: sqlite3.Connection,
        battle_id: int,
        actor: sqlite3.Row,
        skill: sqlite3.Row,
        behaviors: list[sqlite3.Row],
        target_ids: list[int],
    ) -> None:
        for behavior in behaviors:
            if behavior["timing"] not in {Timing.TURN_START.value, Timing.TURN_END.value}:
                continue
            params = _loads(behavior["effect_params_json"], {})
            registration = params.get("registration")
            if not isinstance(registration, dict):
                continue
            connection.execute(
                """
                INSERT INTO battle_registered_behaviors(
                    battle_id,behavior_id,owner_character_id,source_type,source_key,
                    active_from,remaining_turns,remaining_triggers,lifecycle_scope,status,
                    target_snapshot_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    battle_id, behavior["id"], actor["id"], "SKILL", skill["skill_key"],
                    registration.get("active_from", "NEXT_TURN_START"),
                    registration.get("remaining_turns", 1),
                    registration.get("remaining_triggers", 1),
                    registration.get("lifecycle_scope", "TURN"),
                    "ACTIVE"
                    if registration.get("active_from") == "THIS_TURN_END"
                    else "PENDING",
                    _dumps(target_ids),
                ),
            )

    def _execute_registered(
        self, connection: sqlite3.Connection, battle_id: int, timing: Timing
    ) -> list[str]:
        rows = connection.execute(
            """
            SELECT rb.id AS registration_id,rb.battle_id,rb.owner_character_id,
                   rb.source_type,rb.source_key,rb.active_from,rb.remaining_turns,
                   rb.remaining_triggers,rb.lifecycle_scope,rb.status,
                   rb.target_snapshot_json,
                   b.*,s.id AS source_skill_id
            FROM battle_registered_behaviors rb
            JOIN skill_behaviors b ON b.id=rb.behavior_id
            JOIN skills s ON s.id=b.skill_id
            WHERE rb.battle_id=? AND rb.status='ACTIVE' AND b.timing=?
            ORDER BY b.sort_order,rb.id
            """,
            (battle_id, timing.value),
        ).fetchall()
        messages: list[str] = []
        battle = self._battle(connection, battle_id)
        for row in rows:
            actor = connection.execute(
                """
                SELECT c.* FROM characters c
                JOIN battle_participants bp ON bp.character_id=c.id
                WHERE bp.battle_id=? AND bp.character_id=?
                  AND bp.active_in_stage=1 AND c.current_hp>0
                """,
                (battle_id, row["owner_character_id"]),
            ).fetchone()
            if actor is None:
                connection.execute(
                    """
                    UPDATE battle_registered_behaviors SET status='EXHAUSTED'
                    WHERE id=?
                    """,
                    (row["registration_id"],),
                )
                continue
            original_target_ids = [
                int(item) for item in _loads(row["target_snapshot_json"], [])
            ]
            active_ids = {
                int(target["character_id"])
                for target in connection.execute(
                    """
                    SELECT bp.character_id FROM battle_participants bp
                    JOIN characters c ON c.id=bp.character_id
                    WHERE bp.battle_id=? AND bp.active_in_stage=1 AND c.current_hp>0
                    """,
                    (battle_id,),
                )
            }
            if row["target_source"] == "INHERIT_SKILL":
                target_ids = [
                    character_id for character_id in original_target_ids
                    if character_id in active_ids
                ]
            else:
                # AUTO behaviors resolve a fresh active pool at execution time;
                # their old skill snapshot is contextual, not a fixed target.
                target_ids = original_target_ids
            if (
                row["target_source"] == "INHERIT_SKILL"
                and original_target_ids
                and not target_ids
            ):
                connection.execute(
                    """
                    UPDATE battle_registered_behaviors SET status='EXHAUSTED'
                    WHERE id=?
                    """,
                    (row["registration_id"],),
                )
                continue
            targets = [self._character(connection, int(item)) for item in target_ids]
            snapshot = BattleEventSnapshot(
                battle_id=battle_id,
                actor_id=actor["id"],
                skill_id=row["source_skill_id"],
                skill_target_ids=target_ids,
                messages=messages,
                metadata={"damage_total": 0, "healing_total": 0, "positive_coins": 0, "negative_coins": 0},
            )
            self._execute_behavior(connection, battle, actor, row, targets, snapshot, recursion_depth=0)
            triggers = row["remaining_triggers"]
            if triggers is not None:
                triggers = int(triggers) - 1
            turns = row["remaining_turns"]
            exhausted = (triggers is not None and triggers <= 0) or (turns is not None and turns <= 0)
            connection.execute(
                """
                UPDATE battle_registered_behaviors
                SET status=?,remaining_triggers=?,remaining_turns=?,target_snapshot_json=?
                WHERE id=?
                """,
                (
                    "EXHAUSTED" if exhausted else "ACTIVE",
                    triggers,
                    turns,
                    _dumps(target_ids),
                    row["registration_id"],
                ),
            )
        return messages

    @staticmethod
    def _age_registered_behaviors(
        connection: sqlite3.Connection, battle_id: int
    ) -> None:
        """Advance every active registered behavior exactly once per TURN_END."""
        connection.execute(
            """
            UPDATE battle_registered_behaviors
            SET remaining_turns=remaining_turns-1
            WHERE battle_id=? AND status='ACTIVE' AND remaining_turns IS NOT NULL
            """,
            (battle_id,),
        )
        connection.execute(
            """
            UPDATE battle_registered_behaviors SET status='EXHAUSTED'
            WHERE battle_id=? AND status='ACTIVE' AND remaining_turns<=0
            """,
            (battle_id,),
        )

    def _prepare_abnormality_pool(
        self, connection: sqlite3.Connection, battle_id: int, abnormality_keys: list[str]
    ) -> list[str]:
        """播种书页池（CARRY 页不进抽取池），并激活各异想体的携带被动。"""
        carries: list[tuple[int, str, str]] = []
        for key in dict.fromkeys(abnormality_keys):
            abnormality = connection.execute(
                "SELECT id,name FROM abnormalities WHERE abnormality_key=? AND enabled=1",
                (key,),
            ).fetchone()
            if abnormality is None:
                raise BattleRuleError(f"异想体未登记：{key}")
            connection.execute(
                "INSERT INTO battle_abnormalities(battle_id,abnormality_id) VALUES(?,?)",
                (battle_id, abnormality["id"]),
            )
            connection.execute(
                """
                INSERT INTO battle_page_pool(battle_id,page_id,status)
                SELECT ?,id,'AVAILABLE' FROM abnormality_pages
                WHERE abnormality_id=? AND enabled=1 AND page_type!='CARRY'
                """,
                (battle_id, abnormality["id"]),
            )
            for carry in connection.execute(
                """
                SELECT id,name FROM abnormality_pages
                WHERE abnormality_id=? AND enabled=1 AND page_type='CARRY'
                ORDER BY id
                """,
                (abnormality["id"],),
            ).fetchall():
                carries.append(
                    (int(carry["id"]), str(carry["name"]), str(abnormality["name"]))
                )
        if not carries:
            return []
        lead = connection.execute(
            """
            SELECT c.id FROM characters c
            JOIN battle_participants bp ON bp.character_id=c.id
            WHERE bp.battle_id=? AND c.faction='FRIENDLY'
            ORDER BY c.is_core DESC,c.id LIMIT 1
            """,
            (battle_id,),
        ).fetchone()
        if lead is None:
            return []
        messages = []
        for page_id, page_name, abnormality_name in carries:
            connection.execute(
                """
                INSERT OR IGNORE INTO battle_active_pages(battle_id,character_id,page_id)
                VALUES(?,?,?)
                """,
                (battle_id, int(lead["id"]), page_id),
            )
            messages.append(f"◇ 携带被动生效：「{page_name}」（{abnormality_name}）")
        return messages

    def _create_page_offer(
        self,
        connection: sqlite3.Connection,
        battle_id: int,
        character_id: int,
        level: int,
        positive: int,
        negative: int,
    ) -> list[str]:
        preferred = "AWAKENING" if positive >= negative else "BREAKDOWN"
        # 情感等级是"解锁上限"：本人 1-2 级解锁Ⅰ级页、3-4 级解锁至Ⅱ级、
        # 5 级解锁至Ⅲ级；低级页始终在候选池内（2026-07-27 裁定）。
        own_level = int(level)
        max_page_level = 1 if own_level <= 2 else 2 if own_level <= 4 else 3
        rows = connection.execute(
            """
            SELECT p.* FROM abnormality_pages p
            JOIN battle_page_pool pool ON pool.page_id=p.id
            WHERE pool.battle_id=? AND pool.status='AVAILABLE' AND p.enabled=1
              AND p.page_type IN ('AWAKENING','BREAKDOWN') AND p.level<=?
            ORDER BY CASE p.page_type WHEN ? THEN 0 ELSE 1 END,p.id
            """,
            (battle_id, max_page_level, preferred),
        ).fetchall()
        if not rows:
            return ["◇ 携带的异想体没有可选书页，本次选择跳过。"]
        preferred_rows = [row for row in rows if row["page_type"] == preferred]
        other_rows = [row for row in rows if row["page_type"] != preferred]
        self.rng.shuffle(preferred_rows)
        self.rng.shuffle(other_rows)
        selected = (preferred_rows + other_rows)[:3]
        offer_group = f"{battle_id}:{character_id}:{level}"
        for page in selected:
            connection.execute(
                """
                INSERT INTO battle_page_offers(
                    battle_id,character_id,offer_group,page_id,status
                ) VALUES(?,?,?,?,'OPEN')
                """,
                (battle_id, character_id, offer_group, page["id"]),
            )
        return [
            f"◇ 出现 {len(selected)} 张书页候选，请选取一张。"
        ]

    def _dispatch_hooks(
        self,
        connection: sqlite3.Connection,
        battle_id: int,
        event: BattleEvent,
        *,
        event_actor_id: int | None,
        event_target_ids: list[int],
        snapshot: BattleEventSnapshot | None,
        messages: list[str] | None = None,
        recursion_depth: int = 0,
    ) -> list[str]:
        """Dispatch one normalized battle event to pages and special states.

        Hook handlers all receive the same ``EffectExecutionContext``. The
        owner remains ``actor_id`` for backwards-compatible page/status
        handlers; the skill actor and hit targets are available through the
        snapshot plus ``_event_actor_id``/``_event_target_ids`` parameters.
        """
        output = messages if messages is not None else []
        candidates: list[
            tuple[int, str, dict[str, Any], dict[str, Any], str, str, int]
        ] = []

        page_rows = connection.execute(
            """
            SELECT ap.character_id AS owner_id,ap.page_id,p.handler_key,
                   p.name AS source_name,p.params_json,ap.state_json,c.current_hp
            FROM battle_active_pages ap
            JOIN abnormality_pages p ON p.id=ap.page_id
            JOIN characters c ON c.id=ap.character_id
            JOIN battle_participants bp
              ON bp.battle_id=ap.battle_id AND bp.character_id=ap.character_id
            WHERE ap.battle_id=? AND bp.active_in_stage=1
              AND p.enabled=1 AND p.handler_key IS NOT NULL
            ORDER BY ap.activated_at,p.id
            """,
            (battle_id,),
        ).fetchall()
        for row in page_rows:
            if row["current_hp"] <= 0 and not (
                event in {BattleEvent.AFTER_DAMAGE, BattleEvent.KILL}
                and int(row["owner_id"]) in event_target_ids
            ):
                continue
            base_params = _loads(row["params_json"], {})
            source_params = dict(base_params)
            source_params.update(_loads(row["state_json"], {}))
            candidates.append(
                (
                    int(row["owner_id"]), str(row["handler_key"]),
                    base_params, source_params, BattleEvent.TURN_START.value,
                    "PAGE", int(row["page_id"]), str(row["source_name"]),
                )
            )

        status_rows = connection.execute(
            """
            SELECT e.id AS effect_id,e.character_id AS owner_id,e.params_json,
                   d.handler_key,d.name AS source_name,c.current_hp
            FROM active_effects e
            JOIN effect_definitions d ON d.effect_key=e.effect_key
            JOIN characters c ON c.id=e.character_id
            JOIN battle_participants bp
              ON bp.battle_id=e.battle_id AND bp.character_id=e.character_id
            WHERE e.battle_id=? AND bp.active_in_stage=1
              AND e.category='SPECIAL'
              AND d.enabled=1 AND d.handler_key IS NOT NULL
            ORDER BY e.id
            """,
            (battle_id,),
        ).fetchall()
        for row in status_rows:
            if row["current_hp"] <= 0 and not (
                event in {BattleEvent.AFTER_DAMAGE, BattleEvent.KILL}
                and int(row["owner_id"]) in event_target_ids
            ):
                continue
            candidates.append(
                (
                    int(row["owner_id"]), str(row["handler_key"]), {},
                    _loads(row["params_json"], {}), BattleEvent.TURN_END.value,
                    "STATUS", int(row["effect_id"]), str(row["source_name"]),
                )
            )

        for (
            owner_id,
            handler_key,
            base_params,
            source_params,
            default_event,
            source_kind,
            source_id,
            source_name,
        ) in candidates:
            if not self._hook_subscribes(source_params, event.value, default_event):
                continue
            if not self._hook_subject_matches(
                source_params,
                owner_id,
                event,
                event_actor_id,
                event_target_ids,
            ):
                continue
            params = dict(source_params)
            params.update(
                _hook=event.value,
                _hook_owner_id=owner_id,
                _event_actor_id=event_actor_id,
                _event_target_ids=list(event_target_ids),
            )
            target_mode = str(params.get("context_targets", "OWNER")).upper()
            if target_mode == "EVENT_TARGETS":
                context_target_ids = list(event_target_ids)
            elif target_mode == "EVENT_ACTOR" and event_actor_id is not None:
                context_target_ids = [event_actor_id]
            else:
                context_target_ids = [owner_id]
            emitted_from = len(output)
            self.registry.execute(
                handler_key,
                EffectExecutionContext(
                    engine=self,
                    connection=connection,
                    battle_id=battle_id,
                    actor_id=owner_id,
                    target_ids=context_target_ids,
                    params=params,
                    snapshot=snapshot,
                    messages=output,
                    recursion_depth=recursion_depth,
                    event=event.value,
                    hook_owner_id=owner_id,
                ),
            )
            # 被动产生了播报时，先标注触发来源（2026-07-27 反馈）。
            if len(output) > emitted_from and source_name:
                output.insert(emitted_from, f"◇ 「{source_name}」触发：")
            persisted = {
                key: value for key, value in params.items() if not str(key).startswith("_")
            }
            if source_kind == "STATUS":
                connection.execute(
                    "UPDATE active_effects SET params_json=? WHERE id=?",
                    (_dumps(persisted), source_id),
                )
            else:
                state = {
                    key: value
                    for key, value in persisted.items()
                    if key not in base_params or base_params[key] != value
                }
                connection.execute(
                    """
                    UPDATE battle_active_pages SET state_json=?
                    WHERE battle_id=? AND character_id=? AND page_id=?
                    """,
                    (_dumps(state), battle_id, owner_id, source_id),
                )
        return output

    @staticmethod
    def _hook_subscribes(
        params: dict[str, Any], event: str, default_event: str
    ) -> bool:
        configured = params.get("events", params.get("event"))
        if configured is None:
            configured = [default_event]
        elif isinstance(configured, str):
            configured = [configured]
        if not isinstance(configured, list):
            return False
        return event in {str(item).upper() for item in configured}

    @staticmethod
    def _hook_subject_matches(
        params: dict[str, Any],
        owner_id: int,
        event: BattleEvent,
        event_actor_id: int | None,
        event_target_ids: list[int],
    ) -> bool:
        if event in {BattleEvent.TURN_START, BattleEvent.TURN_END}:
            return True
        subject = str(params.get("event_subject", "OWNER_ACTOR")).upper()
        if subject == "ANY":
            return True
        if subject == "OWNER_TARGET":
            return owner_id in event_target_ids
        if subject == "OWNER_INVOLVED":
            return owner_id == event_actor_id or owner_id in event_target_ids
        return owner_id == event_actor_id

    def _deal_status_damage(
        self,
        connection: sqlite3.Connection,
        battle_id: int,
        effect: sqlite3.Row,
        damage: int,
        messages: list[str],
        source_name: str,
        *,
        recursion_depth: int = 0,
    ) -> BattleEventSnapshot | None:
        """Resolve regular fixed damage as its own non-skill event.

        It never reduces stagger and never feeds the originating skill's POST
        snapshot. Pages/special states can still observe ON_AFTER_DAMAGE and
        ON_KILL, including a lethal-damage immunity that restores HP before the
        final death decision.
        """
        target = self._character(connection, int(effect["character_id"]))
        if int(target["current_hp"]) <= 0:
            return None
        source_character_id = (
            int(effect["source_character_id"])
            if effect["source_character_id"] is not None
            else None
        )
        source_skill_id = (
            int(effect["source_skill_id"])
            if effect["source_skill_id"] is not None
            else None
        )
        event_messages: list[str] = []
        snapshot = BattleEventSnapshot(
            battle_id=battle_id,
            actor_id=source_character_id,
            skill_id=source_skill_id,
            skill_target_ids=[int(target["id"])],
            messages=event_messages,
            metadata={
                "damage_source": "STATUS",
                "source_key": effect["effect_key"],
                "damage_total": 0,
                "healing_total": 0,
                "positive_coins": 0,
                "negative_coins": 0,
            },
        )
        old_hp = int(target["current_hp"])
        requested = max(0, int(damage))
        self._fixed_damage(
            connection,
            int(target["id"]),
            requested,
            event_messages,
            source_name,
            announce_defeat=False,
        )
        dealt = min(old_hp, requested)
        hit = HitSnapshot(
            behavior_id=None,
            hit_index=1,
            target_id=int(target["id"]),
            hit=False,
            damage=dealt,
            target_faction=Faction(target["faction"]),
            damage_source="STATUS",
            source_key=str(effect["effect_key"]),
            source_character_id=source_character_id,
        )
        snapshot.hits.append(hit)
        snapshot.metadata["damage_total"] = dealt
        self._dispatch_hooks(
            connection,
            battle_id,
            BattleEvent.AFTER_DAMAGE,
            event_actor_id=source_character_id,
            event_target_ids=[int(target["id"])],
            snapshot=snapshot,
            messages=event_messages,
            recursion_depth=recursion_depth,
        )
        final_target = self._character(connection, int(target["id"]))
        killed = old_hp > 0 and int(final_target["current_hp"]) <= 0
        hit.killed = killed
        if killed:
            hit.killer_id = source_character_id
            snapshot.killed_character_ids.append(int(target["id"]))
            event_messages.append(self.narrator.defeated(target["name"]))
            self._dispatch_hooks(
                connection,
                battle_id,
                BattleEvent.KILL,
                event_actor_id=source_character_id,
                event_target_ids=[int(target["id"])],
                snapshot=snapshot,
                messages=event_messages,
                recursion_depth=recursion_depth,
            )
        messages.extend(event_messages)
        self._log(
            connection,
            battle_id,
            "STATUS_DAMAGE",
            actor_id=source_character_id,
            target_id=int(target["id"]),
            skill_id=source_skill_id,
            payload={"snapshot": asdict(snapshot)},
            message="\n".join(event_messages),
        )
        return snapshot

    def _fixed_damage(
        self,
        connection: sqlite3.Connection,
        character_id: int,
        damage: int,
        messages: list[str],
        source_name: str,
        *,
        announce_defeat: bool = True,
    ) -> int:
        character = self._character(connection, character_id)
        damage = max(0, int(damage))
        new_hp = max(0, int(character["current_hp"]) - damage)
        connection.execute("UPDATE characters SET current_hp=? WHERE id=?", (new_hp, character_id))
        messages.append(self.narrator.fixed_damage(character["name"], source_name, damage))
        if announce_defeat and character["current_hp"] > 0 and new_hp == 0:
            messages.append(self.narrator.defeated(character["name"]))
        return new_hp

    @staticmethod
    def _consume_regular_stack(connection: sqlite3.Connection, effect: sqlite3.Row) -> None:
        remaining = max(0, int(effect["stacks"]) - 1)
        if remaining == 0:
            connection.execute("DELETE FROM active_effects WHERE id=?", (effect["id"],))
        else:
            connection.execute(
                "UPDATE active_effects SET stacks=? WHERE id=?", (remaining, effect["id"])
            )

    @staticmethod
    def _active_effect(
        connection: sqlite3.Connection, battle_id: int, character_id: int, effect_key: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT * FROM active_effects
            WHERE battle_id=? AND character_id=? AND effect_key=?
            """,
            (battle_id, character_id, effect_key),
        ).fetchone()

    def _effect_intensity(
        self, connection: sqlite3.Connection, battle_id: int, character_id: int, effect_key: str
    ) -> int:
        row = self._active_effect(connection, battle_id, character_id, effect_key)
        return int(row["intensity"]) if row else 0

    @staticmethod
    def _character(connection: sqlite3.Connection, character_id: int) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM characters WHERE id=?", (character_id,)).fetchone()
        if row is None:
            raise BattleRuleError(f"角色 #{character_id} 不存在。")
        return row

    @staticmethod
    def _battle(connection: sqlite3.Connection, battle_id: int) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM battles WHERE id=?", (battle_id,)).fetchone()
        if row is None:
            raise BattleRuleError("战斗记录不存在。")
        return row

    @staticmethod
    def _active_battle(connection: sqlite3.Connection) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM battles WHERE status='ACTIVE'").fetchone()
        if row is None:
            raise BattleRuleError("当前没有正在展开的战斗。")
        return row

    @staticmethod
    def _is_active_participant(connection: sqlite3.Connection, character_id: int) -> bool:
        return bool(
            connection.execute(
                """
                SELECT 1 FROM battle_participants bp JOIN battles b ON b.id=bp.battle_id
                WHERE b.status='ACTIVE' AND bp.character_id=? AND bp.active_in_stage=1
                """,
                (character_id,),
            ).fetchone()
        )

    @staticmethod
    def _cooldown(
        connection: sqlite3.Connection, battle_id: int, character_id: int, skill_id: int
    ) -> int:
        row = connection.execute(
            """
            SELECT remaining FROM battle_skill_cooldowns
            WHERE battle_id=? AND character_id=? AND skill_id=?
            """,
            (battle_id, character_id, skill_id),
        ).fetchone()
        return int(row["remaining"]) if row else 0

    @staticmethod
    def _skill_uses(
        connection: sqlite3.Connection, battle_id: int, character_id: int, skill_id: int
    ) -> int:
        row = connection.execute(
            """
            SELECT uses FROM battle_skill_usage
            WHERE battle_id=? AND character_id=? AND skill_id=?
            """,
            (battle_id, character_id, skill_id),
        ).fetchone()
        return int(row["uses"]) if row else 0

    @staticmethod
    def _ego_used(connection: sqlite3.Connection, battle_id: int, character_id: int) -> bool:
        row = connection.execute(
            "SELECT ego_used FROM battle_ego_usage WHERE battle_id=? AND character_id=?",
            (battle_id, character_id),
        ).fetchone()
        return bool(row and row["ego_used"])

    @staticmethod
    def _living_count(
        connection: sqlite3.Connection, battle_id: int, faction: Faction
    ) -> int:
        return int(
            connection.execute(
                """
                SELECT COUNT(*) FROM characters c
                JOIN battle_participants bp ON bp.character_id=c.id
                WHERE bp.battle_id=? AND bp.active_in_stage=1
                  AND bp.faction=? AND c.current_hp>0
                """,
                (battle_id, faction.value),
            ).fetchone()[0]
        )

    @staticmethod
    def _log(
        connection: sqlite3.Connection,
        battle_id: int,
        event_type: str,
        *,
        actor_id: int | None = None,
        target_id: int | None = None,
        skill_id: int | None = None,
        payload: dict[str, Any] | None = None,
        message: str = "",
    ) -> None:
        battle = connection.execute("SELECT current_turn,phase FROM battles WHERE id=?", (battle_id,)).fetchone()
        connection.execute(
            """
            INSERT INTO battle_logs(
                battle_id,turn_number,phase,event_type,actor_id,target_id,skill_id,payload_json,message
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                battle_id, battle["current_turn"], battle["phase"], event_type,
                actor_id, target_id, skill_id, _dumps(payload or {}), message,
            ),
        )
