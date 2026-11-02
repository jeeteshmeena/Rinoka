# Plugin Inventory

Rinoka ships plugins in three locations. This is the current inventory (as of the scaffold).

## plugins/ — user-facing feature modules (22 files)
| File | Likely purpose |
|------|----------------|
| `admins.py` | Admin management (promote/demote, admin list) |
| `backups.py` | Per-group data backup/restore |
| `debug.py` | Debug/developer commands |
| `federation.py` | Cross-chat federation bans/rules |
| `filters.py` | Filter autodelete/regex word filters |
| `language.py` | Per-user/per-chat language switching |
| `lockings.py` | Lock/unlock chat features (messages, media, etc.) |
| `main.py` | Core/about/help commands |
| `misc.py` | Miscellaneous utility commands |
| `muting.py` | Mute/unmute, timed mutes |
| `notes.py` | Saved notes/`#hashtag` snippets |
| `purge.py` | Bulk message purge |
| `reporting.py` | Report user to admins |
| `restriction.py` | Ban/kick/warn restrictions |
| `rules.py` | Group rules display/edit |
| `spam_shield.py` | Spam protection / honeypot |
| `staff_tools.py` | Staff-only moderation tools |
| `stats.py` | Bot/chats statistics |
| `topic.py` | Topic (forum) handling |
| `users.py` | User lookup / info |
| `welcome.py` | Welcome/farewell messages |

## internal_plugins/ (4 files)
- `canonical.py` — canonical/standardized data.
- `health.py` — health/readiness checks.
- `spam_prediction.py` — spam prediction hook.
- package root `__init__.py`.

## custom_plugins/ (2 files)
- User-supplied custom plugins (package root + one feature).

> Note: purpose labels above are inferred from filenames at scaffold time. Verify against the actual source when working on a specific plugin.