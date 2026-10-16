# Troubleshooting

Every fix here was run on the authoring Termux device and confirmed. Read-only commands
change nothing; *(changes system)* and *(requires restart)* are marked.

Start here regardless of symptom:

```sh
# (read-only)  — the single most useful command
~/gate.sh status
```

On Termux, **`hermes gateway status` is a false negative** — it probes systemd/launchd,
which don't exist on Android, so a healthy gateway reads as "not running". Always prefer
`gate.sh`, or read `~/.hermes/gateway_state.json` directly.

---

## 1. Adapter shows `No adapter available for xmpp`

**Meaning.** The platform is enabled but the adapter object was never created. Almost always
the Python dependency is missing from the *gateway venv*.

**Diagnose** *(read-only)*:

```sh
"$PREFIX/lib/hermes-agent/venv/bin/python3" -c 'import slixmpp; print(slixmpp.__version__)'
```

If that raises `ModuleNotFoundError`, the dep isn't in the venv the gateway actually uses.

**Fix** *(changes system)*:

```sh
uv pip install --python "$PREFIX/lib/hermes-agent/venv/bin/python3" 'slixmpp[xep-0363]>=1.10,<2'
```

Then *(requires restart)* `~/gate.sh restart`.

> **Trap.** The Hermes `tools/python` interpreter is a *different* interpreter from the
> gateway venv. Installing slixmpp into `tools/python` will not help. Confirm you targeted
> `$PREFIX/lib/hermes-agent/venv/bin/python3`.

---

## 2. `hermes plugins enable xmpp-platform` fails with a resolver error

**Symptom** *(read-only — running it changes nothing on failure)*:

```
DependencyConflict: Plugin 'xmpp-platform' conflicts with the dependencies pinned by Hermes core…
uv lock exited 1 … playwright==1.62.0 has no `python_full_version >= '3.14'`-compatible wheels
hermes-agent[google-meet]'s requirements are unsatisfiable
```

**Cause.** On this Termux build the plugin manager's admission step generates a temporary
uv workspace (core `pyproject.toml` + the plugin as a member) and re-locks *everything*. The
core's `google-meet` extra pins `playwright==1.62.0`, which ships only platform wheels
(macos/linux/win) with **zero sdists** — so on `sys_platform == "android"` there is nothing
to resolve. Any member, even an empty one, forces the full re-resolve. `hermes pm doctor`
on the same install crashes with `KeyError: 'sha256'`.

This is a finding about **this environment**, not a universal Hermes bug — desktop installs
resolve fine because a compatible playwright wheel exists there.

**Fix** *(changes system)* — enable via config directly. The payload is identical to what
`cmd_enable` writes after a successful admission; only the broken resolution step is
skipped:

```sh
cp -p ~/.hermes/config.yaml ~/.hermes/config.yaml.bak-plugins-$(date +%Y%m%d-%H%M%S)
printf '\nplugins:\n  enabled:\n    - xmpp-platform\n' >> ~/.hermes/config.yaml
```

Confirm *(read-only)* — must print `Status: enabled`:

```sh
hermes plugins info xmpp-platform
```

Disabling has the same admission block, so remove the `    - xmpp-platform` line from
`plugins.enabled` instead of using `hermes plugins disable`.

---

## 3. A PM operation killed both Telegram and XMPP

**Symptom.** Right after `hermes pm install`, a repair, or a *successful* admission, both
platforms stop connecting.

**Cause.** The PM syncs with `uv sync --frozen --all-packages` and **no `--inexact`** —
exact mode. That removes any package not in the lockfile. `slixmpp` and
`python-telegram-bot` were installed manually with `uv pip` (outside the lock), so both get
evicted together.

**Fix** *(changes system)* — reinstall both into the gateway venv, then restart:

```sh
uv pip install --python "$PREFIX/lib/hermes-agent/venv/bin/python3" \
  'slixmpp[xep-0363]>=1.10,<2' 'python-telegram-bot[webhooks]==22.8'
```

*(requires restart)* `~/gate.sh restart`.

**Prevention.** Don't run `hermes pm install` / `pm sync` while manual uv-pip installs carry
the platforms. Ironically, the failed admission in §2 *protects* you: because it never
succeeds, it never syncs, so it never evicts.

---

## 4. XMPP connected but a MUC never joins (or joins silently)

**Diagnose** *(read-only)*:

```sh
grep "XMPP: MUC" ~/.hermes/logs/gateway.log | tail
```

Healthy lines:

```
XMPP: joining MUC <room> as <nick> (resource <res>)
XMPP: MUC <room> join confirmed (<n> occupant(s))
```

