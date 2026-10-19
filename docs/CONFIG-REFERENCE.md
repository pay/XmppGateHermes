# Configuration reference

Every knob the adapter reads, with defaults and the reason it exists. Values go in
`~/.hermes/.env`. **No real values appear in this file** — only names, defaults, and
`example.org` placeholders.

The equivalent YAML form lives under `gateway.platforms.xmpp.extra` when Hermes loads the
plugin from config rather than env. The env path is the one verified on Termux.

## Identity (required)

| Var | Default | Meaning |
| --- | --- | --- |
| `XMPP_JID` | — | Bot account JID, e.g. `bot@example.org`. |
| `XMPP_SERVER` | — | Server hostname, `host:port`, or `xmpp://host:port`. Alias: `XMPP_HOST`. |
| `XMPP_PASSWORD` | — | Password (plaintext). Prefer a file or command below. |
| `XMPP_PASSWORD_FILE` | — | Path to a file holding the password. |
| `XMPP_PASSWORD_COMMAND` | — | Command that prints the password to stdout, e.g. `pass show xmpp/bot`. |
| `XMPP_PORT` | `5222` | TCP port override. |
| `XMPP_RESOURCE` | `hermes` | Resource name. The authoring device used `flip4`. |

`validate_config()` requires JID **and** server **and** a password (from any of the three
password sources). `check_requirements()` only checks that `slixmpp` imports.

## MUC / rooms

| Var | Default | Meaning |
| --- | --- | --- |
| `XMPP_NICKNAME` | localpart of `XMPP_JID` | Nickname in rooms. Alias: `XMPP_MUC_NICK`. |
| `XMPP_ROOMS` | — | Comma-separated room JIDs to join. Alias: `XMPP_MUC_ROOMS`. |
| `XMPP_MUC_REQUIRE_MENTION` | `true` | Only reply in a room when the nick is mentioned. |
| `XMPP_ANONYMOUS_MUC_POLICY` | `mention_only` | How to treat senders with no real bare JID: `mention_only`, `allow`, or `deny`. |

## Access control

| Var | Default | Meaning |
| --- | --- | --- |
| `XMPP_DM_POLICY` | `allowlist` | `allowlist`, `open`, `disabled`, or `pairing`. |
| `XMPP_ALLOWED_USERS` | — | Comma-separated bare JIDs/patterns for direct chat. Supports exact JID, `*@domain`, `*`. |
| `XMPP_ALLOW_ALL_USERS` | `false` | Allow every direct sender. Trusted/dev only. |
| `XMPP_GROUP_POLICY` | `allowlist` | `allowlist`, `open`, or `disabled`. |
| `XMPP_ALLOWED_ROOMS` | falls back to `XMPP_ROOMS` | Rooms allowed when group policy is `allowlist`. |
| `XMPP_GROUP_ALLOW_FROM` | — | Bare JIDs/patterns allowed to speak inside allowed rooms. |

**Why `XMPP_GROUP_ALLOW_FROM` can silently deny everyone.** A groupchat stanza carries only
the sender's *nickname*, not their JID. The adapter resolves the nick to a real JID from
occupant presence (XEP-0045 `<muc#user><x><item jid='…'/>`). In a room that does not expose
occupant JIDs (anon/semi-anon MUC), that mapping is empty, the allowlist can never match,
and every message is denied. This is by design, not a bug — see `TROUBLESHOOTING.md`.

**Who the server tells — and the fix.** Room privacy, not config, decides whether the map can be
filled at all:

| Room `whois` | Who receives `<item jid=…>` | JID allowlist usable? |
| --- | --- | --- |
| `nobody` (fully anonymous) | nobody | no |
| `moderators` (semi-anonymous, common) | moderators only | yes, if the **bot is a moderator** |
| `anyone` (non-anonymous) | every occupant | yes |

So the way to make this gate real is to have the room owner grant the bot **administrator
affiliation** (which carries the moderator role). Observed on one room, same account, before and
after that change: `cached 0/8 occupant nick->JID mapping(s)` → `cached 8/8`. Do not switch the
room to non-anonymous just to feed this gate — that exposes every member's JID to all occupants.
Never substitute a nickname allowlist: any occupant can rename to an allowed nick, so a nick gate
is not an identity check. See `FIELD-NOTES-2026-10-20.md` §3.

