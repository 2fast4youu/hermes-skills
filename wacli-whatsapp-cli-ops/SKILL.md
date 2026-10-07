---
name: wacli-whatsapp-cli-ops
description: Operate the wacli WhatsApp CLI — query the local store, understand JSON/SQLite shapes, re-authenticate stale sessions (phone pairing preferred over QR), and interpret sync/lock behavior.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [wacli, whatsapp, cli, re-auth, sqlite, sync]
    related_skills: [readonly-messaging-automation, personal-inbox-followup-automation]
---

# wacli WhatsApp CLI operations

Operational knowledge for a local wacli install: paths, output shapes, re-authentication, and sync behavior. Higher-level ingestion/extraction patterns live in `readonly-messaging-automation`; this skill is about driving the tool itself.

## Install layout

- Binaries: `~/.local/bin/wacli` and read-only wrapper `~/.local/bin/wacli-ro` (wrapper = `WACLI_READONLY=1 exec wacli "$@"`).
- **Store lives at `~/.local/state/wacli/`** (wacli.db, session.db, LOCK) — NOT `~/.wacli/`. `wacli-ro doctor` prints the STORE path if unsure.
- `wacli-ro` cannot write: `sync`, `auth`, sends are all rejected ("read-only mode"). Use writable `wacli` for those.
- If no account is configured (`wacli accounts list` says none), the default single-store mode is in use — commands work without `--account`.

## JSON output shapes

All `--json` commands wrap results as `{"success": ..., "data": ..., "error": ...}`.

- `chats list --json` → `data` is a list of `{jid, kind, name, last_message_ts, archived, pinned, muted_until, unread, unread_count}`. **Default `--limit` is 50** — pass `--limit 500` to see everything; `--query <text>` filters by name.
- `groups list --json` → `data` is a list with **capitalized keys**: `{JID, Name, OwnerJID, IsParent, LinkedParentJID, CreatedAt, LeftAt, UpdatedAt}`.
- `messages list/search --json` → `data` is an **object** `{fts: bool, messages: [...]}` with capitalized message keys: `ChatJID, ChatName, MsgID, SenderJID, SenderName, Timestamp (RFC3339 UTC), FromMe, Text, DisplayText, MediaType, MediaCaption, ...`.
- **Filter messages per chat with the `--chat <JID>` flag, not a positional arg.** `messages list 120363...@g.us --limit 50` does NOT filter — the positional JID is ignored and you get global recent messages across all chats. Correct: `messages list --chat <JID> --limit 50 --json`. Useful flags: `--after/--before` (RFC3339 or YYYY-MM-DD), `--from-me/--from-them`, `--sender <JID>`, `--asc`.
- `messages export <jid>` may return empty/nothing — use `messages list --chat <jid> --json` instead.
- To verify an outbound send by its returned message ID, `messages show` requires **both** flags: `wacli-ro messages show --chat <jid> --id <msg-id> --json`. Check that `FromMe` is `true`, the `ChatJID` matches the intended recipient, and the `Text` is exactly the requested payload before reporting the send as complete.

## Retrieving newly sent media

A chat's `last_message_ts` can be newer than the messages currently stored locally. When the user asks about a just-sent photo and `messages list --chat <jid>` does not yet show it, do not conclude it is absent:

1. Inspect connection/auth state with `wacli-ro doctor`.
2. Run one bounded writable sync, including media:
   ```bash
   ~/.local/bin/wacli sync --once --idle-exit 20s --download-media --max-reconnect 2m
   ```
   This only syncs to idle, rather than leaving a long-running process.
3. Re-query using a narrow RFC3339 cutoff and `--asc`, for example:
   ```bash
   ~/.local/bin/wacli-ro messages list --chat '<jid>' --after 'YYYY-MM-DDT00:00:00Z' --limit 100 --asc --json
   ```
4. For each `MediaType: image`, only analyze the local file after `LocalPath` is non-empty and `DownloadedAt` is set. Do not act on `DirectPath` alone.

## SQLite fallback (read-only)

When the CLI output is inconvenient or the session is expired, query the store directly — **use Python's `sqlite3` module, not the `sqlite3` shell CLI** (the CLI binary may be absent or silently return nothing; `python3 -c "import sqlite3"` always works):

```python
import os, sqlite3
db = sqlite3.connect('file:' + os.path.expanduser('~/.local/state/wacli/wacli.db') + '?mode=ro', uri=True)
```

- Tables: `chats, contacts, groups, group_participants, messages, polls, call_events, status_messages, ...`
- `messages` uses **unix epoch `ts`** (not RFC3339) plus lowercase cols: `chat_jid, msg_id, sender_jid, sender_name, ts, from_me, text, ...`.
- `groups` uses `created_ts` (epoch). Column names differ from the JSON keys — run `pragma table_info(<t>)` first.
- Open read-only via URI mode to avoid interfering with a running sync's lock.

