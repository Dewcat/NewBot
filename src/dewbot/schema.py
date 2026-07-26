from __future__ import annotations


SCHEMA_V1 = r"""
CREATE TABLE content_packs (
    pack_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    checksum TEXT NOT NULL,
    loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE effect_definitions (
    effect_key TEXT PRIMARY KEY,
    pack_key TEXT NOT NULL REFERENCES content_packs(pack_key),
    name TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('REGULAR','GENERIC','SPECIAL','INSTANT')),
    description TEXT NOT NULL DEFAULT '',
    icon TEXT NOT NULL DEFAULT '',
    handler_key TEXT,
    default_params_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_key TEXT NOT NULL UNIQUE,
    pack_key TEXT NOT NULL REFERENCES content_packs(pack_key),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    skill_type TEXT NOT NULL DEFAULT 'NORMAL' CHECK(skill_type IN ('NORMAL','EGO')),
    base_cooldown INTEGER NOT NULL DEFAULT 0 CHECK(base_cooldown >= 0),
    emotion_requirement INTEGER NOT NULL DEFAULT 0 CHECK(emotion_requirement BETWEEN 0 AND 5),
    target_scope TEXT NOT NULL CHECK(target_scope IN ('SELF','FRIENDLY','ENEMY','ALL')),
    target_method TEXT NOT NULL CHECK(target_method IN ('SELF','SELECT_TARGET','ALL_TARGETS','RANDOM')),
    target_param INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(target_method != 'RANDOM' OR target_param > 0),
    CHECK(target_method != 'SELF' OR target_scope = 'SELF')
);

CREATE TABLE skill_behaviors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    behavior_key TEXT NOT NULL UNIQUE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    timing TEXT NOT NULL CHECK(timing IN ('TURN_START','PRE','ON','POST','TURN_END')),
    trigger_condition TEXT NOT NULL DEFAULT 'ALWAYS',
    trigger_scope TEXT NOT NULL DEFAULT 'PER_SKILL' CHECK(trigger_scope IN ('PER_SKILL','PER_TARGET','PER_HIT')),
    target_source TEXT NOT NULL DEFAULT 'INHERIT_SKILL' CHECK(target_source IN ('INHERIT_SKILL','AUTO')),
    target_scope TEXT CHECK(target_scope IN ('SELF','FRIENDLY','ENEMY','ALL')),
    target_method TEXT CHECK(target_method IN ('SELF','ALL_TARGETS','RANDOM')),
    target_param INTEGER,
    effect_type TEXT NOT NULL CHECK(effect_type IN ('DAMAGE','HEAL','APPLY_EFFECT','SPECIAL')),
    effect_key TEXT REFERENCES effect_definitions(effect_key),
    effect_value TEXT,
    effect_params_json TEXT NOT NULL DEFAULT '{}',
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    CHECK(target_source != 'AUTO' OR (target_scope IS NOT NULL AND target_method IS NOT NULL))
);

CREATE INDEX idx_skill_behaviors_execution
    ON skill_behaviors(skill_id, timing, sort_order, id);

CREATE TABLE character_templates (
    template_key TEXT PRIMARY KEY,
    pack_key TEXT NOT NULL REFERENCES content_packs(pack_key),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_core INTEGER NOT NULL DEFAULT 0 CHECK(is_core IN (0,1)),
    max_hp INTEGER NOT NULL CHECK(max_hp > 0),
    max_actions INTEGER NOT NULL DEFAULT 1 CHECK(max_actions > 0),
    max_stagger INTEGER NOT NULL CHECK(max_stagger > 0),
    tags_json TEXT NOT NULL DEFAULT '[]',
    ego_skill_id INTEGER REFERENCES skills(id),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE personas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_key TEXT NOT NULL UNIQUE,
    pack_key TEXT NOT NULL REFERENCES content_packs(pack_key),
    template_key TEXT NOT NULL REFERENCES character_templates(template_key) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    hp_modifier INTEGER NOT NULL DEFAULT 0,
    actions_modifier INTEGER NOT NULL DEFAULT 0,
    stagger_modifier INTEGER NOT NULL DEFAULT 0,
    is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0,1)),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))
);

CREATE UNIQUE INDEX idx_personas_one_default
    ON personas(template_key) WHERE is_default = 1;

CREATE TABLE persona_skills (
    persona_id INTEGER NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    slot_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(persona_id, skill_id)
);

CREATE TABLE template_skills (
    template_key TEXT NOT NULL REFERENCES character_templates(template_key) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    slot_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(template_key, skill_id)
);

CREATE TABLE abnormalities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    abnormality_key TEXT NOT NULL UNIQUE,
    pack_key TEXT NOT NULL REFERENCES content_packs(pack_key),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))
);

CREATE TABLE abnormality_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_key TEXT NOT NULL UNIQUE,
    abnormality_id INTEGER NOT NULL REFERENCES abnormalities(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    page_type TEXT NOT NULL CHECK(page_type IN ('AWAKENING','BREAKDOWN')),
    description TEXT NOT NULL DEFAULT '',
    handler_key TEXT,
    params_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))
);

CREATE TABLE manager_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manager_skill_key TEXT NOT NULL UNIQUE,
    pack_key TEXT NOT NULL REFERENCES content_packs(pack_key),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    unlock_key TEXT,
    handler_key TEXT NOT NULL,
    max_uses_per_battle INTEGER NOT NULL DEFAULT 1 CHECK(max_uses_per_battle >= 0),
    allowed_phase TEXT,
    params_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))
);

CREATE TABLE manager_unlocks (
    unlock_key TEXT PRIMARY KEY,
    unlocked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_key TEXT NOT NULL REFERENCES character_templates(template_key),
    name TEXT NOT NULL,
    faction TEXT NOT NULL CHECK(faction IN ('FRIENDLY','ENEMY')),
    active_persona_id INTEGER REFERENCES personas(id),
    current_hp INTEGER NOT NULL,
    max_hp INTEGER NOT NULL,
    current_actions INTEGER NOT NULL,
    max_actions INTEGER NOT NULL,
    current_stagger INTEGER NOT NULL,
    max_stagger INTEGER NOT NULL,
    is_staggered INTEGER NOT NULL DEFAULT 0 CHECK(is_staggered IN (0,1)),
    stagger_turns INTEGER NOT NULL DEFAULT 0,
    emotion_level INTEGER NOT NULL DEFAULT 0 CHECK(emotion_level BETWEEN 0 AND 5),
    positive_emotion_coins INTEGER NOT NULL DEFAULT 0,
    negative_emotion_coins INTEGER NOT NULL DEFAULT 0,
    pending_emotion_upgrade INTEGER NOT NULL DEFAULT 0 CHECK(pending_emotion_upgrade IN (0,1)),
    emotion_bonus_actions INTEGER NOT NULL DEFAULT 0,
    tags_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_characters_faction ON characters(faction, current_hp);

CREATE TABLE battles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','COMPLETE')),
    current_stage INTEGER NOT NULL DEFAULT 1,
    total_stages INTEGER NOT NULL DEFAULT 1 CHECK(total_stages > 0),
    current_turn INTEGER NOT NULL DEFAULT 0,
    phase TEXT NOT NULL,
    result TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TEXT
);

CREATE UNIQUE INDEX idx_one_active_battle
    ON battles(status) WHERE status = 'ACTIVE';

CREATE TABLE battle_participants (
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    faction TEXT NOT NULL CHECK(faction IN ('FRIENDLY','ENEMY')),
    active_in_stage INTEGER NOT NULL DEFAULT 1 CHECK(active_in_stage IN (0,1)),
    stage_joined INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(battle_id, character_id)
);

CREATE INDEX idx_participants_active
    ON battle_participants(battle_id, faction, active_in_stage);

CREATE TABLE battle_skill_cooldowns (
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    skill_id INTEGER NOT NULL REFERENCES skills(id),
    remaining INTEGER NOT NULL DEFAULT 0 CHECK(remaining >= 0),
    PRIMARY KEY(battle_id, character_id, skill_id)
);

CREATE TABLE battle_ego_usage (
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    ego_used INTEGER NOT NULL DEFAULT 0 CHECK(ego_used IN (0,1)),
    used_skill_id INTEGER REFERENCES skills(id),
    used_at TEXT,
    PRIMARY KEY(battle_id, character_id)
);

CREATE TABLE active_effects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    effect_key TEXT NOT NULL REFERENCES effect_definitions(effect_key),
    category TEXT NOT NULL CHECK(category IN ('REGULAR','GENERIC','SPECIAL')),
    intensity INTEGER NOT NULL DEFAULT 0,
    stacks INTEGER NOT NULL DEFAULT 0,
    remaining_turns INTEGER,
    params_json TEXT NOT NULL DEFAULT '{}',
    source_character_id INTEGER REFERENCES characters(id),
    source_skill_id INTEGER REFERENCES skills(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(battle_id, character_id, effect_key)
);

CREATE INDEX idx_active_effects_character
    ON active_effects(battle_id, character_id, category);

CREATE TABLE battle_pending_effects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    effect_key TEXT NOT NULL REFERENCES effect_definitions(effect_key),
    category TEXT NOT NULL CHECK(category IN ('REGULAR','GENERIC','SPECIAL','INSTANT')),
    intensity INTEGER NOT NULL DEFAULT 0,
    stacks INTEGER NOT NULL DEFAULT 0,
    activate_at TEXT NOT NULL DEFAULT 'NEXT_TURN_START',
    params_json TEXT NOT NULL DEFAULT '{}',
    source_snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_pending_effects_activation
    ON battle_pending_effects(battle_id, activate_at, character_id);

CREATE TABLE battle_registered_behaviors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    behavior_id INTEGER NOT NULL REFERENCES skill_behaviors(id) ON DELETE CASCADE,
    owner_character_id INTEGER REFERENCES characters(id),
    source_type TEXT NOT NULL CHECK(source_type IN ('SKILL','PAGE','STATUS','MANAGER')),
    source_key TEXT NOT NULL,
    active_from TEXT NOT NULL,
    remaining_turns INTEGER,
    remaining_triggers INTEGER,
    lifecycle_scope TEXT NOT NULL DEFAULT 'TURN' CHECK(lifecycle_scope IN ('TURN','STAGE','BATTLE')),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','ACTIVE','EXHAUSTED')),
    target_snapshot_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE battle_abnormalities (
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    abnormality_id INTEGER NOT NULL REFERENCES abnormalities(id),
    PRIMARY KEY(battle_id, abnormality_id)
);

CREATE TABLE battle_page_pool (
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    page_id INTEGER NOT NULL REFERENCES abnormality_pages(id),
    status TEXT NOT NULL DEFAULT 'AVAILABLE' CHECK(status IN ('AVAILABLE','USED')),
    PRIMARY KEY(battle_id, page_id)
);

CREATE TABLE battle_page_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    offer_group TEXT NOT NULL,
    page_id INTEGER NOT NULL REFERENCES abnormality_pages(id),
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CHOSEN','EXPIRED')),
    offered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE battle_active_pages (
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    page_id INTEGER NOT NULL REFERENCES abnormality_pages(id),
    activated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(battle_id, character_id, page_id)
);

CREATE TABLE manager_skill_usage (
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    manager_skill_id INTEGER NOT NULL REFERENCES manager_skills(id),
    uses INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(battle_id, manager_skill_id)
);

CREATE TABLE emotion_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    event_type TEXT NOT NULL,
    positive_delta INTEGER NOT NULL DEFAULT 0,
    negative_delta INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE battle_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    turn_number INTEGER NOT NULL,
    phase TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_id INTEGER REFERENCES characters(id),
    target_id INTEGER REFERENCES characters(id),
    skill_id INTEGER REFERENCES skills(id),
    payload_json TEXT NOT NULL DEFAULT '{}',
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_battle_logs_timeline
    ON battle_logs(battle_id, turn_number, id);
"""


