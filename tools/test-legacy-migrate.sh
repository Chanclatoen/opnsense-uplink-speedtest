#!/bin/sh
#
# Checks that legacy-migrate.sh reads the right identifiers off a tree shaped like an
# older release of this plugin, and finds nothing when there is no older release. Runs
# anywhere with a POSIX shell; no OPNsense, no pkg, no root.
#
# Copyright (c) 2026 Chanclatoen. SPDX-License-Identifier: BSD-2-Clause.

set -e

HERE="$(cd "$(dirname "$0")/.." && pwd)"
MIGRATE="${HERE}/src/opnsense/scripts/OPNsense/UplinkSpeedtest/legacy-migrate.sh"
ROOT="$(mktemp -d /tmp/test-legacy-migrate.XXXXXX)"
trap 'rm -rf "${ROOT}"' EXIT

fake_release() {   # fake_release <namespace> <action> <widget> <plugin>
    mkdir -p "${ROOT}/usr/local/opnsense/scripts/OPNsense/$1" \
             "${ROOT}/usr/local/opnsense/mvc/app/models/OPNsense/$1" \
             "${ROOT}/usr/local/opnsense/service/conf/actions.d" \
             "${ROOT}/usr/local/opnsense/www/js/widgets/Metadata" \
             "${ROOT}/usr/local/opnsense/version"
    : > "${ROOT}/usr/local/opnsense/scripts/OPNsense/$1/$(echo "$1" | tr 'A-Z' 'a-z')_speedtest.py"
    : > "${ROOT}/usr/local/opnsense/mvc/app/models/OPNsense/$1/General.xml"
    echo "command:/usr/local/opnsense/scripts/OPNsense/$1/x_speedtest.py run" \
        > "${ROOT}/usr/local/opnsense/service/conf/actions.d/actions_$2.conf"
    printf '<metadata>\n    <%s>\n        <filename>%s.js</filename>\n    </%s>\n</metadata>\n' \
        "$3" "$1" "$3" > "${ROOT}/usr/local/opnsense/www/js/widgets/Metadata/$1.xml"
    echo "1.1.3" > "${ROOT}/usr/local/opnsense/version/$4"
}

expect() {   # expect <description> <wanted> <got>
    if [ "$2" = "$3" ]; then
        echo "ok   $1"
    else
        echo "FAIL $1" >&2
        echo "     wanted: $2" >&2
        echo "     got:    $3" >&2
        exit 1
    fi
}

# nothing installed at all
mkdir -p "${ROOT}/usr/local/opnsense/scripts/OPNsense" "${ROOT}/var/db"
expect "empty tree finds no older release" "ns=" \
    "$(PREFIX="${ROOT}/usr/local" DB="${ROOT}/var/db" sh "${MIGRATE}" -n)"

# only this release installed
mkdir -p "${ROOT}/usr/local/opnsense/scripts/OPNsense/UplinkSpeedtest" \
         "${ROOT}/usr/local/opnsense/mvc/app/models/OPNsense/UplinkSpeedtest" \
         "${ROOT}/usr/local/opnsense/version"
: > "${ROOT}/usr/local/opnsense/scripts/OPNsense/UplinkSpeedtest/uplink_speedtest.py"
: > "${ROOT}/usr/local/opnsense/mvc/app/models/OPNsense/UplinkSpeedtest/General.xml"
echo "1.2.1" > "${ROOT}/usr/local/opnsense/version/uplink-speedtest"
expect "own install is not mistaken for an older one" "ns=" \
    "$(PREFIX="${ROOT}/usr/local" DB="${ROOT}/var/db" sh "${MIGRATE}" -n)"

# the 1.1.3 release, under its own package name
fake_release LegacySpeedtest legacyspeedtest legacyspeedtest legacy-speedtest
expect "reads the old identifiers" \
    "ns=LegacySpeedtest action=legacyspeedtest widget=legacyspeedtest plugin=legacy-speedtest" \
    "$(PREFIX="${ROOT}/usr/local" DB="${ROOT}/var/db" sh "${MIGRATE}" -n)"

echo "all checks passed"
