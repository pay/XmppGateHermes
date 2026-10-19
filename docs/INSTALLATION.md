# Installation (Termux / Android)

This guide targets Hermes Agent installed as the **APT/bundle payload** under
`$PREFIX/lib/hermes-agent` on Termux (aarch64), Python 3.14. Paths differ for Nix or
source installs; the plugin mechanics are the same.

Commands are tagged:

- **(read-only)** — inspects, changes nothing.
- **(changes system)** — installs packages or edits files.
- **(requires restart)** — needs a gateway restart to take effect.

## 0. Confirm the environment

```sh
# (read-only)
uname -m                                   # expect: aarch64
"$PREFIX/lib/hermes-agent/venv/bin/python3" -c 'import sys; print(sys.version, sys.platform)'
command -v uv && uv --version              # uv ships with the Hermes Termux bundle
```

The adapter dependency must go into the **gateway venv**, not `tools/python`:

```
$PREFIX/lib/hermes-agent/venv/bin/python3
```

## 1. Install the runtime dependency

```sh
# (changes system)
uv pip install --python "$PREFIX/lib/hermes-agent/venv/bin/python3" 'slixmpp[xep-0363]>=1.10,<2'
```

Verified on the authoring device: this pulls **13 packages** including `slixmpp 1.17.0`,
`aiohttp`, `aiodns`, `pycares`, `attrs`, `frozenlist`, `multidict`, `yarl`, and does not
modify any pre-existing package.

Confirm *(read-only)*:

```sh
"$PREFIX/lib/hermes-agent/venv/bin/python3" -c \
  'import slixmpp, slixmpp.plugins.xep_0363.http_upload; print(slixmpp.__version__)'
# expect: 1.17.0
```

> **Why `uv`, not `pip`.** The Hermes gateway venv on this build has **no pip module**.
> `python -m pip` fails with `No module named pip`. Use `uv pip install --python <venv-python>`.