SCHEMA_V2 = r"""
ALTER TABLE template_skills ADD COLUMN pack_key TEXT REFERENCES content_packs(pack_key);

UPDATE template_skills
SET pack_key=(
    SELECT t.pack_key FROM character_templates t
    WHERE t.template_key=template_skills.template_key
)
WHERE pack_key IS NULL;

CREATE INDEX idx_template_skills_pack ON template_skills(pack_key);

CREATE TABLE character_ego_skills (
    template_key TEXT NOT NULL REFERENCES character_templates(template_key) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    pack_key TEXT NOT NULL REFERENCES content_packs(pack_key),
    slot_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(template_key, skill_id)
);

CREATE INDEX idx_character_ego_skills_pack ON character_ego_skills(pack_key);

ALTER TABLE battle_active_pages ADD COLUMN state_json TEXT NOT NULL DEFAULT '{}';
"""


SCHEMA_V3 = r"""
CREATE TABLE content_pack_dependencies (
    pack_key TEXT NOT NULL REFERENCES content_packs(pack_key) ON DELETE CASCADE,
    required_pack_key TEXT NOT NULL REFERENCES content_packs(pack_key),
    min_version TEXT,
    PRIMARY KEY(pack_key, required_pack_key),
    CHECK(pack_key != required_pack_key)
);

CREATE INDEX idx_content_dependencies_required
    ON content_pack_dependencies(required_pack_key);
"""


