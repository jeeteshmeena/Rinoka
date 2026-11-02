# Rinoka — Lode Summary

Rinoka is a modern, fully-asynchronous, class-based **Telegram group management bot** built on **Pyrogram/Pyrofork** (a Telegram MTProto client library). It is a community administration bot (usable in production as @dAnjani_bot) under active development by the UserbotIndo team.

## Key facts
- **Language:** Python 3.9+ (fully async with `async`/`await`).
- **Package:** `rinoka`, version 2.14.20, distributed on PyPI (`poetry`-managed).
- **Entry point:** `rinoka.main:start` (via `rinoka/main.py`).
- **Data stores:** MongoDB (primary domain data via `database_provider`), SQLite (Pyrogram session/storage via `SQLiteStorage`).
- **Key runtime deps:** `pyro`/`pyrofork`, `aiohttp`, `mongodb` driver, i18n (YAML locale files).

## Architecture
The bot is built as a **single `Rinoka` class** that composes several **mixin base classes** (Python MRO composition):
`Rinoka(TelegramBot, DatabaseProvider, PluginExtender, CommandDispatcher, EventDispatcher)`.

- **Core mixins** (in `rinoka/core/`): `rinoka_bot`, `telegram_bot`, `database_provider`, `plugin_extenter`, `command_dispatcher`, `event_dispatcher`, `sqlite_storage`, `metrics`, `rinoka_mixin_base`.
- **Plugin system:** a **class-based plugin** model (`rinoka/plugin.py::Plugin`). Plugins declare commands via decorators (`@command.filters(...)`) and listeners via `@listener(...)`. Dispatchers register/unregister them at load time.
- **CustomFilter & filters:** permission/context filters in `rinoka/filters.py` and `rinoka/util/types.py`.

## Plugin inventory
- `rinoka/plugins/` (22 files) — core user-facing modules: admins, backups, debug, federation, filters, language, lockings, main, misc, muting, notes, purge, reporting, restriction, rules, spam_shield, staff_tools, stats, topic, users, welcome.
- `rinoka/internal_plugins/` (4) — canonical, health, spam_prediction, and package root.
- `rinoka/custom_plugins/` (2) — user custom plugins.
- `rinoka/language/` — i18n strings: `en.yml`, `id.yml`, `de.yml`.

## Scale
~13,500 LOC in the main package (excluding tests). Tests are minimal: `test/test_base_converter.py`, `test/test_tg.py`.

See [architecture/summary.md](architecture/summary.md) for the layer diagram and [practices.md](practices.md) for conventions.