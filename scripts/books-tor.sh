#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/books-ops/tor"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}/books-ops"
PID_FILE="$RUNTIME_DIR/tor.pid"
SOCKS_PORT="${BOOKS_TOR_SOCKS_PORT:-9050}"
LOG_FILE="$DATA_DIR/notices.log"
CACHE_DIR="$DATA_DIR/cache"

mkdir -p "$DATA_DIR" "$CACHE_DIR" "$RUNTIME_DIR"
chmod 700 "$DATA_DIR" "$CACHE_DIR" "$RUNTIME_DIR" 2>/dev/null || true

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
            -f /dev/null \
            --defaults-torrc /dev/null \
            --RunAsDaemon 1 \
            --ClientOnly 1 \
            --SocksPort "127.0.0.1:$SOCKS_PORT" \
            --DataDirectory "$DATA_DIR" \
            --CacheDirectory "$CACHE_DIR" \
            --PidFile "$PID_FILE" \
            --Log "notice file $LOG_FILE"

        sleep 1
        if ! is_running; then
            echo "Tor no pudo iniciar. Últimas líneas del log:" >&2
            tail -n 40 "$LOG_FILE" >&2 2>/dev/null || true
            exit 1
        fi

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
    logs)
        touch "$LOG_FILE"
        tail -n 60 "$LOG_FILE"
        ;;
    *)
        echo "Uso: books-tor {start|stop|status|check|logs}" >&2
        exit 2
        ;;
esac