SCHEMA_V4 = r"""
CREATE TABLE battle_content_versions (
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    pack_key TEXT NOT NULL,
    version TEXT NOT NULL,
    checksum TEXT NOT NULL,
    PRIMARY KEY(battle_id, pack_key)
);
"""


SCHEMA_V5 = r"""
ALTER TABLE skills ADD COLUMN max_uses_per_battle INTEGER
    CHECK(max_uses_per_battle IS NULL OR max_uses_per_battle > 0);

CREATE TABLE battle_skill_usage (
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    skill_id INTEGER NOT NULL REFERENCES skills(id),
    uses INTEGER NOT NULL DEFAULT 0 CHECK(uses >= 0),
    PRIMARY KEY(battle_id, character_id, skill_id)
);
"""


SCHEMA_V6 = r"""
CREATE TABLE character_roles (
    role_key TEXT PRIMARY KEY,
    pack_key TEXT NOT NULL REFERENCES content_packs(pack_key),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    max_hp INTEGER NOT NULL CHECK(max_hp > 0),
    max_actions INTEGER NOT NULL DEFAULT 1 CHECK(max_actions > 0),
    max_stagger INTEGER NOT NULL CHECK(max_stagger > 0),
    tags_json TEXT NOT NULL DEFAULT '[]',
    ego_skill_id INTEGER REFERENCES skills(id),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE characters ADD COLUMN role_key TEXT REFERENCES character_roles(role_key);
ALTER TABLE characters ADD COLUMN ego_skill_id INTEGER REFERENCES skills(id);
ALTER TABLE personas ADD COLUMN role_key TEXT;

CREATE INDEX idx_characters_role ON characters(role_key, faction);
CREATE INDEX idx_personas_role ON personas(role_key, enabled);
"""