> **If `uv` is not installed** (it is absent on at least one Termux install, contrary to
> `README.md`'s assumption), and the venv's `python -m pip` *and* `ensurepip` are both broken
> (the bundled pip wheel is stripped from the payload), bootstrap pip straight into the gateway
> venv and use that:
>
> ```sh
> curl -fsSL -o /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py
> "$PREFIX/lib/hermes-agent/venv/bin/python3" /tmp/get-pip.py
> "$PREFIX/lib/hermes-agent/venv/bin/python3" -m pip install 'slixmpp[xep-0363]>=1.10,<2'
> ```
>
> Do not install into the system interpreter, and do not use `--target <gateway site-packages>`
> (it ignores already-installed packages and can clobber shared libraries). `pycares` has no
> Android wheel and builds from source, needing `pkg install cmake` first. Snapshot
> `site-packages` before and after and confirm the diff contains only additions. Details and
> numbers: `FIELD-NOTES-2026-10-20.md` §1.

> **Do not use `hermes pm install` / `hermes pm sync`.** On this build the PM syncs with
> `uv sync --frozen --all-packages` **without `--inexact`** — exact mode — which *evicts*
> any package not in the lockfile, including `slixmpp` and `python-telegram-bot`. See
> `KNOWN-ISSUES.md`.

## 2. Place the plugin

```sh
# (changes system)
mkdir -p ~/.hermes/plugins/xmpp-platform
rsync -a --exclude='.git' --exclude='__pycache__' --exclude='.pytest_cache' \
  ~/XmppGateHermes/ ~/.hermes/plugins/xmpp-platform/
```

The Hermes plugin loader discovers any directory under `~/.hermes/plugins/` that contains a
`plugin.yaml`. The key becomes the directory name: `xmpp-platform`.

## 3. Configure credentials

All settings are env vars, read from `~/.hermes/.env`. Prefer a password file or password
command over a plaintext password.

```dotenv
# ~/.hermes/.env   (values are YOURS — never commit this file)

# --- required ---
XMPP_JID="bot@example.org"          # the bot's account JID
XMPP_SERVER="chat.example.org"      # host | host:port | xmpp://host:port

# --- password: use ONE of these three ---
XMPP_PASSWORD_FILE="~/.config/xmpp/bot.pass"   # preferred
# XMPP_PASSWORD_COMMAND="pass show xmpp/bot"    # or a command that prints it
# XMPP_PASSWORD="..."                            # last resort (plaintext)

XMPP_RESOURCE="hermes"              # resource name; authoring device used "flip4"
```

Full env-var reference is in [`CONFIG-REFERENCE.md`](CONFIG-REFERENCE.md). The minimum to
get a working direct-chat bot is: `XMPP_JID`, `XMPP_SERVER`, a password, and
`XMPP_ALLOWED_USERS` + `XMPP_DM_POLICY=allowlist` (otherwise nobody can talk to it).

## 4. Enable the plugin

### 4a. The normal path (works on most installs)

```sh
# (changes system)
hermes plugins enable xmpp-platform
```

### 4b. Termux workaround (when 4a fails with a resolver error)

On the authoring build, `hermes plugins enable` fails with a `uv lock` / `playwright`
resolver error (`KNOWN-ISSUES.md`). The enablement can be applied by editing config
directly — the payload is byte-identical to what `cmd_enable` writes after a successful
admission, minus the broken dependency-resolution step:

```sh
# (changes system)  — always back up first
cp -p ~/.hermes/config.yaml ~/.hermes/config.yaml.bak-plugins-$(date +%Y%m%d-%H%M%S)

printf '\nplugins:\n  enabled:\n    - xmpp-platform\n' >> ~/.hermes/config.yaml
```

Confirm *(read-only)* — must print `Status: enabled`:

```sh
hermes plugins info xmpp-platform
```

Validate the YAML still parses *(read-only)*:

```sh
"$PREFIX/lib/hermes-agent/venv/bin/python3" -c \
  "import sys; sys.path.insert(0,'$PREFIX/lib/hermes-agent/app'); from hermes_cli.config import load_config; print(load_config().get('plugins'))"
```

> Disabling again has the same admission block, so remove the `    - xmpp-platform` line
> from `plugins.enabled` rather than relying on `hermes plugins disable`.

## 5. Restart the gateway

```sh
# (requires restart)
~/gate.sh restart
```

> A new platform adapter **only connects at gateway startup**. The control-socket
> `reload-plugins` verb rewires handlers on already-live adapters; it never creates or
> connects a new one. So a restart is mandatory after enabling.

> **Downtime warning.** The restart drops both messaging connections for ~25–30 s. Because
> the Telegram adapter sets `drop_pending_on_cold_boot: true`, messages that arrive during
> that window are **discarded**, not queued. Restart when your chats are quiet.

## 6. Verify

```sh
# (read-only)  — expect both lines OK
~/gate.sh status

# (read-only)  — expect both markers, and MUC join lines
grep -E "✓ (telegram|xmpp) connected" ~/.hermes/logs/gateway.log | tail
grep "XMPP: MUC .* join confirmed"    ~/.hermes/logs/gateway.log | tail
```

Send a direct message to the bot and confirm a reply. The full diagnosis flow, if anything
is red, is in `TROUBLESHOOTING.md`.

## Why `~/gate.sh` and not `hermes gateway status`?

On Termux, `hermes gateway status` and `hermes gateway stop` are **false negatives** — they
probe systemd/launchd, which do not exist on Android, so a healthy gateway is reported as
"not running". `gate.sh` (a small helper, see `KNOWN-ISSUES.md`) instead reads
`~/.hermes/gateway_state.json` and validates the pid against `/proc/<pid>/cmdline`, which
rejects stale or zombie pids. If you don't want the helper, verify by reading
`gateway_state.json` directly:

```sh
# (read-only)
python3 -c "import json; d=json.load(open('$HOME/.hermes/gateway_state.json')); print(d['gateway_state'], d['pid'], {k:v['state'] for k,v in d['platforms'].items()})"
```

## Rollback

1. Remove `    - xmpp-platform` from `plugins.enabled` in `~/.hermes/config.yaml`
   (or restore the backup you made in step 4b).
2. Remove the plugin directory: `rm -rf ~/.hermes/plugins/xmpp-platform`
3. *(requires restart)* `~/gate.sh restart` — the adapter disconnects on shutdown.
4. Optional, only XMPP used it: `uv pip uninstall --python "$PREFIX/lib/hermes-agent/venv/bin/python3" slixmpp`
   then confirm `import telegram` still works.

No Hermes core file needs to be touched for install or rollback, with one documented
exception: the optional logging patch in `patches/`. Read `patches/README.md` before
applying it, and re-check after any `hermes update`.
