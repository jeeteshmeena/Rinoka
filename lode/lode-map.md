# Lode Map

Hierarchical index of all Lode files for Rinoka (Telegram group management bot).

## Root
- **[summary.md](summary.md)** — one-paragraph living snapshot of the whole system.
- **[terminology.md](terminology.md)** — domain language glossary.
- **[practices.md](practices.md)** — project patterns, conventions, and workflows.
- **lode-map.md** (this file) — index of all Lode files.

## architecture/
- **[architecture/summary.md](architecture/summary.md)** — bot architecture, mixin composition, plugin system.
- **[architecture/plugin-system.md](architecture/plugin-system.md)** — Plugin/Command/Listener model, decorators, dispatchers.

## core/
- **[core/bot-lifecycle.md](core/bot-lifecycle.md)** — Rinoka class, init_and_run, TelegramBot + Pyrogram wiring.
- **[core/storage.md](core/storage.md)** — SQLiteStorage, session/persistence, database_provider (MongoDB).

## plugins/
- **[plugins/index.md](plugins/index.md)** — inventory of plugin packages by category.

## util/
- **[util/helpers.md](util/helpers.md)** — rinoka/util helpers (config, converter, tg, time, system).

## plans/
- Current roadmap and active tasks.

## tmp/
- Session scraps (git-ignored). Do not persist permanent content here.