#!/bin/sh
#
# Build this checkout into a FreeBSD package in <output-dir> and print its path.
# Runs on an OPNsense box (install.sh) and on a plain FreeBSD builder (CI); the only
# difference is where the dependency versions come from.
#
# Copyright (c) 2026 Chanclatoen. SPDX-License-Identifier: BSD-2-Clause.

set -e

PLUGIN="os-uplink-speedtest"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${HERE}/src"
OUT="${1:?usage: build-package.sh <output-dir>}"

VERSION="$(sed -n 's/^PLUGIN_VERSION=[[:space:]]*//p' "${HERE}/Makefile")"
[ -n "${VERSION}" ] || { echo "${PLUGIN}: no PLUGIN_VERSION in Makefile" >&2; exit 1; }
[ -d "${SRC}/opnsense" ] || { echo "${PLUGIN}: no src/opnsense in ${HERE}" >&2; exit 1; }

# The dependencies come from the OPNsense repository. On the firewall we record the
# versions that are actually installed, like the official plugin build does; off the
# firewall there is nothing to read, so we record the oldest release the plugin was
# written against and let pkg pick whatever OPNsense offers above it.
dep_field() { pkg query "$1" "$2" 2>/dev/null | head -1; }
OOKLA_ORIGIN="$(dep_field %o py313-speedtest-cli)"; : "${OOKLA_ORIGIN:=net/py-speedtest-cli}"
OOKLA_VERSION="$(dep_field %v py313-speedtest-cli)"; : "${OOKLA_VERSION:=2.1.3}"
IPERF3_ORIGIN="$(dep_field %o iperf3)"; : "${IPERF3_ORIGIN:=benchmarks/iperf3}"
IPERF3_VERSION="$(dep_field %v iperf3)"; : "${IPERF3_VERSION:=3.17}"

STAGE="$(mktemp -d "/tmp/${PLUGIN}-stage.XXXXXX")"
BUILD="$(mktemp -d "/tmp/${PLUGIN}-build.XXXXXX")"
trap 'rm -rf "${STAGE}" "${BUILD}"' EXIT

mkdir -p "${STAGE}/usr/local/opnsense/version"
tar -cf - -C "${SRC}" . | tar -xf - -C "${STAGE}/usr/local"
# a checkout that was run from in place has __pycache__ in it; those bytes are not ours to ship
find "${STAGE}" -name __pycache__ -type d -prune -exec rm -rf {} +
echo "${VERSION}" > "${STAGE}/usr/local/opnsense/version/uplink-speedtest"
find "${STAGE}" -type d -exec chmod 755 {} +
find "${STAGE}" -type f -exec chmod 644 {} +
for executable in uplink_speedtest.py uplink_cloudflare.py migrate-legacy-config.php legacy-migrate.sh; do
    chmod 755 "${STAGE}/usr/local/opnsense/scripts/OPNsense/UplinkSpeedtest/${executable}"
done

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
/usr/local/opnsense/scripts/OPNsense/UplinkSpeedtest/legacy-migrate.sh || true
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

mkdir -p "${OUT}"
pkg create -M "${BUILD}/manifest" -r "${STAGE}" -p "${BUILD}/plist" -o "${OUT}" >&2
PACKAGE="$(ls "${OUT}"/${PLUGIN}-${VERSION}.pkg "${OUT}"/${PLUGIN}-${VERSION}.txz 2>/dev/null | head -1)"
[ -n "${PACKAGE}" ] || { echo "${PLUGIN}: pkg create produced nothing" >&2; exit 1; }
echo "${PACKAGE}"
