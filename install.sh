#!/bin/sh
#
# Build this checkout into a real FreeBSD package and install it, so pkg owns every
# file and `pkg delete os-uplink-speedtest` takes them all away again.
# Run as root on the OPNsense box, from the root of the checkout.
#
# Copyright (c) 2026 Chanclatoen. SPDX-License-Identifier: BSD-2-Clause.

set -e

PLUGIN="os-uplink-speedtest"
VERSION="1.2.0"
NAMESPACE="UplinkSpeedtest"      # MVC namespace and config.xml node
ACTION="uplinkspeedtest"         # configd action, also the cron command
WIDGET="uplinkspeedtest"         # dashboard widget id and page privilege
DATADIR="/var/db/uplink-speedtest"
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="${HERE}/src"

[ "$(id -u)" = "0" ] || { echo "${PLUGIN}: run as root" >&2; exit 1; }
[ -d "${SRC}/opnsense" ] || { echo "${PLUGIN}: no src/opnsense next to $0" >&2; exit 1; }

STAGE="$(mktemp -d "/tmp/${PLUGIN}-stage.XXXXXX")"
BUILD="$(mktemp -d "/tmp/${PLUGIN}-build.XXXXXX")"
trap 'rm -rf "${STAGE}" "${BUILD}"' EXIT

# the Ookla and iperf3 engines come from the OPNsense repository, never from a download;
# the default provider (Cloudflare) needs nothing but the Python standard library
for dependency in py313-speedtest-cli iperf3; do
    pkg info -e "${dependency}" || pkg install -y "${dependency}"
done
OOKLA_ORIGIN="$(pkg query %o py313-speedtest-cli)"
OOKLA_VERSION="$(pkg query %v py313-speedtest-cli)"
IPERF3_ORIGIN="$(pkg query %o iperf3)"
IPERF3_VERSION="$(pkg query %v iperf3)"

# ---------------------------------------------------------------------------
# An earlier release of this plugin may be installed under a different package
# name. Everything needed to carry it over is read off that package itself, so
# this works for any past (or future) rename, not one hard-coded one.
# ---------------------------------------------------------------------------
LEGACY=""
for candidate in $(pkg query -g %n '*speedtest*' 2>/dev/null); do
    [ "${candidate}" = "${PLUGIN}" ] && continue
    pkg info -l "${candidate}" 2>/dev/null \
        | grep -q '/usr/local/opnsense/scripts/OPNsense/.*/.*_speedtest\.py$' || continue
    LEGACY="${candidate}"
    break
done

if [ -n "${LEGACY}" ]; then
    LEGACY_FILES="$(pkg info -l "${LEGACY}")"
    LEGACY_NS="$(echo "${LEGACY_FILES}" | sed -n 's|.*/mvc/app/models/OPNsense/\([^/]*\)/General\.xml$|\1|p' | head -1)"
    LEGACY_ACTION="$(echo "${LEGACY_FILES}" | sed -n 's|.*/actions\.d/actions_\([^/]*\)\.conf$|\1|p' | head -1)"
    LEGACY_META="$(echo "${LEGACY_FILES}" | sed -n 's|^[[:space:]]*\(/usr/local/opnsense/www/js/widgets/Metadata/.*\.xml\)$|\1|p' | head -1)"
    LEGACY_WIDGET=""
    # the widget id is the one element indented inside <metadata>
    [ -f "${LEGACY_META}" ] && LEGACY_WIDGET="$(sed -n 's|^[[:space:]][[:space:]]*<\([a-z0-9]\{1,\}\)>$|\1|p' "${LEGACY_META}" | head -1)"
    LEGACY_DATA="/var/db/${LEGACY#os-}"

    echo "${PLUGIN}: upgrading from ${LEGACY} (namespace ${LEGACY_NS}, action ${LEGACY_ACTION}, widget ${LEGACY_WIDGET})"

    if [ -n "${LEGACY_NS}" ] && [ -n "${LEGACY_ACTION}" ] && [ -n "${LEGACY_WIDGET}" ]; then
        # the migrator saves through OPNsense's own config API, which keeps a restorable
        # copy under /conf/backup first, so no extra backup is made here
        "${HERE}/tools/migrate-legacy-config.php" \
            "${LEGACY_NS}" "${NAMESPACE}" "${LEGACY_ACTION}" "${ACTION}" "${LEGACY_WIDGET}" "${WIDGET}"
    else
        echo "${PLUGIN}: could not read the old identifiers off ${LEGACY}; settings not migrated" >&2
    fi

    # the measurement history is not owned by pkg, so it survives on its own path
    if [ -d "${LEGACY_DATA}" ] && [ ! -d "${DATADIR}" ]; then
        mv "${LEGACY_DATA}" "${DATADIR}"
        echo "${PLUGIN}: history moved ${LEGACY_DATA} -> ${DATADIR}"
    elif [ -d "${LEGACY_DATA}" ]; then
        echo "${PLUGIN}: ${DATADIR} already exists, left ${LEGACY_DATA} alone" >&2
    fi

    pkg delete -y "${LEGACY}"