A `join NOT confirmed — server sent no self-presence` error means the MUC service dropped
the join. Check the room exists and isn't archived, the account is allowed to join, and the
room's domain isn't blocked against the account's domain.

> **Note.** The `(<n> occupant(s))` and self-presence check are in the newer adapter in this
> repo. An older installed copy logs the plainer `join confirmed` / `join NOT confirmed`
> without the occupant count. See `KNOWN-ISSUES.md`.

---

## 5. XMPP connected, room joined, but the bot never replies in the room

This is the **triple gate**. A group message must pass all three, in `XMPP_GROUP_POLICY` /
`XMPP_MUC_REQUIRE_MENTION` mode:

1. **Room allowlist** — `XMPP_ALLOWED_ROOMS` (falls back to `XMPP_ROOMS`).
2. **Sender allowlist** — `XMPP_GROUP_ALLOW_FROM`.
3. **Mention** — the bot's nickname appears in the message (when
   `XMPP_MUC_REQUIRE_MENTION=true`).

The subtle one is #2. A groupchat stanza carries only the sender's **nickname**, so the
adapter resolves the nick → real JID from occupant presence (XEP-0045
`<muc#user><x><item jid='…'/>`) before matching. **In a room that exposes no occupant JIDs**
(anonymous/semi-anonymous MUC), that mapping is empty, the allowlist can never match, and
every message is denied — by design.

**Diagnose** *(read-only)*: confirm the room exposes occupant JIDs (join with a normal
client and check the member list shows real JIDs, not just nicks).

**Options:**
- Use a non-anonymous room, or
- Set `XMPP_ANONYMOUS_MUC_POLICY=allow` to accept anonymous nicks under the other gates, or
- Mention-gate only: keep `XMPP_MUC_REQUIRE_MENTION=true` and treat the room as mention-only.

---

## 6. XMPP connects then periodically drops (`connection_lost` on idle)

**Cause.** A silent stream is reaped by the server or an intermediate NAT after a few
minutes. slixmpp's default keepalive (300 s) is too slow for most mobile networks.

**Fix** *(changes system)* — tighten keepalive and use the XEP-0410 self-ping (the adapter
already prefers it over the fire-and-forget XEP-0199):

```dotenv
XMPP_KEEPALIVE_INTERVAL=60
XMPP_PING_INTERVAL=60
XMPP_PING_TIMEOUT=30
```

*(requires restart)* `~/gate.sh restart`.

---

## 7. No XMPP log records in `gateway.log`

**Diagnose** *(read-only)*:

```sh
grep hermes_plugins.xmpp_platform ~/.hermes/logs/gateway.log | tail     # expected: several lines
grep "XMPP:" ~/.hermes/logs/errors.log | tail                          # fallback location
```

**Cause.** `gateway.log` is filtered by logger-name prefix. A module logging as
`hermes_xmpp.adapter` matches no gateway prefix and is dropped from `gateway.log` (it still
goes to `errors.log` / `agent.log`). The adapter pins its logger to
`hermes_plugins.xmpp_platform.adapter` to avoid this.

If records are missing, either the installed adapter predates the pin (see `KNOWN-ISSUES.md`)
or the core-side patch has been reverted by a `hermes update`. See `patches/README.md` to
re-apply the core half and **restart** (the filter is read once at logging setup).

---

## 8. Gateway reads "not running" but messages are arriving

Not a fault. Use `~/gate.sh status` instead of `hermes gateway status` (see §0). To check by
hand *(read-only)*:

```sh
python3 -c "import json; d=json.load(open('$HOME/.hermes/gateway_state.json')); print(d['gateway_state'], d['pid'], {k:v['state'] for k,v in d['platforms'].items()})"
```

If the state says `running` but the pid in `~/.hermes/gateway.pid` no longer exists in
`/proc/<pid>/cmdline`, the gateway died uncleanly — restart it.

---

## General diagnosis order

1. `~/gate.sh status` — which adapter is down.
2. `hermes plugins info xmpp-platform` — is it `enabled`?
3. Deps in the **gateway venv** — `import slixmpp, telegram`.
4. Offline gates — `hermes plugins validate <dir>` and `hermes plugins doctor <dir>`.
5. `~/.hermes/logs/gateway.log` markers (not `agent.log`).
6. `~/.hermes/gateway_state.json` → `platforms.<name>.{state,error_code,error_message}`.
7. **Network before credentials** — DNS + TCP connect to :5222. Reachable-but-refused means
   credentials/allowlist; unreachable means network/blocking.
8. Confirm `XMPP_*` keys exist in `~/.hermes/.env` (names only — never echo values).

The reusable version of this runbook is the Hermes skill `hermes-xmpp-termux`
(`~/.hermes/skills/hermes/hermes-xmpp-termux/`).
