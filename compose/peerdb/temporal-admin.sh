#!/bin/sh
set -eu

until temporal operator search-attribute list >/dev/null 2>&1; do
  sleep 2
done

if ! temporal operator search-attribute list | grep -w MirrorName >/dev/null 2>&1; then
  temporal operator search-attribute create \
    --name MirrorName --type Text --namespace default
fi

exec tini -s -- sleep infinity
