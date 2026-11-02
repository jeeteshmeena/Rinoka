# Architecture Overview

Rinoka is a single async Telegram bot composed from **mixin base classes** (Python MRO). There is no separate service split — one process, one `Rinoka` object.

```mermaid
graph TD
    A[main.py<br>start()] --> B[Rinoka<br>core/rinoka_bot.py]
    B --> C[TelegramBot<br>Pyrogram wiring]
    B --> D[DatabaseProvider<br>MongoDB]
    B --> E[SQLiteStorage<br>session/auth/peers]
    B --> F[PluginExtenter<br>load plugins]
    B --> G[CommandDispatcher<br>register/route commands]
    B --> H[EventDispatcher<br>register/route listeners]

    P[plugins/] --> F
    P --> G
    P --> H
    C --> MT[Telegram MTProto<br>Pyrofork]
    F --> IP[internal_plugins]
    F --> CP[custom_plugins]
```

## Composition (MRO)
`Rinoka(TelegramBot, DatabaseProvider, PluginExtenter, CommandDispatcher, EventDispatcher)`
- **TelegramBot** — owns the Pyrogram/Pyrofork client, `init_and_run`, `stop`.
- **DatabaseProvider** — wraps MongoDB connection/access for domain data.
- **PluginExtenter** — `load_plugin`, `unload_plugin`, `load_all_plugins`, `reload_plugin_pkg`.
- **CommandDispatcher** — `register_command(s)`, `unregister_command(s)`, `command_predicate`, `on_command`.
- **EventDispatcher** — `register_listener(s)`, `dispatch_event`, `dispatch_missed_events`, `dispatch_alert`, `log_stat`.

The core `Rinoka` class (`core/rinoka_bot.py`) is the canonical composed object; mixins reference `self: "Rinoka"` and are not instantiated standalone.

## Package Layout
```
rinoka/
├── core/           # Mixins: rinoka_bot, telegram_bot, command_dispatcher,
│                   #   event_dispatcher, database_provider, sqlite_storage,
│                   #   plugin_extenter, metrics, rinoka_mixin_base
├── plugins/        # 22 user-facing feature plugins
├── internal_plugins/  # canonical, health, spam_prediction
├── custom_plugins/    # user custom plugins
├── util/           # config, converter, tg, time, system, db, types, misc
├── language/       # en.yml, id.yml, de.yml
├── action.py       # BotAction async context manager
├── command.py      # filters decorator, Context, command types
├── plugin.py       # Plugin base class
├── listener.py     # Listener type
├── filters.py      # permission/context filters
└── main.py         # start()
```

## Key Invariants
- One `Rinoka` object; plugins are attached to it, never independent.
- Commands/listeners are registered declaratively via decorators at import/load time.
- All I/O (Telegram, MongoDB, SQLite) is async.
- Localized strings come from `language/*.yml`, never inline.

See [plugin-system.md](plugin-system.md) and [../core/bot-lifecycle.md](../core/bot-lifecycle.md).