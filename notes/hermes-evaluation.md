# Hermes Evaluation Notes

Date: 2026-06-06

## Pi State

Initial checks:

- Temperature: 62.6C
- Throttled: `0x0`
- Load average: `1.05, 0.37, 0.22`

During OpenClaw hook activity the Pi briefly reached 74.7C with no throttle flags,
so heavier work was paused until it cooled.

Later checks:

- Temperature after cooldown: 54.9C
- Temperature during skeleton work: 65-68C
- Final observed throttle flag during this run: `0x80000`

## Flake Outputs

Light `nix flake show --json` evaluation succeeded with:

```bash
/home/thanos/.nix-profile/bin/nix --extra-experimental-features 'nix-command flakes' flake show --json --no-write-lock-file .
```

Available for `aarch64-linux`:

- packages: `default`, `messaging`, `full`, `tui`, `web`, `desktop`, `fix-lockfiles`, `configKeys`
- devShell: `default`
- checks: `build-devshell`, `build-package`, `bundled-locales`, `bundled-plugins`,
  `bundled-skills`, `bundled-tui`, `cli-commands`, `config-roundtrip`,
  `cross-eval`, `entry-points-sync`, `extra-dependency-groups`,
  `extra-python-packages`, `hermes-node`, `managed-guard`, `messaging-variant`,
  `package-contents`
- NixOS module: `default`
- overlay: `default`

No flake `apps` were exposed. The default package sets `meta.mainProgram = "hermes"`,
so `nix run .#default -- ...` is the intended app-like route if the package is built.

## Nix Build Dry-Run

Command:

```bash
/home/thanos/.nix-profile/bin/nix --extra-experimental-features 'nix-command flakes' build --no-link --dry-run .#default
```

Result:

- 207 derivations would be built
- about 428 MiB would be downloaded
- about 1.9 GiB would be unpacked

Decision: stop before building/installing. This is too heavy for the requested
Pi-friendly lane without an explicit go-ahead or an off-Pi builder.

## Migration

`hermes claw migrate --dry-run` was not run because Hermes was not installed or
built. No OpenClaw state, services, secrets, or configs were changed.

Recommended next migration command after a reviewed install:

```bash
HERMES_HOME=/home/thanos/.hermes-eval hermes claw migrate --dry-run
```

For a non-secret migration later, prefer:

```bash
HERMES_HOME=/home/thanos/.hermes-eval hermes claw migrate --preset user-data --dry-run
```

Do not migrate secrets without a separate confirmation.

## Rollback Notes

No install was performed, so there is no Hermes package rollback. Current changes
are limited to `~/Projects/hermes-xmpp`.

If Hermes is later installed with Nix profile:

```bash
nix profile remove hermes-agent
```

If run through `nix run`, rollback is simply not invoking it again plus optional
Nix garbage collection later.