SCHEMA_V7 = r"""
CREATE TEMP TABLE _v7_persona_owner (
    persona_id INTEGER PRIMARY KEY,
    character_id INTEGER
);

INSERT INTO _v7_persona_owner(persona_id,character_id)
SELECT p.id,
       COALESCE(
           (SELECT c.id FROM characters c
            WHERE p.role_key IS NOT NULL AND c.role_key=p.role_key
            ORDER BY c.id LIMIT 1),
           (SELECT c.id FROM characters c
            WHERE p.template_key IS NOT NULL AND c.template_key=p.template_key
            ORDER BY CASE WHEN c.role_key IS NOT NULL THEN 0 ELSE 1 END,c.id LIMIT 1)
       )
FROM personas p;

CREATE TABLE characters_v7 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_key TEXT REFERENCES character_templates(template_key),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    faction TEXT NOT NULL CHECK(faction IN ('FRIENDLY','ENEMY')),
    is_core INTEGER NOT NULL DEFAULT 0 CHECK(is_core IN (0,1)),
    content_pack_key TEXT REFERENCES content_packs(pack_key),
    ego_skill_id INTEGER REFERENCES skills(id),
    active_persona_id INTEGER REFERENCES personas(id),
    current_hp INTEGER NOT NULL,
    max_hp INTEGER NOT NULL,
    current_actions INTEGER NOT NULL,
    max_actions INTEGER NOT NULL,
    current_stagger INTEGER NOT NULL,
    max_stagger INTEGER NOT NULL,
    is_staggered INTEGER NOT NULL DEFAULT 0 CHECK(is_staggered IN (0,1)),
    stagger_turns INTEGER NOT NULL DEFAULT 0,
    emotion_level INTEGER NOT NULL DEFAULT 0 CHECK(emotion_level BETWEEN 0 AND 5),
    positive_emotion_coins INTEGER NOT NULL DEFAULT 0,
    negative_emotion_coins INTEGER NOT NULL DEFAULT 0,
    pending_emotion_upgrade INTEGER NOT NULL DEFAULT 0 CHECK(pending_emotion_upgrade IN (0,1)),
    emotion_bonus_actions INTEGER NOT NULL DEFAULT 0,
    tags_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(
        (is_core=1 AND template_key IS NULL AND faction='FRIENDLY'
            AND content_pack_key IS NOT NULL)
        OR
        (is_core=0 AND template_key IS NOT NULL AND content_pack_key IS NULL
            AND ego_skill_id IS NULL AND active_persona_id IS NULL)
    )
);

INSERT INTO characters_v7(
    id,template_key,name,description,faction,is_core,content_pack_key,ego_skill_id,
    active_persona_id,current_hp,max_hp,current_actions,max_actions,current_stagger,
    max_stagger,is_staggered,stagger_turns,emotion_level,positive_emotion_coins,
    negative_emotion_coins,pending_emotion_upgrade,emotion_bonus_actions,tags_json,
    metadata_json,created_at
)
SELECT c.id,
       CASE WHEN c.role_key IS NOT NULL THEN NULL ELSE c.template_key END,
       c.name,COALESCE(r.description,''),c.faction,
       CASE WHEN c.role_key IS NOT NULL THEN 1 ELSE 0 END,
       r.pack_key,CASE WHEN c.role_key IS NOT NULL
                       THEN COALESCE(c.ego_skill_id,r.ego_skill_id) ELSE NULL END,
       CASE WHEN c.role_key IS NOT NULL THEN c.active_persona_id ELSE NULL END,
       c.current_hp,c.max_hp,c.current_actions,c.max_actions,c.current_stagger,
       c.max_stagger,c.is_staggered,c.stagger_turns,c.emotion_level,
       c.positive_emotion_coins,c.negative_emotion_coins,c.pending_emotion_upgrade,
       c.emotion_bonus_actions,c.tags_json,c.metadata_json,c.created_at
FROM characters c
LEFT JOIN character_roles r ON r.role_key=c.role_key;

DROP TABLE characters;
ALTER TABLE characters_v7 RENAME TO characters;

CREATE UNIQUE INDEX idx_one_core_character_name
    ON characters(name) WHERE is_core=1;
CREATE INDEX idx_characters_faction ON characters(faction,current_hp);
CREATE INDEX idx_characters_template ON characters(template_key,faction);

CREATE TABLE personas_v7 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_key TEXT NOT NULL UNIQUE,
    pack_key TEXT NOT NULL REFERENCES content_packs(pack_key),
    character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    max_hp INTEGER NOT NULL CHECK(max_hp > 0),
    max_actions INTEGER NOT NULL DEFAULT 1 CHECK(max_actions > 0),
    max_stagger INTEGER NOT NULL CHECK(max_stagger > 0),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0,1)),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))
);

INSERT INTO personas_v7(
    id,persona_key,pack_key,character_id,name,description,max_hp,max_actions,
    max_stagger,is_default,metadata_json,enabled
)
SELECT p.id,p.persona_key,p.pack_key,o.character_id,p.name,p.description,
       MAX(1,c.max_hp),MAX(1,c.max_actions),MAX(1,c.max_stagger),
       p.is_default,p.metadata_json,p.enabled
FROM personas p
JOIN _v7_persona_owner o ON o.persona_id=p.id AND o.character_id IS NOT NULL
JOIN characters c ON c.id=o.character_id;

DROP TABLE personas;
ALTER TABLE personas_v7 RENAME TO personas;

CREATE UNIQUE INDEX idx_personas_one_default
    ON personas(character_id) WHERE is_default=1;
CREATE INDEX idx_personas_character ON personas(character_id,enabled);

CREATE TRIGGER trg_character_persona_owner
BEFORE UPDATE OF active_persona_id ON characters
WHEN NEW.active_persona_id IS NOT NULL
 AND NOT EXISTS (
     SELECT 1 FROM personas p
     WHERE p.id=NEW.active_persona_id AND p.character_id=NEW.id AND p.enabled=1
 )
BEGIN
    SELECT RAISE(ABORT,'active persona does not belong to character');
END;

UPDATE characters
SET active_persona_id=NULL
WHERE active_persona_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM personas p
      WHERE p.id=characters.active_persona_id AND p.character_id=characters.id
  );

DELETE FROM template_skills
WHERE template_key IN (SELECT template_key FROM character_templates WHERE is_core=1);
DELETE FROM character_ego_skills
WHERE template_key IN (SELECT template_key FROM character_templates WHERE is_core=1);
DELETE FROM character_templates WHERE is_core=1;

CREATE TABLE character_templates_v7 (
    template_key TEXT PRIMARY KEY,
    pack_key TEXT NOT NULL REFERENCES content_packs(pack_key),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    max_hp INTEGER NOT NULL CHECK(max_hp > 0),
    max_actions INTEGER NOT NULL DEFAULT 1 CHECK(max_actions > 0),
    max_stagger INTEGER NOT NULL CHECK(max_stagger > 0),
    tags_json TEXT NOT NULL DEFAULT '[]',
    ego_skill_id INTEGER REFERENCES skills(id),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO character_templates_v7(
    template_key,pack_key,name,description,max_hp,max_actions,max_stagger,
    tags_json,ego_skill_id,metadata_json,enabled,updated_at
)
SELECT template_key,pack_key,name,description,max_hp,max_actions,max_stagger,
       tags_json,ego_skill_id,metadata_json,enabled,updated_at
FROM character_templates;

DROP TABLE character_templates;
ALTER TABLE character_templates_v7 RENAME TO character_templates;

DROP TABLE character_roles;
DROP TABLE _v7_persona_owner;
"""


