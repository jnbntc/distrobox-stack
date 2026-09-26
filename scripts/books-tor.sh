#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/books-ops/tor"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}/books-ops"
PID_FILE="$RUNTIME_DIR/tor.pid"
SOCKS_PORT="${BOOKS_TOR_SOCKS_PORT:-9050}"

mkdir -p "$DATA_DIR" "$RUNTIME_DIR"

is_running() {
    [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

case "${1:-status}" in
    start)
        if is_running; then
            echo "Tor ya está activo (PID $(cat "$PID_FILE"), SOCKS5 127.0.0.1:$SOCKS_PORT)."
            exit 0
        fi

        rm -f "$PID_FILE"
        tor \
            --RunAsDaemon 1 \
            --SocksPort "127.0.0.1:$SOCKS_PORT" \
            --DataDirectory "$DATA_DIR" \
            --PidFile "$PID_FILE" \
            --Log "notice file $DATA_DIR/notices.log"

        echo "Tor iniciado. Proxy SOCKS5: 127.0.0.1:$SOCKS_PORT"
        echo "Usá: torsocks <comando>"
        ;;
    stop)
        if is_running; then
            kill "$(cat "$PID_FILE")"
            rm -f "$PID_FILE"
            echo "Tor detenido."
        else
            rm -f "$PID_FILE"
            echo "Tor no está activo."
        fi
        ;;
    status)
        if is_running; then
            echo "Tor activo (PID $(cat "$PID_FILE"), SOCKS5 127.0.0.1:$SOCKS_PORT)."
        else
            echo "Tor detenido."
            exit 1
        fi
        ;;
    check)
        if ! is_running; then
            echo "Tor no está activo. Ejecutá: books-tor start" >&2
            exit 1
        fi
        curl --fail --silent --show-error \
            --socks5-hostname "127.0.0.1:$SOCKS_PORT" \
            https://check.torproject.org/api/ip | jq .
        ;;
    *)
        echo "Uso: books-tor {start|stop|status|check}" >&2
        exit 2
        ;;
esac
