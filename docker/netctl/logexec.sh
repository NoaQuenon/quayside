#!/bin/sh
# A simple wrapper to log stuff to Docker logs

set -eu

if [ "$#" -eq 0 ]; then
    echo "usage: logexec CMD [ARGS...]" >&2
    exit 2
fi

quote() {
    case "$1" in
        '' | *[!A-Za-z0-9_./:=@%+,-]*) printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")" ;;
        *) printf '%s' "$1" ;;
    esac
}

line="$(date -u '+%Y-%m-%dT%H:%M:%SZ') \$"

for arg in "$@"; do
    line="$line $(quote "$arg")"
done

printf '%s\n' "$line" > "/proc/$(cat /run/main.pid)/fd/1"

exec "$@"