SCHEMA_V8 = r"""
CREATE TABLE encounters (
    encounter_key TEXT PRIMARY KEY,
    pack_key TEXT NOT NULL REFERENCES content_packs(pack_key),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    abnormalities_json TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE encounter_stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_key TEXT NOT NULL REFERENCES encounters(encounter_key) ON DELETE CASCADE,
    stage_number INTEGER NOT NULL CHECK(stage_number > 0),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    UNIQUE(encounter_key,stage_number)
);

CREATE TABLE encounter_stage_enemies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_id INTEGER NOT NULL REFERENCES encounter_stages(id) ON DELETE CASCADE,
    template_key TEXT NOT NULL REFERENCES character_templates(template_key),
    amount INTEGER NOT NULL DEFAULT 1 CHECK(amount > 0),
    display_name TEXT,
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE battle_setups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_key TEXT NOT NULL REFERENCES encounters(encounter_key),
    status TEXT NOT NULL DEFAULT 'PREPARING'
        CHECK(status IN ('PREPARING','LAUNCHED','CANCELLED')),
    battle_id INTEGER UNIQUE REFERENCES battles(id),
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    launched_at TEXT
);

CREATE UNIQUE INDEX idx_one_preparing_battle_setup
    ON battle_setups(status) WHERE status='PREPARING';

CREATE TABLE battle_setup_friendlies (
    setup_id INTEGER NOT NULL REFERENCES battle_setups(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    persona_id INTEGER REFERENCES personas(id),
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(setup_id,character_id)
);

CREATE TABLE battle_setup_enemies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    setup_id INTEGER NOT NULL REFERENCES battle_setups(id) ON DELETE CASCADE,
    stage_number INTEGER NOT NULL CHECK(stage_number > 0),
    template_key TEXT NOT NULL REFERENCES character_templates(template_key),
    amount INTEGER NOT NULL DEFAULT 1 CHECK(amount > 0),
    display_name TEXT,
    source TEXT NOT NULL DEFAULT 'MANUAL' CHECK(source IN ('ENCOUNTER','MANUAL'))
);

CREATE INDEX idx_setup_enemies_stage
    ON battle_setup_enemies(setup_id,stage_number,id);
"""


