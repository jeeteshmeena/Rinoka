# Util Helpers

`rinoka/util/` holds shared helpers used across the bot.

## Files
| File | Purpose |
|------|---------|
| `config.py` | Config loading (env vars via `config.env_sample`). |
| `converter.py` | Value/data conversion helpers (time strings, sizes, etc.). |
| `tg.py` | Telegram helpers (`get_text`, message/entity utilities). |
| `time.py` | Time parsing/formatting helpers. |
| `system.py` | System/resource helpers (uptime, load). |
| `types.py` | Shared types incl. `CustomFilter`. |
| `misc.py` | Miscellaneous utilities. |
| `async_helper.py` | Async helper utilities. |
| `cache_limiter.py` | Cache/rate limiting. |
| `error.py` | Error types. |
| `db/` | DB utility helpers.

## Notable
- `CustomFilter` (in `util/types.py`) is the predicate type used to gate commands/listeners.
- `get_text` (in `util/tg.py`) is the string-rendering helper backing `Plugin.get_text`.
- `converter.py` is covered by `test/test_base_converter.py`.

## Link
- [../practices.md](../practices.md), [../architecture/summary.md](../architecture/summary.md)