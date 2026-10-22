from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Settings
from .content import ContentLoader
from .db import Database
from .engine import BattleEngine
from .models import BattleRuleError, Faction


def _runtime(settings: Settings) -> tuple[Database, ContentLoader, BattleEngine]:
    database = Database(settings.database_path)
    database.initialize()
    engine = BattleEngine(database)
    loader = ContentLoader(database, engine.registry.keys)
    return database, loader, engine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dewbot v2 管理工具")
    parser.add_argument("--database", type=Path, help="覆盖 DEWBOT_DB_PATH")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="初始化新版数据库")

    load = subparsers.add_parser("load-content", help="加载一个 JSON 内容包")
    load.add_argument("path", type=Path)

    subparsers.add_parser("templates", help="列出可用角色模板")

    spawn = subparsers.add_parser("spawn", help="从模板创建角色实例")
    spawn.add_argument("template_key")
    spawn.add_argument("faction", choices=[item.value for item in Faction])
    spawn.add_argument("--name")

    subparsers.add_parser("roster", help="列出角色实例")

    unlock = subparsers.add_parser("unlock-manager", help="登记剧情解锁")
    unlock.add_argument("unlock_key")
    unlock.add_argument("--metadata", default="{}", help="JSON 元数据")

    simulate = subparsers.add_parser("simulate", help="运行一回合最小烟雾测试")
    simulate.add_argument("--friendly", default="珏", help="核心角色名称")
    simulate.add_argument("--enemy", default="enemy.training_shell")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.database:
        settings = Settings(
            database_path=args.database.resolve(),
            content_paths=settings.content_paths,
            telegram_token=settings.telegram_token,
            telegram_proxy=settings.telegram_proxy,
            admin_ids=settings.admin_ids,
        )
    database, loader, engine = _runtime(settings)
    try:
        if args.command == "init-db":
            print(f"数据库已初始化：{database.path}")
        elif args.command == "load-content":
            print(loader.load_path(args.path))
            engine.validate_content_handlers()
        elif args.command == "templates":
            for item in engine.list_templates():
                print(f"{item['template_key']}\t{item['name']}\tHP {item['max_hp']}")
        elif args.command == "spawn":
            character_id = engine.spawn_character(args.template_key, args.faction, name=args.name)
            print(f"已创建角色 #{character_id}")
        elif args.command == "roster":
            for item in engine.list_characters():
                print(
                    f"#{item['id']} [{item['faction']}] {item['name']} "
                    f"HP {item['current_hp']}/{item['max_hp']}"
                )
        elif args.command == "unlock-manager":
            engine.unlock_manager_feature(args.unlock_key, json.loads(args.metadata))
            print(f"已登记剧情解锁：{args.unlock_key}")
        elif args.command == "simulate":
            for path in settings.content_paths:
                loader.load_path(path)
            engine.validate_content_handlers()
            friendly = int(engine.get_core_character(args.friendly)["id"])
            enemy = engine.spawn_character(args.enemy, Faction.ENEMY)
            _battle_id, messages = engine.start_battle([friendly], [enemy])
            print("\n".join(messages))
            if engine.battle_status()["phase"] == "ENEMY_PLANNING":
                enemy_skill = engine.list_skills(enemy, available_only=True)[0]
                print(engine.use_skill(enemy, enemy_skill["id"], [friendly]).text)
                print(engine.finish_enemy_planning())
            skill = engine.list_skills(friendly, available_only=True)[0]
            print(engine.use_skill(friendly, skill["id"], [enemy]).text)
            if engine.database.fetch_one("SELECT id FROM battles WHERE status='ACTIVE'"):
                if engine.battle_status()["phase"] == "FRIENDLY_ACTION":
                    print(engine.end_friendly_phase())
                if engine.battle_status()["phase"] == "ENEMY_ACTION":
                    print("\n".join(engine.end_turn()))
    except (BattleRuleError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