## Delivery & liveness

| Var | Default | Meaning |
| --- | --- | --- |
| `XMPP_HOME_CHAT` | — | Default destination for cron/notification delivery. Alias: `XMPP_HOME_CHANNEL`. |
| `XMPP_TEXT_CHUNK_LIMIT` | `4000` | Split outbound text above this many chars. Alias: `XMPP_MAX_MESSAGE_LENGTH`. |
| `XMPP_KEEPALIVE_INTERVAL` | `60` | Seconds between whitespace keepalives. slixmpp's own default (300) is too slow for most servers/NAT; idle streams get reaped and surface as `connection_lost`. |
| `XMPP_PING_INTERVAL` | `60` | Seconds of inactivity before an XEP-0410 self-ping. |
| `XMPP_PING_TIMEOUT` | `30` | Seconds to wait for the self-ping reply before treating the stream as dead. |

XEP-0199 pings are fire-and-forget (a ping written to a dead socket raises nothing), so the
adapter uses **XEP-0410** self-ping, which times out on an unanswered ping and closes the
detection loop.

## Receipts, markers, chat states

| Var | Default | Meaning |
| --- | --- | --- |
| `XMPP_SEND_DELIVERY_RECEIPTS` | `true` | Send XEP-0184 `<received/>` for authorized direct messages that request it. |
| `XMPP_SEND_RECEIVED_MARKERS` | `true` | Send XEP-0333 `<received/>` for authorized, `<markable/>` direct messages. |
| `XMPP_SEND_READ_RECEIPTS` | `false` | Send XEP-0333 `<displayed/>`. Off by default for privacy. |
| `XMPP_SEND_CHAT_STATES` | `true` | Send XEP-0085 composing/active while processing. |

Behavior is deliberately conservative: receipts/markers are only sent after allowlist
authorization, a receipt never triggers a receipt in reply, and **groupchat** marker/receipt
sending is disabled because XEP-0333 needs care around MUC stanza IDs (XEP-0359).

## Reactions & progress

| Var | Default | Meaning |
| --- | --- | --- |
| `XMPP_REACTIONS` | `true` | Send XEP-0444 processing reactions to authorized messages. |
| `XMPP_REACTION_START_CHOICES` | `👀` | Comma-separated reactions for "started"; one picked at random. |
| `XMPP_REACTION_SUCCESS_CHOICES` | `✅` | Comma-separated reactions for "done". |
| `XMPP_REACTION_FAILURE_CHOICES` | `❌` | Comma-separated reactions for "failed". |
| `XMPP_PROGRESS_DELIVERY` | `messages` | `messages` sends lifecycle status as normal messages; `edit` uses XEP-0308 corrections for same-key updates. |
| `XMPP_EDITABLE_PROGRESS` | `known` | `known` requires a positive recipient support probe; `disabled` avoids correction stanzas. |

Reactions are gated the same way as messages: unauthorized senders get no reaction, and an
XEP-0444 failure is a soft no-op. Code holding a Hermes `MessageEvent` can call
`adapter.react_to_event(event, reactions)` for arbitrary reactions (e.g. `❤️`, `😂`) — it
reuses the event's own target and authorization gates rather than accepting raw public
message ids.

## YAML form

If you'd rather keep config in `config.yaml` than `.env`:

```yaml
gateway:
  platforms:
    xmpp:
      enabled: true
      extra:
        jid: bot@example.org
        server: chat.example.org
        password_file: /run/secrets/hermes-xmpp-password
        resource: hermes
        rooms:
          - room@muc.example.org
        allowed_users:
          - user@example.org
        muc_require_mention: true
        reaction_success_choices:
          - "✅"
          - "❤️"
```

The env path and the YAML path are equivalent; the adapter's `_env_enablement()` merges env
values into `platform.extra` using the flat IRC/Google-Chat shape.
