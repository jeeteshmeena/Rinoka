# Terminology

Repository of short (term - meaning) lines describing the domain language of Rinoka.

## Domain
- **Plugin** — a class (subclass of `rinoka.plugin.Plugin`) bundling a set of commands/listeners for a feature area.
- **Command** — a bot command (e.g. `/ban`) declared via the `filters` decorator; has a name, aliases, and an async handler taking a `Context`.
- **Listener** — an async event handler registered for a Pyrogram update type via the `listener` decorator.
- **Context** — the command invocation object passed to command handlers (wraps the incoming `Message`).
- **CustomFilter** — a callable predicate used to gate commands/listeners by permissions or message shape.
- **ChatAction / BotAction** — Telegram chat-action ("typing…") wrappers; `BotAction` is an async context manager in `rinoka/action.py`.
- **Honeypot / SPAM** — a honeypot/interaction requirement; `spam_shield` implements a spam-protection layer.
- **Federation** — a cross-chat shared affordance system grouping several chats under one federation for shared bans/rules.

## Technical / Project
- **Mixin** — a mixin base class in `rinoka/core/` composed into the single `Rinoka` class via MRO (e.g. `CommandDispatcher`, `EventDispatcher`).
- **Dispatcher** — a component that registers/forwards commands (`CommandDispatcher`) or events/listeners (`EventDispatcher`).
- **PluginExtenter** — the mixin responsible for loading/unloading/reloading plugin packages.
- **Storage / SQLiteStorage** — a Pyrogram storage backend persisted to SQLite (`rinoka/core/sqlite_storage.py`) for session/auth/peer data.
- **DatabaseProvider** — the mixin wrapping the MongoDB connection/database access for domain data.
- **i18n** — internationalization; localized strings are YAML files in `rinoka/language/` keyed by locale (`en`, `id`, `de`).
- **canonical** — an internal plugin providing canonical/standardized data or IDs.
- **Lode** — this structured markdown knowledge base; the AI's persistent project memory.