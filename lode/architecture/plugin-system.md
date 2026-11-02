# Plugin System

Rinoka's feature modules are **class-based plugins**. Understanding this model is essential for adding or modifying features.

## Plugin base
`rinoka/plugin.py` defines `class Plugin`:
- Class vars: `name: ClassVar[str]`, `disabled: ClassVar[bool]`, `helpable: ClassVar[bool]`.
- Instance: `self.bot` (the `Rinoka` object), `self.log`, `self.comment`.
- `__init__(self, bot)` sets up the logger; `get_text(chat_id, text_name, *args, **kwargs)` renders localized strings for the user's language.

Example:
```python
from rinoka import plugin

class MyFeature(plugin.Plugin):
    name = "myfeature"
    helpable = True

    async def on_message(self, ...):
        ...
```
(Concrete command/listener registration is via decorators — see below.)

## Commands
`rinoka/command.py` provides the `filters(...)` decorator:
```python
@command.filters(filters=CUSTOM_FILTER, aliases=["alias1"])
async def my_cmd(self, ctx: command.Context) -> Optional[str]:
    ...
```
- `filters` — a `CustomFilter`/Pyrogram filter gating access.
- `aliases` — additional command names.
- Handlers are `async`; they return `Optional[str]` (a reply string) or `None`.

## Listeners
`rinoka/listener.py` defines the `Listener` type. `EventDispatcher.register_listener` wires async handlers to Pyrogram update types. `dispatch_event` fans an update out to all matching listeners.

## Dispatchers
- **CommandDispatcher** (`core/command_dispatcher.py`): `register_command(s)`, `unregister_command(s)`, `command_predicate`, `on_command`. It builds a map of command name → handler and checks predicates before invoking.
- **EventDispatcher** (`core/event_dispatcher.py`): `register_listener(s)`, `unregister_listener(s)`, `dispatch_event`, `dispatch_missed_events`, `dispatch_alert`, `log_stat`.

## Loading
`PluginExtenter` (`core/plugin_extenter.py`):
- `load_plugin(plugin_cls)`, `unload_plugin`, `load_all_plugins`, `unload_all_plugins`, `reload_plugin_pkg`.
- Plugins are discovered from `plugins/`, `internal_plugins/`, and `custom_plugins/`.
- Registration happens at load time: plugin classes register their commands/listeners with the dispatchers.

## Link
- [architecture/summary.md](summary.md)
