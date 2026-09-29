# hermes-xmpp

Hermes Agent XMPP platform adapter, modeled conceptually after `openclaw-xmpp` but implemented against Hermes gateway plugin abstractions.

Status: Hermes-native adapter implementation in progress. It remains isolated from OpenClaw and is designed for local Hermes plugin installation after tests pass.

## Goals

- Direct XMPP chats first.
- MUC room support second, with conservative mention/allowlist defaults.
- Hermes-native platform registration through `ctx.register_platform()`.
- Secret handling through env vars, password files, or password commands.
- Clear separation from OpenClaw runtime state.

## Hermes Plugin Shape

Hermes community platform plugins use:

- `plugin.yaml` for metadata and setup UI env prompts.
- `adapter.py` with a `BasePlatformAdapter` subclass.
- `register(ctx)` to call `ctx.register_platform(...)`.

This repository keeps the adapter in `hermes_xmpp/adapter.py`. For local Hermes plugin discovery, symlink or copy the repository into the operator's Hermes plugin directory only after review.

## Installation

### Requirements

- Hermes Agent with plugin support.
- Python 3.11+.
- `slixmpp>=1.10,<2` available to the same Python environment that runs Hermes.
- An XMPP account for the bot.

### Install as a local Hermes plugin

Clone the repository and expose it as `xmpp-platform` under the Hermes plugin directory:

```sh
git clone <repo-url> ~/Projects/hermes-xmpp
mkdir -p ~/.hermes/plugins
ln -sfn ~/Projects/hermes-xmpp ~/.hermes/plugins/xmpp-platform
hermes plugins enable xmpp-platform
```

If you prefer copying instead of symlinking:

```sh
rm -rf ~/.hermes/plugins/xmpp-platform
mkdir -p ~/.hermes/plugins/xmpp-platform
rsync -a --exclude='.git' --exclude='__pycache__' --exclude='.pytest_cache' \
  ~/Projects/hermes-xmpp/ ~/.hermes/plugins/xmpp-platform/
hermes plugins enable xmpp-platform
```

Install the Python dependency in the Hermes runtime environment. For a venv-based Hermes install:

```sh
python -m pip install 'slixmpp>=1.10,<2'
```

For a Nix-packaged Hermes install, do not `pip install` into the immutable store. Add `slixmpp` to the Hermes wrapper/package environment declaratively, then rebuild the profile or Home Manager generation that provides `hermes`.

### Configure credentials

Prefer a password file or password command over putting a password directly in `.env`:

```dotenv
XMPP_JID="bot@example.org"
XMPP_SERVER="chat.example.org"
XMPP_RESOURCE="hermes"
XMPP_PASSWORD_COMMAND="pass show xmpp/bot/password"
XMPP_ALLOWED_USERS="user@example.org"
XMPP_DM_POLICY="allowlist"
XMPP_HOME_CHAT="user@example.org"
```

Then restart or run the Hermes gateway:

```sh
hermes gateway run --replace
```

A minimal standalone send smoke test can be done with Hermes' normal send-message tooling after the gateway/plugin is loaded, or by sending a direct message to the configured XMPP account and verifying Hermes replies.

## Configuration

Environment variables:

- `XMPP_JID`: account JID, for example `bot@example.org`.
- `XMPP_SERVER`: XMPP server hostname, `host:port`, or URL such as `xmpp://chat.example.org:5222`. Alias: `XMPP_HOST`.
- `XMPP_PORT`: optional TCP port override.
- `XMPP_PASSWORD`: account password. Prefer `XMPP_PASSWORD_FILE` or `XMPP_PASSWORD_COMMAND`.
- `XMPP_PASSWORD_FILE`: file containing the password.
- `XMPP_PASSWORD_COMMAND`: command that prints the password to stdout, for example `pass show xmpp/bot@example.org`.
- `XMPP_RESOURCE`: resource name, default `hermes`.
- `XMPP_NICKNAME`: MUC nickname, default localpart from `XMPP_JID`. Alias: `XMPP_MUC_NICK`.
- `XMPP_ROOMS`: comma-separated MUC JIDs to join. Alias: `XMPP_MUC_ROOMS`.
- `XMPP_ALLOWED_USERS`: comma-separated bare JIDs or patterns allowed to use direct chat. Supports exact JIDs, `*@domain`, and `*`.
- `XMPP_DM_POLICY`: `allowlist` (default), `open`, `disabled`, or `pairing` (treated as allowlist unless Hermes pairing is configured separately).
- `XMPP_ALLOW_ALL_USERS`: allow all direct-chat senders. Use only for trusted/dev environments.
- `XMPP_GROUP_POLICY`: `allowlist` (default), `open`, or `disabled`.
- `XMPP_ALLOWED_ROOMS`: comma-separated MUC room JIDs allowed when group policy is `allowlist`.
- `XMPP_GROUP_ALLOW_FROM`: comma-separated bare JIDs or patterns allowed inside MUCs. A groupchat message carries only the sender's nickname, so the adapter resolves the nickname to its real JID from occupant presence (XEP-0045 `<muc#user><x><item jid='...'/>`) before matching; in a room that exposes no occupant JIDs, this allowlist cannot match and the message is denied.
- `XMPP_MUC_REQUIRE_MENTION`: default `true`.
- `XMPP_KEEPALIVE_INTERVAL`: seconds between XMPP whitespace keepalives, default 60. A silent stream is reaped by the server or an intermediate NAT after a few minutes, which surfaces as `connection_lost` on an otherwise idle room; keepalives prevent it. slixmpp's own default is 300s, which is too slow for most servers.
- `XMPP_PING_INTERVAL`: seconds of inactivity before an XEP-0410 self ping is sent, default 60. XEP-0199 (`xep_0199`) is fire-and-forget: a ping written into a dead socket raises nothing, so a dead stream is only noticed after the fact. XEP-0410 closes that loop by timing out on an unanswered ping.
- `XMPP_PING_TIMEOUT`: seconds to wait for the self ping reply before the stream is treated as dead, default 30.
- `XMPP_HOME_CHAT`: default destination for cron/notification delivery. Alias: `XMPP_HOME_CHANNEL`.
- `XMPP_TEXT_CHUNK_LIMIT`: split outbound text above this many characters before sending. Alias: `XMPP_MAX_MESSAGE_LENGTH`.
- `XMPP_SEND_DELIVERY_RECEIPTS`: send XEP-0184 `<received xmlns='urn:xmpp:receipts'/>` replies to authorized direct-chat messages that request them. Default `true`.
- `XMPP_SEND_RECEIVED_MARKERS`: send XEP-0333 `<received xmlns='urn:xmpp:chat-markers:0'/>` markers to authorized direct-chat messages marked `<markable/>`. Default `true`.
- `XMPP_SEND_READ_RECEIPTS`: send XEP-0333 `<displayed/>` read/display markers to authorized direct-chat messages marked `<markable/>`. Default `false` for privacy.
- `XMPP_REACTIONS`: send XEP-0444 processing reactions to authorized messages. Default `true`; direct messages are allowed after DM authorization, and MUC reactions stay behind the same room/sender/mention gates as message processing.
- `XMPP_REACTION_START_CHOICES`: comma-separated reaction choices for processing start; one is chosen randomly. Default `👀`.
- `XMPP_REACTION_SUCCESS_CHOICES`: comma-separated reaction choices for successful completion; one is chosen randomly. Default `✅`.
- `XMPP_REACTION_FAILURE_CHOICES`: comma-separated reaction choices for failed completion; one is chosen randomly. Default `❌`.
- `XMPP_EDITABLE_PROGRESS`: controls XEP-0308 edits when editable delivery is enabled. `known` (default) requires a positive recipient support probe; `disabled` avoids correction stanzas.
- `XMPP_PROGRESS_DELIVERY`: `messages` (default) sends lifecycle status messages normally. `edit` lets repeated status messages with the same key use XEP-0308 when `XMPP_EDITABLE_PROGRESS` permits it.
- `XMPP_ANONYMOUS_MUC_POLICY`: how to treat MUC senders without a real bare JID. `mention_only` (default) still requires a mention when MUC mentions are enabled, `allow` accepts anonymous nicks under the other group gates, and `deny` rejects anonymous MUC senders.
- Progress: XMPP keeps XEP-0085 typing and XEP-0444 reactions. Generic Hermes previews and tool progress use recipient-probed XEP-0308 edits, then fall back to fresh visible delivery when corrections are unsupported.

Receipt/marker behavior is conservative: replies are only sent after allowlist authorization, marker/receipt stanzas do not get marker replies, and groupchat marker/receipt sending is disabled for now because XEP-0333 requires extra care around MUC stanza IDs (XEP-0359). Processing reactions are likewise conservative: unauthorized senders get no reaction, processing start/success/failure choose from configurable reaction sets, and XEP-0444 failures are soft/no-op. Code that already has a Hermes `MessageEvent` can call the adapter's `react_to_event(event, reactions)` helper to send arbitrary reactions such as `❤️` or `😂`; the helper reuses the original event target and authorization gates rather than accepting raw public message ids. Lifecycle status delivery preserves Hermes thread metadata and can use capability-gated XEP-0308 corrections. The live slixmpp client also requests STARTTLS and requires TLS before authentication.

Equivalent YAML values should live under `gateway.platforms.xmpp.extra` when Hermes loads the plugin:

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
          - ✅
          - ❤️
```

## Rollback

This repo is isolated. Rollback is:

1. Disable `gateway.platforms.xmpp.enabled` in Hermes config if it was enabled.
2. Remove any symlink/copy from `~/.hermes/plugins/`.
3. Stop/restart only the Hermes gateway if a live Hermes gateway was running.
4. Delete or archive this repository if no longer needed.

No OpenClaw state or service should be touched.