SCHEMA_V9 = r"""
ALTER TABLE battle_setups ADD COLUMN name TEXT NOT NULL DEFAULT '';
ALTER TABLE battles ADD COLUMN name TEXT NOT NULL DEFAULT '';

UPDATE battle_setups
SET name=(
    SELECT e.name || ' #' || battle_setups.id
    FROM encounters e WHERE e.encounter_key=battle_setups.encounter_key
)
WHERE name='';

DROP INDEX idx_one_preparing_battle_setup;

CREATE TABLE battle_setup_selections (
    user_id INTEGER PRIMARY KEY,
    setup_id INTEGER NOT NULL REFERENCES battle_setups(id) ON DELETE CASCADE,
    selected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


SCHEMA_V10 = r"""
ALTER TABLE encounter_stages ADD COLUMN clear_condition_json TEXT NOT NULL
    DEFAULT '{"type":"ALL_ENEMIES_DEFEATED"}';
ALTER TABLE encounter_stages ADD COLUMN clear_outcome TEXT NOT NULL DEFAULT 'NEXT_STAGE'
    CHECK(clear_outcome IN ('NEXT_STAGE','VICTORY'));
ALTER TABLE battle_setup_enemies ADD COLUMN enemy_key TEXT;
ALTER TABLE encounter_stage_enemies ADD COLUMN enemy_key TEXT;

