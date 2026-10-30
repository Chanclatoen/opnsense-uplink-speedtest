#!/bin/sh
#
# Carry an older release of this plugin, installed under a different package name, over
# to the identifiers this release uses: settings node, cron command, page privilege,
# dashboard widget and the measurement history. Everything is read off the files that
# are on disk, so a future rename needs no new code here.
#
# Runs from the package's post-install and does nothing when there is no older release.
# It does not remove the old package: pkg holds its database while this runs. It prints
# the command for that instead; install.sh runs it afterwards.
#
#   -n   print the identifiers it found and change nothing
#
# PREFIX and DB exist so tools/test-legacy-migrate.sh can point the detection at a tree
# it built itself; nothing else should set them.
#
# Copyright (c) 2026 Chanclatoen. SPDX-License-Identifier: BSD-2-Clause.

PLUGIN="os-uplink-speedtest"
NAMESPACE="UplinkSpeedtest"      # MVC namespace and config.xml node
ACTION="uplinkspeedtest"         # configd action, also the cron command
WIDGET="uplinkspeedtest"         # dashboard widget id and page privilege
PREFIX="${PREFIX:-/usr/local}"
DB="${DB:-/var/db}"

DATADIR="${DB}/uplink-speedtest"
MODELS="${PREFIX}/opnsense/mvc/app/models/OPNsense"
SCRIPTS="${PREFIX}/opnsense/scripts/OPNsense"
ACTIONS="${PREFIX}/opnsense/service/conf/actions.d"
METADATA="${PREFIX}/opnsense/www/js/widgets/Metadata"
VERSIONS="${PREFIX}/opnsense/version"

DRYRUN=""
[ "$1" = "-n" ] && DRYRUN="yes"

# the old MVC namespace: another plugin directory holding an engine named *_speedtest.py
OLD_NS=""
for directory in "${SCRIPTS}"/*; do
    namespace="${directory##*/}"
    [ "${namespace}" = "${NAMESPACE}" ] && continue
    ls "${directory}"/*_speedtest.py >/dev/null 2>&1 || continue
    [ -f "${MODELS}/${namespace}/General.xml" ] || continue
    OLD_NS="${namespace}"
    break
done
[ -n "${OLD_NS}" ] || { [ -n "${DRYRUN}" ] && echo "ns="; exit 0; }

# the old configd action: the actions file whose commands point into that directory
OLD_ACTION=""
for conf in "${ACTIONS}"/actions_*.conf; do
    grep -q "/OPNsense/${OLD_NS}/" "${conf}" 2>/dev/null || continue
    OLD_ACTION="${conf##*/actions_}"
    OLD_ACTION="${OLD_ACTION%.conf}"
    break
done

# the old widget id: the one element indented inside <metadata>
OLD_WIDGET=""
OLD_META="${METADATA}/${OLD_NS}.xml"
[ -f "${OLD_META}" ] && OLD_WIDGET="$(sed -n 's|^[[:space:]][[:space:]]*<\([a-z0-9]\{1,\}\)>$|\1|p' "${OLD_META}" | head -1)"

# the old package name: its version stamp, which is the package name without the os- prefix
OLD_PLUGIN=""
for stamp in "${VERSIONS}"/*speedtest*; do
    name="${stamp##*/}"
    [ "${name}" = "uplink-speedtest" ] && continue
    [ -f "${stamp}" ] || continue
    OLD_PLUGIN="${name}"
    break
done
OLD_DATA="${DB}/${OLD_PLUGIN}"

if [ -n "${DRYRUN}" ]; then
    echo "ns=${OLD_NS} action=${OLD_ACTION} widget=${OLD_WIDGET} plugin=${OLD_PLUGIN}"
    exit 0
fi

echo "${PLUGIN}: upgrading from ${OLD_PLUGIN:-an earlier release} (namespace ${OLD_NS}, action ${OLD_ACTION}, widget ${OLD_WIDGET})"

if [ -z "${OLD_ACTION}" ] || [ -z "${OLD_WIDGET}" ]; then
    echo "${PLUGIN}: could not read the old identifiers off the filesystem; settings not migrated" >&2
    exit 1
fi

# the migrator saves through OPNsense's own config API, which keeps a restorable copy
# under /conf/backup first, so no extra backup is made here
"${SCRIPTS}/${NAMESPACE}/migrate-legacy-config.php" \
    "${OLD_NS}" "${NAMESPACE}" "${OLD_ACTION}" "${ACTION}" "${OLD_WIDGET}" "${WIDGET}" || exit 1

# the measurement history is not owned by pkg, so it survives on its own path
if [ -n "${OLD_PLUGIN}" ] && [ -d "${OLD_DATA}" ] && [ "${OLD_DATA}" != "${DATADIR}" ]; then
    if [ -f "${DATADIR}/history.json" ]; then
        echo "${PLUGIN}: ${DATADIR}/history.json already exists, left ${OLD_DATA} alone" >&2
    else
        for file in "${OLD_DATA}"/*; do
            [ -e "${file}" ] || continue
            mv "${file}" "${DATADIR}/"
        done
        rmdir "${OLD_DATA}" 2>/dev/null
        echo "${PLUGIN}: history moved ${OLD_DATA} -> ${DATADIR}"
    fi
fi

[ -n "${OLD_PLUGIN}" ] && echo "${PLUGIN}: now remove the old package:  pkg delete -y os-${OLD_PLUGIN}"
exit 0
