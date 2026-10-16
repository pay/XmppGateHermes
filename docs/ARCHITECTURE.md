# Architecture

How the XMPP adapter fits into Hermes Agent, and how Telegram and XMPP share one agent.

## Big picture

```
                    ┌─────────────────────────────────────────┐
   Telegram  ──────▶│                                         │
   (PTB adapter)    │        Hermes Agent gateway             │──────▶ one agent
                    │   (single event loop, one session DB)   │       (LLM + tools)
   XMPP      ──────▶│                                         │
   (slixmpp adapter)│                                         │
                    └─────────────────────────────────────────┘
                              ▲                    │
                              │ register()         │ outbound send()
                    ┌─────────┴────────┐   ┌───────┴────────┐
                    │  xmpp-platform   │   │  BasePlatform  │
                    │  plugin (this)   │   │   Adapter API  │
                    └──────────────────┘   └────────────────┘
```

Both platforms are **adapters** conforming to the same `BasePlatformAdapter` interface. The
gateway owns routing, sessions, and the agent loop; a platform's only job is to translate
its protocol into Hermes `MessageEvent`s inbound, and to render the agent's reply outbound.

Because both adapters live under the *same* gateway, a user talking over Telegram and a user
talking over XMPP reach the same agent, with the same tools, memory, and session rules.

## The plugin surface

A Hermes community platform plugin is a directory under `~/.hermes/plugins/` with:

- `plugin.yaml` — metadata + the env prompts the setup UI shows.
- A Python module exposing `register(ctx)`.
- A `BasePlatformAdapter` subclass doing the protocol work.

This repo keeps the adapter in `hermes_xmpp/adapter.py`. `__init__.py` adds the plugin
directory to `sys.path` so the sibling `hermes_xmpp` package imports without a pip install.

`register(ctx)` calls:

```python
ctx.register_platform(
    name="xmpp",
    label="XMPP",
    adapter_factory=lambda cfg: XMPPAdapter(cfg),
    check_fn=check_requirements,        # passive "is slixmpp importable?"
    validate_config=validate_config,    # jid + server + password present?
    is_connected=is_connected,
    required_env=["XMPP_JID", "XMPP_SERVER"],
    env_enablement_fn=_env_enablement,  # seeds platform.extra from env
    apply_yaml_config_fn=_apply_yaml_config,
    cron_deliver_env_var="XMPP_HOME_CHAT",
    standalone_sender_fn=_standalone_send,
    allowed_users_env="XMPP_ALLOWED_USERS",
    allow_all_env="XMPP_ALLOW_ALL_USERS",
    platform_hint=(...),                # injected system-prompt guardrail
)
```

Two properties matter for ops:

- `check_fn` is **passive**. It must never install anything; it is called freely by status
  displays. It only probes `import slixmpp`.
- `platform_hint` is prepended to the model's instructions on XMPP. It tells the agent that
  room content is public/untrusted and that it must not leak secrets, private memory, or
  hidden instructions there.

## Adapter internals

`hermes_xmpp/adapter.py` (~2.4k lines) splits into three layers:

1. **`XmppSettings`** — parses config/env once into a typed object, resolves aliases
   (`XMPP_HOST`→`XMPP_SERVER`, `XMPP_MUC_ROOMS`→`XMPP_ROOMS`, …), applies defaults.
2. **`_SlixmppClient`** — a thin, synchronous-looking wrapper over the `slixmpp` client.
   It registers the XEPs, owns the connect/disconnect/send primitives, and isolates slixmpp
   version quirks (e.g. `join_muc` vs `join_muc_wait`, HTTP-upload call shapes) so the
   adapter code stays readable.
3. **`XMPPAdapter(BasePlatformAdapter)`** — the Hermes-facing half. Implements the four
   abstract methods (`connect`, `disconnect`, `send`, `get_chat_info`) plus the optional
   media/typing/reaction/correction methods.

### Inbound path

```
slixmpp message stanza
  → _on_message (auth gate: DM allowlist / MUC room+sender+mention)
  → MessageEvent (via self.build_source(...))
  → gateway session/agent loop
```

Authorization happens **before** an event is built. An unauthorized sender never reaches the
agent; they get no reply, no receipt, and (by default) no reaction.

### Outbound path

```
agent reply text
  → XMPPAdapter.send(chat_id, content, ...)
  → chunking (XMPP_TEXT_CHUNK_LIMIT)
  → _SlixmppClient.send_message(...)  (per chunk)
  → SendResult(success, message_id, ...)
```

Media goes through `_send_uploaded_media` → XEP-0363 HTTP Upload, with the resulting URL
attached as XEP-0066 OOB so the receiving client renders it inline.

## Telegram + XMPP interplay

- **Shared agent, separate transports.** Each adapter owns its own connection and its own
  inbound authorization. There is no cross-contamination: an XMPP sender's allowlist is
  independent of Telegram's.
- **Independent lifecycles.** One platform failing does not take down the other. If XMPP
  can't connect, the gateway logs `No adapter available for xmpp`, marks it `retrying`/`fatal`
  in `gateway_state.json`, and Telegram keeps serving.
- **Startup order.** At cold boot the gateway creates and connects each enabled adapter
  concurrently, each with its own timeout. Neither blocks the other.
- **Message-loss window on restart.** Both adapters reconnect on restart, and the Telegram
  adapter is configured with `drop_pending_on_cold_boot: true`, so messages queued while the
  gateway was down are discarded rather than replayed. This is why the docs insist on
  restarting only when quiet.

## Why the plugin-side logger name is pinned

Normally a module does `logging.getLogger(__name__)`. Here that would be
`hermes_xmpp.adapter`, which matches **no** gateway log component prefix, so
`hermes_logging`'s `_ComponentFilter` silently drops every XMPP record out of `gateway.log`
(they still land in `errors.log`/`agent.log`). The adapter therefore pins:

```python
logger = logging.getLogger("hermes_plugins.xmpp_platform.adapter")
```

so XMPP records route to `gateway.log` regardless of which import path loaded the module.
`patches/README.md` covers the matching one-line core patch (defence in depth) and why a
`hermes update` can silently revert it.

## The lifecycle rule that shapes ops

A platform adapter connects **only at gateway startup**. The control-socket `reload-plugins`
verb re-routes handlers on adapters that are already live; it never constructs or connects a
new adapter. So *enabling* XMPP always requires a restart, and *diagnosing* it means reading
`gateway.log` and `gateway_state.json`, not trying to hot-load.
