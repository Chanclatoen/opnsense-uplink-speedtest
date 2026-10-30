#!/bin/sh
#
# Build the package and a signed pkg repository into dist/. Runs inside the FreeBSD VM
# of .github/workflows/package.yml; the signing key is dropped next to the checkout by
# the workflow and removed again by it.
#
#   dist/<package>.pkg          attached to the GitHub Release
#   dist/<package>.pkg.sha256
#   dist/site/                  published to GitHub Pages: the repository plus the two
#                               files a firewall needs to trust and reach it
#
# Copyright (c) 2026 Chanclatoen. SPDX-License-Identifier: BSD-2-Clause.

set -e

HERE="$(cd "$(dirname "$0")/.." && pwd)"
KEY="${HERE}/.signkey"
cd "${HERE}"

[ -s "${KEY}" ] || { echo "no signing key at ${KEY}" >&2; exit 1; }

rm -rf dist
mkdir -p dist/site/pkg/All

PACKAGE="$(tools/build-package.sh "${HERE}/dist")"
NAME="$(basename "${PACKAGE}")"
cp "${PACKAGE}" "dist/site/pkg/All/${NAME}"
(cd dist && sha256 -r "${NAME}" | awk '{print $1 "  " $2}' > "${NAME}.sha256")

# signs meta.conf and packagesite.pkg; the per-package checksums live in packagesite,
# so a client with the public key cannot be handed a package we did not build
pkg repo dist/site/pkg "${KEY}"

cp repo/uplink-speedtest.pub repo/uplink-speedtest.conf repo/index.html dist/site/
touch dist/site/.nojekyll

echo "--- dist ---"
find dist -type f | sort
pkg info -F "${PACKAGE}"
