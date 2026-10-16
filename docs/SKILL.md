# The `hermes-xmpp-termux` skill

The runbook in this repo also exists as a **Hermes skill** — the reusable, in-session form
that loads automatically when Hermes sees an XMPP-on-Termux problem. This page documents
what the skill is, where it lives, and how the two relate.

## Two forms of the same knowledge

| | This repo (`docs/`) | The skill |
| --- | --- | --- |
| Audience | A human, reading on GitHub | Hermes, loading in-session |
| Loaded | Manually, on demand | Automatically when a matching problem appears |
| Location | `~/XmppGateHermes/docs/` | `~/.hermes/skills/hermes/hermes-xmpp-termux/SKILL.md` |
| Copy | — | `skills/hermes-xmpp-termux/SKILL.md` (in this repo) |

The repo ships a copy of the skill under `skills/hermes-xmpp-termux/SKILL.md` so the
project is self-contained: someone installing this project can install the skill too. The
**canonical, live** copy is the one under `~/.hermes/skills/`, which is what Hermes loads.

To install the skill from this repo (changes system — adds a file Hermes will load):

```sh
mkdir -p ~/.hermes/skills/hermes/hermes-xmpp-termux
cp skills/hermes-xmpp-termux/SKILL.md ~/.hermes/skills/hermes/hermes-xmpp-termux/SKILL.md
```

No gateway restart is needed for a skill — skills are read from disk when Hermes decides to
load them, not compiled into the running gateway.

## When the skill triggers

The skill's own frontmatter and `When to Use` section define this. It fires when:

- The XMPP adapter is down, `xmpp` is not `connected`, or the log shows
  `No adapter available for xmpp`.
- You need to enable/disable `xmpp-platform`, or a MUC fails to join.
- `hermes plugins enable|disable xmpp-platform` fails (the PM admission bug).
- **After** a `hermes pm install|sync|repair`, or a Hermes/pkg upgrade, **and** one or both
  messaging platforms stopped connecting — this is the case where the PM-eviction hazard
  (below) actually bites.

It deliberately does **not** fire for general Termux/Hermes issues with no XMPP angle —
those belong to the companion skill `hermes-on-termux`, whose standing rules also apply.

## What it covers (map to this repo's docs)

| Skill section | Repo doc |
| --- | --- |
| Known-good snapshot | `README.md` → Verified baseline |
| Config contract (env keys, names only) | `docs/CONFIG-REFERENCE.md` |
| Dependencies (uv, gateway venv, eviction hazard) | `docs/INSTALLATION.md`, `docs/KNOWN-ISSUES.md` §3 |
| PM admission bug | `docs/KNOWN-ISSUES.md` §1 |
| Enable/disable via config | `docs/INSTALLATION.md` §4 |
| Adapter lifecycle & safe restart | `docs/ARCHITECTURE.md`, `docs/INSTALLATION.md` §5 |
| MUC behavior (triple gate, anonymous rooms) | `docs/ARCHITECTURE.md`, `docs/TROUBLESHOOTING.md` §5 |
| Diagnosis procedure | `docs/TROUBLESHOOTING.md` |
| Backup & rollback | `docs/INSTALLATION.md` → Rollback |
| Rules (no secrets, read-only first) | `docs/SECURITY.md`, `CONTRIBUTING.md` |

The content is intentionally consistent across both forms. If you change one, mirror the
other: edit the repo doc *and* the skill copy, then re-copy the skill into
`~/.hermes/skills/`.

## Secrets policy

The skill — like every file in this repo — carries **no passwords, tokens, API keys, or
`.env` values**. It references `~/.hermes/.env` by **key name only** (`XMPP_JID`,
`XMPP_PASSWORD_FILE`, …), never by value. Its `Rules` section repeats this constraint so a
future edit doesn't regress it.

Verified before commit: the shipped copy is byte-identical to the live skill, and a pattern
scan for JIDs, tokens, and long base64/hex-looking strings found no matches.

## Related skill

- `hermes-on-termux` — general Termux/Hermes platform facts, PM notes, and
  `references/pm-extras-resolution.md`. Not shipped in this repo (it's a separate skill
  covering more than XMPP); its standing rules apply when working on XMPP too.
