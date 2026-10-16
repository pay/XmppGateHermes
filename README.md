# XmppGateHermes

XMPP/Jabber platform adapter for **Hermes Agent**, proven running on **Android / Termux**
alongside the Telegram gateway. This repo documents a working integration: one Hermes
gateway serving **Telegram and XMPP at the same time**, with MUC (group) room support.

> **Status: verified on a real device.** Every claim in `docs/TESTING.md` was observed on a
> Termux install, not assumed. Known limitations and environment-specific bugs are listed
> honestly in `docs/KNOWN-ISSUES.md`.

## What this is

- A Hermes **platform plugin** (`xmpp-platform`) that registers an XMPP adapter through
  Hermes' `ctx.register_platform()` gateway API.
- `slixmpp`-based transport (XEP-0184 receipts, XEP-0333 chat markers, XEP-0085 chat
  states, XEP-0444 reactions, XEP-0308 corrections, XEP-0363 HTTP Upload, XEP-0045 MUC).
- An operator runbook for installing, hardening and troubleshooting it on Termux, where the
  Hermes plugin manager and Android's filesystem differ from desktop Linux.

The adapter source lives in `hermes_xmpp/adapter.py`. The docs here are the part that is
usually missing: what actually breaks on a phone, and the verified workaround.

## Features

- Direct (1:1) XMPP chats and MUC rooms served through the same agent.
- Runs **concurrently with the Telegram gateway** — one agent, two messaging platforms.
- Conservative access control: direct-chat allowlist, per-room and per-sender group
  allowlists, nickname-mention gating in rooms.
- Typing indicators, delivery receipts, read markers, emoji reactions, live "editing"
  progress updates (capability-gated).
- Outbound media via XEP-0363 HTTP Upload.
- Secret handling via env var, password file, or password command (never hardcoded).

## Verified baseline

These are **observed** facts from the device this repo was authored on (Termux, Android,
Python 3.14). They describe a state that was reached and logged, not a target:

| Item | Value |
| --- | --- |
| Hermes Agent | `v0.22.0+canary` APT payload on Termux |
| Python | 3.14 (`sys.platform == "android"`) |
| Concurrent platforms | Telegram gateway + XMPP adapter, both `connected` |
| Plugin key | `xmpp-platform` |
| Verified dependency | `slixmpp 1.17.0` (via `slixmpp[xep-0363]`) |
| XMPP resource | `flip4` |
| MUC rooms joined | `tangerang@conference.jabber.ru`, `code@conference.conversations.im` |
| Outbound message to a room | confirmed delivered and logged |
| Test suite | `125 passed, 2 skipped` (see `docs/TESTING.md`) |

The plugin manager (PM) on this build could **not** enable the plugin through the normal
`hermes plugins enable` path — see `docs/KNOWN-ISSUES.md`. Activation was done by editing
`config.yaml` after a backup. That is a finding about *this* Termux environment, not a
universal Hermes bug.

Personal JIDs, allowlist entries, passwords, tokens, local IPs and `.env` contents are
deliberately **not** in this repo. See `docs/SECURITY.md`.

## Requirements

- Android device running **Termux** (aarch64).
- Hermes Agent installed (this docs set targets the APT/bundle payload under
  `$PREFIX/lib/hermes-agent`).
- An XMPP account for the bot, on a server reachable over TCP 5222 with STARTTLS.
- `uv` (ships with the Hermes Termux bundle) to install the adapter's Python dependency.

## Installation

Full, copy-pasteable steps — including the Termux-specific workaround for the plugin
manager — are in **`docs/INSTALLATION.md`**. The short version:

```sh
# 1. install the runtime dependency into the GATEWAY venv (not tools/python)
uv pip install --python "$PREFIX/lib/hermes-agent/venv/bin/python3" 'slixmpp[xep-0363]>=1.10,<2'

# 2. drop the plugin into the Hermes plugin dir
mkdir -p ~/.hermes/plugins/xmpp-platform
rsync -a --exclude='.git' ~/XmppGateHermes/ ~/.hermes/plugins/xmpp-platform/

# 3. enable it (on this Termux build: edit config.yaml directly — see docs/KNOWN-ISSUES.md)
# 4. set XMPP_* env vars in ~/.hermes/.env  (names and meanings: docs/INSTALLATION.md)
# 5. restart the gateway
~/gate.sh restart
```

## Documentation

| File | What it covers |
| --- | --- |
| `docs/ARCHITECTURE.md` | Adapter design, how it plugs into the Hermes gateway, Telegram+XMPP interplay |
| `docs/INSTALLATION.md` | Termux-specific install, step by step |
| `docs/CONFIG-REFERENCE.md` | Every env var: name, default, purpose (names only, no values) |
| `docs/TROUBLESHOOTING.md` | Verified diagnosis flow and the fixes that worked |
| `docs/SECURITY.md` | Secrets, allowlists, TLS, MUC as a public surface |
| `docs/TESTING.md` | Test scenarios and their real results |
| `docs/KNOWN-ISSUES.md` | Bugs, environment quirks, compatibility notes |
| `docs/SKILL.md` | The `hermes-xmpp-termux` Hermes skill and how it maps here |
| `patches/README.md` | The one Hermes-core patch and why it exists |
| `notes/` | Upstream design/architecture notes (background reading) |
| `skills/hermes-xmpp-termux/SKILL.md` | Shipped copy of the operator skill (live copy in `~/.hermes/skills/`) |

A reusable Hermes skill, **`hermes-xmpp-termux`**, also encodes this runbook for in-session
use — Hermes loads it automatically when an XMPP-on-Termux problem appears. A byte-identical
copy ships in this repo at `skills/hermes-xmpp-termux/SKILL.md`; the live one Hermes loads
is `~/.hermes/skills/hermes/hermes-xmpp-termux/SKILL.md`. Like every file here, it holds no
secrets — `~/.hermes/.env` keys are named, never valued. See `docs/SKILL.md`.

## Safety notes

- Restarting the Hermes gateway drops the messaging connections for ~25–30 s. During that
  window inbound messages can be **lost** (cold-boot drops the pending queue). Restart only
  when your chats are quiet.
- Commands in these docs are tagged *(read-only)*, *(changes system)*, or
  *(requires restart)* so you can tell before you run them which ones disturb a live
  gateway.

## License

Source in this repo is MIT (`LICENSE`), matching the upstream plugin, `slixmpp`, and Hermes
Agent itself. See `LICENSE` and the note in `docs/KNOWN-ISSUES.md` about third-party code.

## Contributing

See `CONTRIBUTING.md`. This is a documentation-first repo: the highest-value contributions
are corrections from other Termux installs.
