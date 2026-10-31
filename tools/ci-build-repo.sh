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

PKG_VERSION="2.3.1_1"
PKG_SHA256="74dbb941de91fda8b470eeab78926170e35737346fbe55e8a2e4c3968f79e1e3"
PKG_PACKAGE="/tmp/pkg-${PKG_VERSION}.pkg"
fetch -qo "${PKG_PACKAGE}" "https://pkg.opnsense.org/FreeBSD:14:amd64/26.1/latest/All/pkg-${PKG_VERSION}.pkg"
[ "$(sha256 -q "${PKG_PACKAGE}")" = "${PKG_SHA256}" ] || { echo "pkg ${PKG_VERSION}: checksum mismatch" >&2; exit 1; }
pkg add -f "${PKG_PACKAGE}"
hash -r
[ "$(pkg -v)" = "2.3.1" ] || { echo "expected pkg 2.3.1, got $(pkg -v)" >&2; exit 1; }

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
