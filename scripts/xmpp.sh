#!/data/data/com.termux/files/usr/bin/bash
# xmpp.sh — control helper for the Hermes gateway running the XMPP platform
# plugin on Termux/Android (no systemd/launchd, so `hermes gateway status`
# is a false negative here; this reads gateway_state.json and validates the
# pid against /proc instead).
#
#   ./xmpp.sh start     start the gateway (background, logged)
#   ./xmpp.sh stop      graceful SIGTERM, SIGKILL only if it will not die
#   ./xmpp.sh restart   stop, wait for the MUC ghost to clear, start
#   ./xmpp.sh status    state, pid, uptime, platform states, join history
#   ./xmpp.sh log [N]   follow gateway.log (last N lines, default 60)
#   ./xmpp.sh edit      back up ~/.hermes/.env, edit it, show key names only
#
# Never prints secret values: only env KEY NAMES are ever echoed.

set -uo pipefail

HERMES_HOME_DIR="${HOME}/.hermes"
STATE="${HERMES_HOME_DIR}/gateway_state.json"
LOGDIR="${HERMES_HOME_DIR}/logs"
GLOG="${LOGDIR}/gateway.log"
CONSOLE="${LOGDIR}/gateway-console.log"
ENVF="${HERMES_HOME_DIR}/.env"
HERMES_BIN="$(command -v hermes || echo "${PREFIX}/bin/hermes")"
# Seconds to wait between stop and start: a MUC keeps the old occupant entry
# ("ghost") for ~1-2 min; rejoining with the same nick during that window is
# what gets a fresh session kicked 0.2s after it joins.
RESTART_DELAY="${XMPP_RESTART_DELAY:-90}"

die() { printf 'xmpp.sh: %s\n' "$*" >&2; exit 1; }

state_field() { # state_field <python-expr over d>
    [ -f "$STATE" ] || { echo ""; return; }
    python3 - "$STATE" "$1" <<'PY' 2>/dev/null
import json, sys
path, expr = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(path))
except Exception:
    print("")
    raise SystemExit(0)
print(eval(expr, {"d": d}) or "")
PY
}

gateway_pid() { state_field "d.get('pid')"; }

pid_is_gateway() {
    local p="${1:-}"
    [ -n "$p" ] && [ -d "/proc/$p" ] || return 1
    tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null | grep -q 'gateway run'
}

uptime_of() {
    local p="$1" secs
    secs="$(ps -o etime= -p "$p" 2>/dev/null | tr -d ' ')"
    echo "${secs:-?}"
}

env_val() { grep -m1 "^$1=" "$ENVF" 2>/dev/null | cut -d= -f2-; }