UPDATE battle_setup_enemies SET enemy_key='enemy_' || id WHERE enemy_key IS NULL;
UPDATE encounter_stage_enemies SET enemy_key='enemy_' || id WHERE enemy_key IS NULL;

CREATE TABLE battle_setups_v10 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    encounter_key TEXT NOT NULL REFERENCES encounters(encounter_key),
    status TEXT NOT NULL DEFAULT 'STANDBY'
        CHECK(status IN ('STANDBY','ACTIVE','COMPLETE','CANCELLED')),
    battle_id INTEGER UNIQUE REFERENCES battles(id),
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    launched_at TEXT,
    name TEXT NOT NULL DEFAULT ''
);

INSERT INTO battle_setups_v10(
    id,encounter_key,status,battle_id,created_by,created_at,launched_at,name
)
SELECT id,encounter_key,
       CASE status WHEN 'PREPARING' THEN 'STANDBY'
                   WHEN 'LAUNCHED' THEN 'ACTIVE'
                   ELSE status END,
       battle_id,created_by,created_at,launched_at,name
FROM battle_setups;

DROP TABLE battle_setups;
ALTER TABLE battle_setups_v10 RENAME TO battle_setups;

CREATE TABLE battle_spawn_origins (
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    stage_number INTEGER NOT NULL,
    enemy_key TEXT,
    setup_enemy_id INTEGER REFERENCES battle_setup_enemies(id),
    PRIMARY KEY(battle_id,character_id)
);
"""


SCHEMA_V11 = r"""
CREATE TABLE battle_setup_stages (
    setup_id INTEGER NOT NULL REFERENCES battle_setups(id) ON DELETE CASCADE,
    stage_number INTEGER NOT NULL CHECK(stage_number > 0),
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    clear_condition_json TEXT NOT NULL,
    clear_outcome TEXT NOT NULL CHECK(clear_outcome IN ('NEXT_STAGE','VICTORY')),
    PRIMARY KEY(setup_id,stage_number)
);

INSERT INTO battle_setup_stages(
    setup_id,stage_number,name,description,clear_condition_json,clear_outcome
)
SELECT bs.id,es.stage_number,es.name,es.description,
       es.clear_condition_json,es.clear_outcome
FROM battle_setups bs
JOIN encounter_stages es ON es.encounter_key=bs.encounter_key;
"""


SCHEMA_V12 = r"""
ALTER TABLE battle_setups ADD COLUMN abnormalities_json TEXT NOT NULL DEFAULT '[]';

UPDATE battle_setups
SET abnormalities_json=COALESCE(
    (SELECT e.abnormalities_json
     FROM encounters e
     WHERE e.encounter_key=battle_setups.encounter_key),
    '[]'
);
"""


SCHEMA_V13 = r"""
ALTER TABLE battle_setups ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;
"""


SCHEMA_V14 = r"""
CREATE TABLE battle_setup_selections_v14 (
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL DEFAULT 0,
    setup_id INTEGER NOT NULL REFERENCES battle_setups(id) ON DELETE CASCADE,
    selected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(user_id,chat_id)
);

INSERT INTO battle_setup_selections_v14(user_id,chat_id,setup_id,selected_at)
SELECT user_id,0,setup_id,selected_at FROM battle_setup_selections;

