#!/bin/sh
#
# Remove the package. Measurement history in /var/db/uplink-speedtest is kept on
# purpose, so a reinstall picks it up again; pass --purge to delete it as well.
#
# Copyright (c) 2026 Uplink IT. SPDX-License-Identifier: BSD-2-Clause.

set -e

[ "$(id -u)" = "0" ] || { echo "os-uplink-speedtest: run as root" >&2; exit 1; }

pkg delete -y os-uplink-speedtest

if [ "$1" = "--purge" ]; then
    rm -rf /var/db/uplink-speedtest
    echo "measurement history deleted"
fi