fi

mkdir -p "${STAGE}/usr/local/opnsense/version"
tar -cf - -C "${SRC}" . | tar -xf - -C "${STAGE}/usr/local"
# a checkout that was run from in place has __pycache__ in it; those bytes are not ours to ship
find "${STAGE}" -name __pycache__ -type d -prune -exec rm -rf {} +
echo "${VERSION}" > "${STAGE}/usr/local/opnsense/version/uplink-speedtest"
find "${STAGE}" -type d -exec chmod 755 {} +
find "${STAGE}" -type f -exec chmod 644 {} +
chmod 755 "${STAGE}/usr/local/opnsense/scripts/OPNsense/UplinkSpeedtest/uplink_speedtest.py"
chmod 755 "${STAGE}/usr/local/opnsense/scripts/OPNsense/UplinkSpeedtest/uplink_cloudflare.py"

(cd "${STAGE}" && find . -type f | sed 's|^\.||' | sort) > "${BUILD}/plist"

cat > "${BUILD}/manifest" <<MANIFEST
name: ${PLUGIN}
version: "${VERSION}"
origin: opnsense/${PLUGIN}
comment: "Periodic uplink speedtest with a dashboard widget"
desc: <<DESC
$(cat "${HERE}/pkg-descr")
DESC
maintainer: 188175474+Chanclatoen@users.noreply.github.com
www: https://github.com/Chanclatoen/opnsense-uplink-speedtest
prefix: /usr/local
categories: [net]
licenselogic: single
licenses: [BSD2CLAUSE]
deps: {
  py313-speedtest-cli: { origin: "${OOKLA_ORIGIN}", version: "${OOKLA_VERSION}" }
  iperf3: { origin: "${IPERF3_ORIGIN}", version: "${IPERF3_VERSION}" }
}
annotations: {
  product_id: uplink-speedtest
  product_name: uplink-speedtest
  product_version: "${VERSION}"
}
scripts: {
  post-install: <<POSTINSTALL
install -d -m 0755 -o root -g wheel /var/db/uplink-speedtest
rm -f /var/lib/php/tmp/opnsense_acl_cache.json /var/lib/php/tmp/opnsense_menu_cache.xml
rm -f /tmp/opnsense_acl_cache.json /tmp/opnsense_menu_cache.xml
rm -f /var/lib/php/cache/*.php
/usr/local/etc/rc.d/configd restart
POSTINSTALL
  post-deinstall: <<POSTDEINSTALL
rm -rf /usr/local/opnsense/scripts/OPNsense/UplinkSpeedtest/__pycache__
rm -f /tmp/uplink-speedtest.lock
rm -f /var/lib/php/tmp/opnsense_acl_cache.json /var/lib/php/tmp/opnsense_menu_cache.xml
rm -f /tmp/opnsense_acl_cache.json /tmp/opnsense_menu_cache.xml
rm -f /var/lib/php/cache/*.php
/usr/local/etc/rc.d/configd restart
POSTDEINSTALL
}
MANIFEST

pkg create -M "${BUILD}/manifest" -r "${STAGE}" -p "${BUILD}/plist" -o "${BUILD}"
PACKAGE="$(ls "${BUILD}"/${PLUGIN}-${VERSION}.pkg "${BUILD}"/${PLUGIN}-${VERSION}.txz 2>/dev/null | head -1)"
[ -n "${PACKAGE}" ] || { echo "${PLUGIN}: pkg create produced nothing" >&2; exit 1; }

pkg add -f "${PACKAGE}"
echo "${PLUGIN} ${VERSION} installed. History is kept in /var/db/uplink-speedtest/history.json."