DROP TABLE battle_setup_selections;
ALTER TABLE battle_setup_selections_v14 RENAME TO battle_setup_selections;
"""


SCHEMA_V15 = r"""
CREATE TABLE chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_role TEXT NOT NULL CHECK(author_role IN ('gm','player')),
    kind TEXT NOT NULL CHECK(kind IN ('speech','narration')),
    speaker TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    edited_at TEXT,
    revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)),
    read_by_gm INTEGER NOT NULL DEFAULT 0 CHECK(read_by_gm IN (0,1)),
    read_by_player INTEGER NOT NULL DEFAULT 0 CHECK(read_by_player IN (0,1))
);

CREATE INDEX idx_chat_messages_created ON chat_messages(created_at,id);
"""


SCHEMA_V16 = r"""
CREATE TABLE player_page_deck (
    abnormality_key TEXT PRIMARY KEY,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE battle_setups ADD COLUMN published INTEGER NOT NULL DEFAULT 0;
"""


SCHEMA_V17 = r"""
ALTER TABLE battle_setups ADD COLUMN core_pool_json TEXT NOT NULL DEFAULT '[]';
"""


SCHEMA_V18 = r"""
CREATE TABLE abnormality_pages_v18 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_key TEXT NOT NULL UNIQUE,
    abnormality_id INTEGER NOT NULL REFERENCES abnormalities(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    page_type TEXT NOT NULL CHECK(page_type IN ('AWAKENING','BREAKDOWN','CARRY')),
    level INTEGER NOT NULL DEFAULT 1 CHECK(level BETWEEN 1 AND 3),
    description TEXT NOT NULL DEFAULT '',
    handler_key TEXT,
    params_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))
);

INSERT INTO abnormality_pages_v18(
    id,page_key,abnormality_id,name,page_type,level,description,
    handler_key,params_json,enabled
)
SELECT id,page_key,abnormality_id,name,page_type,1,description,
       handler_key,params_json,enabled
FROM abnormality_pages;

DROP TABLE abnormality_pages;
ALTER TABLE abnormality_pages_v18 RENAME TO abnormality_pages;

CREATE TABLE page_deck_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    abnormality_keys_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


SCHEMA_V19 = r"""
CREATE TABLE abnormality_access (
    abnormality_key TEXT PRIMARY KEY,
    opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO abnormality_access(abnormality_key)
SELECT abnormality_key FROM abnormalities WHERE enabled=1;
"""


SCHEMA_V20 = r"""
CREATE TABLE persona_access (
    persona_key TEXT PRIMARY KEY,
    opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO persona_access(persona_key)
SELECT persona_key FROM personas WHERE enabled=1;
"""


SCHEMA_V21 = r"""
ALTER TABLE battle_setup_enemies ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1;
"""


MIGRATIONS: tuple[tuple[int, str, str], ...] = (
    (1, "v2_initial_schema", SCHEMA_V1),
    (2, "content_extensions_and_page_state", SCHEMA_V2),
    (3, "content_pack_dependencies", SCHEMA_V3),
    (4, "battle_content_version_snapshot", SCHEMA_V4),
    (5, "per_battle_skill_usage", SCHEMA_V5),
    (6, "core_character_roles", SCHEMA_V6),
    (7, "direct_core_characters", SCHEMA_V7),
    (8, "encounter_battle_setup", SCHEMA_V8),
    (9, "named_selectable_battle_setups", SCHEMA_V9),
    (10, "standby_encounters_and_clear_conditions", SCHEMA_V10),
    (11, "snapshot_stages_per_battle_setup", SCHEMA_V11),
    (12, "snapshot_abnormalities_per_battle_setup", SCHEMA_V12),
    (13, "battle_setup_revision_guard", SCHEMA_V13),
    (14, "battle_setup_selection_per_chat", SCHEMA_V14),
    (15, "roleplay_chat_messages", SCHEMA_V15),
    (16, "player_page_deck_and_setup_publish", SCHEMA_V16),
    (17, "setup_core_pool", SCHEMA_V17),
    (18, "leveled_pages_carry_bonus_and_presets", SCHEMA_V18),
    (19, "abnormality_player_access", SCHEMA_V19),
    (20, "persona_player_access", SCHEMA_V20),
    (21, "setup_enemy_toggle", SCHEMA_V21),
)
