# Contributing

This is a **documentation-first** repo. The adapter works on the authoring device; the
highest-value contributions are corrections and field reports from *other* Termux installs,
because the failure modes here (plugin manager, Android filesystem, PM sync) are the parts
that differ most between devices.

## What helps most

- "Tried it on my device, X happened" reports — device, Termux variant, Hermes version, and
  whether the normal `hermes plugins enable` path worked or you needed the config workaround.
- Fixes to docs where a step was unclear or wrong on your setup.
- Test-suite portability (the suite currently assumes a writable temp dir; more
  platform-conditional skips are fine).

## What to read first

- `docs/KNOWN-ISSUES.md` — the environment quirks. Many "bugs" are already documented.
- `docs/TESTING.md` — what is and isn't covered, and how to run the suite safely.
- The Hermes skill `hermes-xmpp-termux` (`~/.hermes/skills/hermes/hermes-xmpp-termux/`) —
  the in-session runbook this repo documents.

## Ground rules

1. **No secrets, ever.** Not in code, docs, tests, commit messages, or issue text. No real
   JIDs, passwords, tokens, API keys, local IPs, allowlist values, or `.env` contents. Use
   `example.org` placeholders. `.gitignore` excludes `.env*`; keep it that way.
2. **Don't claim what you didn't run.** If you write "verified", you observed it on a real
   install and can say how. Untested changes get labelled as such.
3. **Preserve the honest tone.** Known issues stay documented even when inconvenient. Don't
   soften a failure into a "roadmap item", and don't advertise a fix that only worked once.
4. **Mark command impact.** Tag commands *(read-only)*, *(changes system)*, or
   *(requires restart)*. A restart drops both messaging platforms and can lose messages.
5. **Don't ship broad core patches.** This repo may carry *one* narrowly-scoped Hermes-core
   patch (in `patches/`) because it can't live in a plugin. Anything wider belongs upstream
   in Hermes, not here.

## Making a change

```sh
# fork + clone, then create a branch
git checkout -b <branch>

# run the suite in an isolated venv (see docs/TESTING.md) — do NOT touch the gateway venv
PYTHONPATH="$PWD" "$SCRATCH/.venv/bin/python3" -m pytest tests/ -q

# check nothing sensitive slipped in, and that the tree is clean
git diff --check
git status
```

Before committing, scan for secrets *(read-only)*:

```sh
grep -rniE "password=[^\"'\$<{ ]|token=[A-Za-z0-9]{8}|api[_-]?key\s*[:=]\s*[\"'][A-Za-z0-9]|BEGIN (RSA|OPENSSH|PRIVATE)|sk-[A-Za-z0-9]{20}" . --exclude-dir=.git
```

A single hit on `password=_resolve_password(...)` is a function call, not a secret — but any
other hit should be fixed before commit.

## Docs style

- Prefer a working command over a paragraph of prose.
- Show the *observed* output when it helps (`expect: 1.17.0`).
- When something is environment-specific, say which environment.
- Keep personal/device details out; describe the class of problem, not your JID.

## License

By contributing you agree your changes are distributed under the repo's MIT license,
consistent with the upstream plugin, `slixmpp`, and Hermes Agent.