**Finding all groups a contact belongs to** (no CLI command for this — sqlite only):
1. Resolve the person's JIDs from `contacts` (cols: `jid, push_name, full_name`) — one person often has BOTH a phone JID (`436...@s.whatsapp.net`) AND a linked-device ID (`...@lid`).
2. Join `group_participants` (cols: `group_jid, user_jid, role` — it is `user_jid`, NOT `jid`) for EVERY JID variant. Matching only the phone JID can return zero groups while the `@lid` variant finds them all — membership is frequently stored under the LID.
3. When scanning that person's messages across chats, filter `sender_jid` with all variants the same way.

```sql
SELECT g.jid, g.name FROM groups g
JOIN group_participants p ON p.group_jid = g.jid
WHERE p.user_jid IN ('<phone-jid>', '<lid>');
```

## Re-authentication (the recurring task)

wacli's WhatsApp session expires every few weeks; `wacli-ro doctor` then shows `AUTHENTICATED false` and `wacli sync` fails with "not authenticated; run `wacli auth`".

### Preferred: phone-number pairing

**Always try phone pairing first when the user is remote (chatting via a messenger).** QR codes rotate every ~20s; a QR image sent through chat is usually expired by the time the user scans it ("the code doesn't work").

1. Kill any stale auth process first.
2. Run in background with notify:
   ```bash
   ~/.local/bin/wacli auth --phone +<COUNTRYCODE><NUMBER> --idle-exit 10m
   ```
   (Your own number — also discoverable as the `sender_jid` of `from_me=1` rows in the messages table.)
3. Output contains `Pairing code for +...: XXXX-XXXX`. Send the code to the user immediately.
4. User: WhatsApp → Einstellungen → Verknüpfte Geräte → Gerät verknüpfen → **Mit Telefonnummer verknüpfen** → enter code.
5. The process then starts the initial history sync automatically.

### Fallback: QR

Only if phone pairing fails. Capture with a background process or PTY, render the newest QR payload to PNG **programmatically** (python `qrcode.make(payload)`) — never retype the base64-ish payload by eye, one wrong character makes it unscannable. The payload is the full `https://wa.me/settings/linked_devices#...` line. Send via `MEDIA:` immediately and regenerate on rotation. `auth connection dropped before pairing completed; retrying (n/3)` means the previous QR expired.

### After pairing

- Verify: `wacli auth status` → `Authenticated as ...@s.whatsapp.net`.
- Initial history sync runs **in the same auth process** and can take 10+ minutes (5,000+ messages). During it, `doctor` shows `CONNECTED locked_by_other_process` — that is healthy while message counts advance. Don't kill it.
- Newly created groups/chats on the phone only appear after sync has caught up. If a chat the user mentions isn't in `chats list` yet, say so and re-check after sync.

## Drafting and sending messages

- **Never send without the user's explicit OK.** Draft, show the text, wait. Sending requires the writable `wacli` binary (`wacli-ro` rejects sends).
- Before drafting a reply/message, assemble full context — this order matters:
  1. The person's DM (`messages list --chat <dm-jid>`)
  2. The relevant group history (`messages list --chat <group-jid>` — see `--chat` pitfall above)
  3. The user's own recent messages in that group (they may already have sent a first nudge — don't duplicate, follow up on it)
  4. `session_search` for prior agreements (e.g. departure dates/routes often were already decided in earlier sessions — a draft contradicting them looks clueless)
- **Style analysis of the user's own voice:** pull `from_me=1` texts via sqlite (~3000 recent), count top words, first words, emoji and average length, and read the long (>150 char) messages separately. Those are usually group announcements and are often written more formally than DMs, so mirror that register for announcements.
- **Group invitations/announcements** (rewrite requests): aim for the user's natural register (often light dialect/colloquial, not heavy), flowing personal sentences, motivating but not stiff. A single wall of text is hard to scan: default to a personal 1–2 sentence opener + compact info lines (date/time, arrive-anytime, what to bring, food/drinks) + a short warm closer. When asked for variants, vary BOTH the creative angle AND the message structure (opener+list, two messages invite→infos, poster-style headline), then recommend one.
- **Ghost-writing someone else's voice** ("how would X phrase this?"): sample that person's messages from the DM AND every shared group (use the contact-groups query above), then extract a style signature: greeting pattern, favorite words, dialect level (they may write more standard-German than the user), sentence structure, emoji/smileys incl. variants (e.g. 👌🏻 vs 👌, `:)` vs 😂), and typical closings. Rewrite the user's content in that signature; show style evidence + draft and never send without the user's OK.

## Pitfalls

1. **Don't pipe `wacli --json` output into an interpreter via shell pipe in one shot** if the terminal security scanner flags it; capture first or use python with `subprocess`. Also `messages list` data is an object, not a list — `data['messages']`.
2. **QR expiry over chat** — see above; phone pairing first.
3. **Confusing store paths**: `~/.wacli/` may appear in old docs/sessions; the live store is `~/.local/state/wacli/`.
4. **JSON key casing differs per command** (`name` vs `Name`, `timestamp` RFC3339 vs sqlite `ts` epoch). Don't assume.
5. **`wacli-ro` for reads only.** Sync/auth/send require the writable binary.
6. **Newly created groups not visible** until history sync completes — check sync progress before concluding a group doesn't exist.
