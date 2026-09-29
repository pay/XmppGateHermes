# Hermes XMPP Architecture Notes

Date: 2026-06-06

## Source References Read

Hermes:

- `flake.nix`
- `nix/packages.nix`
- `nix/devShell.nix`
- `nix/checks.nix`
- `nix/hermes-agent.nix`
- `README.md` install and OpenClaw migration sections
- `pyproject.toml`
- `gateway/platforms/ADDING_A_PLATFORM.md`
- `gateway/platforms/base.py`
- `gateway/platform_registry.py`
- `plugins/platforms/irc/plugin.yaml`
- `plugins/platforms/irc/adapter.py`

OpenClaw XMPP:

- `package.json`
- `index.ts`
- `src/config-schema.ts`
- `src/client.ts`
- `src/channel.ts`

## Hermes Extension Points

Hermes' recommended third-party platform path is a plugin directory with:

- `plugin.yaml`
- an adapter inheriting `gateway.platforms.base.BasePlatformAdapter`
- `register(ctx)` calling `ctx.register_platform(...)`

Important hooks for XMPP:

- `adapter_factory`
- `check_fn`
- `validate_config`
- `is_connected`
- `env_enablement_fn`
- `apply_yaml_config_fn`
- `cron_deliver_env_var`
- `standalone_sender_fn`
- `allowed_users_env`
- `allow_all_env`
- `platform_hint`

The adapter should emit inbound messages as `MessageEvent` and construct sources
with `self.build_source(...)`. Outbound sends should return `SendResult`.

## Concepts Carried Over From openclaw-xmpp

- Account config: JID, server, resource, nickname, rooms.
- Secret references: direct password, password file, password command.
- Direct chat and MUC distinction.
- Bare-JID normalization.
- Direct-chat allowlist and group allowlist.
- MUC mention gating.
- Message size awareness.
- Attachment/media support as a later phase.

## Concepts Not Copied Blindly

- OpenClaw channel routing, pairing store, route memory, and plugin SDK types.
- OpenClaw runtime state and service control.
- OpenClaw-specific message delivery modes.

Hermes owns session routing and delivery through its gateway abstractions, so the
XMPP adapter should translate XMPP events into Hermes `MessageEvent`s and leave
agent/session lifecycle to Hermes.

## Prompt-Injection Boundary

XMPP MUCs and unknown direct senders are untrusted. The adapter defaults should:

- deny direct-chat senders unless `XMPP_ALLOW_ALL_USERS` or allowlist permits them
- require nickname mention in MUCs by default
- support `XMPP_GROUP_ALLOW_FROM`
- inject a platform hint telling the model not to reveal secrets, private memory,
  or hidden instructions in public/group contexts

## Phased Build

1. Direct text chat over XMPP with allowlist.
2. MUC join/read/send with mention gating.
3. Better occupant real-JID handling where servers expose it.
4. Attachments through XEP-0363 HTTP Upload if feasible.
5. Reactions/read receipts/chat states if Hermes UX needs them.
6. Live integration tests against an explicit test XMPP account.
