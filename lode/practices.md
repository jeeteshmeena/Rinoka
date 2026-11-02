# Practices

Patterns, conventions, and workflows for Rinoka.

## 1. Project & Tooling
- Poetry-managed Python 3.9+ package; entry point `rinoka = "rinoka.main:start"`.
- Pre-commit hooks configured (`.pre-commit-config.yaml`); DeepSource lint configured (`.deepsource.toml`).
- GPL-3.0-or-later licensed.

## 2. Architecture & Composition
- The bot is a **single composition of mixins**: `class Rinoka(TelegramBot, DatabaseProvider, PluginExtenter, CommandDispatcher, EventDispatcher)`.
- Mixins live in `rinoka/core/` and each mixin methods reference `self: "Rinoka"`; they share the composed object.
- **Dependency direction:** plugins → bot mixins → Pyrogram/MongoDB/SQLite. Plugins never reach into raw clients directly; they go through the bot surface.

## 3. Plugin System
- Plugins are **classes**, one per file, named after the file's purpose, subclassing `Plugin` and setting `name`.
- Commands declared with the `@filters(...)` decorator (from `rinoka/command`), optional `aliases`.
- Event handling via `@listener(...)` decorators registered by `EventDispatcher`.
- Grouping convention: commands that form a feature area live in one plugin package; internal/canonical helpers go in `internal_plugins`.

## 4. Commands & Filters
- Command handlers are async, take a `Context`, and may return an optional string (sent as reply) or `None`.
- Gate access with `CustomFilter`s / `filters.py` helpers rather than checking inside handlers.
- Use `BotAction` (async context manager) for chat-action typing indicators.

## 5. Data & Storage
- **Domain data** → MongoDB via `DatabaseProvider`.
- **Session/auth/peer data** (Pyrogram storage) → `SQLiteStorage`.
- All DB/storage calls are async; never block the event loop.

## 6. i18n / Localization
- Human-facing strings live in `rinoka/language/{locale}.yml`, not inline in code.
- Provide `en.yml` as the canonical locale; add `id.yml`, `de.yml`, etc. alongside.
- Use the plugin's `get_text(...)`/text helpers to render localized strings with interpolation args.

## 7. Async & Concurrency
- Fully async: `async def` everywhere I/O happens; no sync network/DB calls.
- Long-running/background work should not block the dispatcher loop.

## 8. Code Quality
- Type-hinted API (mirrors the "easy to develop" design goal).
- Keep plugins self-contained and small; one concern per plugin.
- `test/` holds minimal unit tests (`test_base_converter.py`, `test_tg.py`); treat these as the seed for more.
