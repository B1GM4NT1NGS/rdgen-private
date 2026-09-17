#!/bin/sh
set -eu

SOURCE_DIR=/opt/rdgen-seed
APP_DIR=/opt/rdgen

mkdir -p "$APP_DIR" /data "$APP_DIR/exe" "$APP_DIR/png" "$APP_DIR/temp_zips"
if [ ! -f "$APP_DIR/manage.py" ]; then
    cp -a "$SOURCE_DIR/." "$APP_DIR/"
fi

chown -R user:user "$APP_DIR" /data

cd "$APP_DIR"
if [ -f /config/rdgen.env ]; then
    exec /usr/local/bin/rdgen-env-exec /config/rdgen.env su-exec user "$@"
fi

exec su-exec user "$@"
