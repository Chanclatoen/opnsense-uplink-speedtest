#!/bin/sh
#
# Build this checkout into a real FreeBSD package and install it, so pkg owns every
# file and `pkg delete os-uplink-speedtest` takes them all away again. This is the
# from-source route; most people install the package instead (see README).
# Run as root on the OPNsense box, from the root of the checkout.
#
# Copyright (c) 2026 Chanclatoen. SPDX-License-Identifier: BSD-2-Clause.

set -e

PLUGIN="os-uplink-speedtest"
HERE="$(cd "$(dirname "$0")" && pwd)"

[ "$(id -u)" = "0" ] || { echo "${PLUGIN}: run as root" >&2; exit 1; }

BUILD="$(mktemp -d "/tmp/${PLUGIN}-out.XXXXXX")"
trap 'rm -rf "${BUILD}"' EXIT

# the Ookla and iperf3 engines come from the OPNsense repository, never from a download;
# the default provider (Cloudflare) needs nothing but the Python standard library
for dependency in py313-speedtest-cli iperf3; do
    pkg info -e "${dependency}" || pkg install -y "${dependency}"
done

PACKAGE="$("${HERE}/tools/build-package.sh" "${BUILD}")"

# the package's post-install carries an older release over to the new identifiers; it
# cannot delete that release itself, because pkg holds its database while it runs
pkg add -f "${PACKAGE}"

for candidate in $(pkg query -g %n '*speedtest*' 2>/dev/null); do
    [ "${candidate}" = "${PLUGIN}" ] && continue
    pkg info -l "${candidate}" 2>/dev/null \
        | grep -q '/usr/local/opnsense/scripts/OPNsense/.*/.*_speedtest\.py$' || continue
    pkg delete -y "${candidate}"
done

echo "${PLUGIN} installed. History is kept in /var/db/uplink-speedtest/history.json."