wait_for_xmpp() { # wait_for_xmpp <seconds>
    local deadline=$(( $(date +%s) + ${1:-45} ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if [ "$(state_field "d.get('platforms',{}).get('xmpp',{}).get('state')")" = "connected" ]; then
            return 0
        fi
        sleep 2
    done
    return 1
}

cmd_status() {
    local pid state alive
    state="$(state_field "d.get('gateway_state')")"
    pid="$(gateway_pid)"
    if pid_is_gateway "$pid"; then alive="yes"; else alive="no"; fi

    if [ "$alive" = yes ]; then
        printf 'gateway : %s\n' "${state:-unknown}"
    else
        printf 'gateway : stopped (last recorded: %s)\n' "${state:-unknown}"
    fi
    printf 'pid     : %s (%s)\n' "${pid:-?}" "$([ "$alive" = yes ] && echo alive || echo "not running")"
    [ "$alive" = yes ] && printf 'uptime  : %s\n' "$(uptime_of "$pid")"
    printf 'platform: '
    if [ -f "$STATE" ]; then
        python3 - "$STATE" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
plats = d.get("platforms") or {}
if not plats:
    print("(none)")
for name, info in plats.items():
    print(f"{name}={info.get('state')} updated={info.get('updated_at','?')}")
PY
    else
        printf '(no %s)\n' "$STATE"
    fi

    printf 'jid     : %s\n' "$(env_val XMPP_JID)"
    printf 'resource: %s\n' "$(env_val XMPP_RESOURCE)"
    printf 'server  : %s:%s\n' "$(env_val XMPP_SERVER)" "$(env_val XMPP_PORT)"
    printf 'rooms   : %s\n' "$(env_val XMPP_ROOMS)"

    if [ -f "$GLOG" ]; then
        printf '\nlast room events:\n'
        grep -E 'join confirmed|join NOT confirmed|MUC .* joining' "$GLOG" 2>/dev/null | tail -4 | sed 's/^/  /'
        if [ "$alive" = yes ] && [ "$(state_field "d.get('platforms',{}).get('xmpp',{}).get('state')")" = "connected" ]; then
            printf '\nhint: adapter only joins rooms at connect/reconnect — a MUC kick leaves the bot\n'
            printf '      silently absent until a restart. `./xmpp.sh restart` fixes that.\n'
        fi
    fi
}

cmd_start() {
    local pid
    pid="$(gateway_pid)"
    if pid_is_gateway "$pid"; then
        printf 'already running (pid %s) — nothing to do\n' "$pid"
        [ "$(state_field "d.get('platforms',{}).get('xmpp',{}).get('state')")" = "connected" ] \
            && printf 'xmpp: connected\n' || printf 'xmpp: not connected (check ./xmpp.sh log)\n'
        return 0
    fi
    [ -x "$HERMES_BIN" ] || die "hermes binary not found"
    mkdir -p "$LOGDIR"
    cd "$HOME" || die "cannot cd $HOME"
    printf 'starting gateway...\n'
    nohup setsid "$HERMES_BIN" gateway run --accept-hooks >>"$CONSOLE" 2>&1 &
    disown 2>/dev/null || true
    if wait_for_xmpp 45; then
        printf 'gateway up, pid %s, xmpp connected\n' "$(gateway_pid)"
        return 0
    fi
    printf 'gateway started but xmpp not connected within 45s\n' >&2
    [ -f "$GLOG" ] && tail -n 12 "$GLOG" | sed 's/^/  /' >&2
    return 1
}

cmd_stop() {
    local pid i
    pid="$(gateway_pid)"
    if ! pid_is_gateway "$pid"; then
        printf 'not running\n'
        return 0
    fi
    printf 'stopping pid %s...\n' "$pid"
    kill -TERM "$pid" 2>/dev/null
    for i in $(seq 1 20); do
        pid_is_gateway "$pid" || { printf 'stopped\n'; return 0; }
        sleep 1
    done
    printf 'did not exit after 20s — sending SIGKILL\n'
    kill -KILL "$pid" 2>/dev/null
    sleep 2
    pid_is_gateway "$pid" && die "pid $pid still alive"
    printf 'stopped (forced)\n'
}

cmd_restart() {
    cmd_stop || return 1
    printf 'waiting %ss so the old MUC occupant entry expires (avoids ghost-nick kick)\n' "$RESTART_DELAY"
    printf 'override with XMPP_RESTART_DELAY=<seconds> ./xmpp.sh restart\n'
    sleep "$RESTART_DELAY"
    cmd_start
}

cmd_log() {
    local n="${1:-60}"
    [ -f "$GLOG" ] || die "no log at $GLOG"
    tail -n "$n" -f "$GLOG"
}

cmd_edit() {
    [ -f "$ENVF" ] || die "no $ENVF"
    local stamp backup editor
    stamp="$(date +%Y%m%d-%H%M%S)"
    backup="${ENVF}.bak-edit-${stamp}"
    cp -p "$ENVF" "$backup" || die "backup failed"
    chmod 600 "$ENVF" "$backup" 2>/dev/null
    printf 'backup : %s\n' "$backup"
    editor="${EDITOR:-}"
    if [ -z "$editor" ]; then
        for cand in nano vi vim; do command -v "$cand" >/dev/null && { editor="$cand"; break; }; done
    fi
    [ -n "$editor" ] || die "no editor found; set EDITOR"
    "$editor" "$ENVF"
    printf '\nXMPP keys now defined (names only):\n'
    grep -oE '^XMPP_[A-Z_]+' "$ENVF" | sort | sed 's/^/  /'
    printf '\nchanged lines vs backup (values masked):\n'
    diff <(sed 's/=.*/=***/' "$backup") <(sed 's/=.*/=***/' "$ENVF") | sed -n 's/^[<>]/  &/p' || true
    printf '\nrestart the gateway for changes to take effect: ./xmpp.sh restart\n'
}

case "${1:-}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    status)  cmd_status ;;
    log)     shift; cmd_log "${1:-60}" ;;
    edit)    cmd_edit ;;
    *)
        cat >&2 <<EOF
usage: $0 {start|stop|restart|status|log [N]|edit}
  start     start the Hermes gateway in the background (waits for xmpp)
  stop      graceful stop (SIGTERM, then SIGKILL after 20s)
  restart   stop, wait ${RESTART_DELAY}s for the MUC ghost to clear, start
  status    gateway/pid/uptime, platform states, jid/resource/rooms, room events
  log [N]   follow gateway.log, last N lines (default 60)
  edit      back up and edit ~/.hermes/.env (values are never echoed)
EOF
        exit 2 ;;
esac
