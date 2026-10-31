# Changelog

All notable changes to this project. Versions are the package version
(`pkg info os-uplink-speedtest`).

## 1.2.2 — 2026-10-31

* Build packages with OPNsense 26.1's pkg 2.3.1, so every installed file has a
  SHA-256 checksum that the target firewall can verify.
* Reject a CI build before publishing unless every package file checksum uses the
  `1$` SHA-256 format accepted by OPNsense.

## 1.2.1 — 2026-10-30

### Added
* **Real packages, two ways to install.** A GitHub Actions workflow builds the package on a
  FreeBSD 14 VM for every `v*` tag, attaches it and its checksum to the GitHub Release, and
  publishes a signed `pkg` repository to GitHub Pages. Adding that repository once makes the
  plugin install and update from **System → Firmware → Plugins** like any other, which
  replaces "copy the checkout to the firewall and run a script as root" as the way in.

### Changed
* The package build moved out of `install.sh` into `tools/build-package.sh`, so the firewall
  and the release workflow produce the same package from the same manifest. `install.sh` is
  now the from-source route only.
* The old-name migration moved into the package's post-install
  (`scripts/OPNsense/UplinkSpeedtest/legacy-migrate.sh` plus the migrator next to it), so it
  also happens when the package is installed from the repository or a release. It reads the
  old identifiers off the filesystem instead of off the installed package, and it does not
  delete the old package — pkg holds its database while post-install runs — it prints the
  `pkg delete` command, which `install.sh` then runs itself.

## 1.2.0 — 2026-10-30

### Changed
* **Renamed the plugin to `os-uplink-speedtest`.** Everything moved with it: the MVC
  namespace (`OPNsense/UplinkSpeedtest`), the configd action and cron command
  (`uplinkspeedtest`), the engine scripts, the widget and its metadata id, the page
  privilege and the data directory (`/var/db/uplink-speedtest`).

### Added
* **An upgrade path from a release installed under a different package name.** `install.sh`
  finds it, reads the old identifiers off the installed package itself, and carries over the
  settings node, the cron jobs' command (schedule and description untouched), the page
  privilege, the widget on every user's dashboard and the measurement history, then removes
  the old package. The config edits go through OPNsense's own API, so the previous
  `config.xml` stays restorable from System → Configuration → Backups.
* A real README, this changelog, a security policy, contributing notes and an issue template.

## 1.1.3 — 2026-10-30

### Fixed
* **Ookla's "nearest" server was not nearest.** `speedtest-cli` ranks a static server list
  that stopped being updated, so a box in the Netherlands was offered only French servers,
  and a current server could not be pinned at all (`No matched servers`). The server list now
  comes from Ookla's own live API, which places the client from the request, and the chosen
  entry is injected into the engine so a server only the current list knows is measurable.
  The static list stays as a fallback and the page says when it is used.
* **Servers that returned 0 bit/s with a plausible latency.** Many are listed under a vanity
  hostname their TLS certificate does not cover, and the engine swallowed the failure. The
  connection now uses the name the certificate is issued for, and a 0 bit/s result is refused
  instead of recorded.

### Added
* **iperf3 picks by location** instead of a hard-coded server: the country comes from
  Cloudflare's trace endpoint, then a built-in list of verified public servers for that region
  and its neighbours, with the last Auto pick named on the page. A busy server costs one
  candidate; an unreachable region fails with `no reachable iperf3 server for <country>`
  rather than hanging.
* **Auto / Custom as an explicit choice** for both Ookla and iperf3, so switching back to Auto
  keeps the server you typed. Empty port means 5201, empty streams means 4.
* A search box on the page for Ookla servers by city or sponsor, sanitised in the controller
  and in the engine.

## 1.1.2 — 2026-10-30

### Changed
* Removed the vendor branding from the plugin itself; only the package name carries a name now.

## 1.1.1 — 2026-10-30

### Fixed
* **Opening the page crashed on OPNsense 26.4**: an escaped apostrophe in `index.volt` raised
  a Volt `ParseError`. 26.1 tolerated it, 26.4 does not.

## 1.1.0 — 2026-10-30

### Added
* **Three providers, with Cloudflare as the new default** — Python standard library only, no
  extra package, and it reports the PoP it measured against.
* **iperf3** as a provider, with `iperf3` added as a package dependency from the OPNsense
  repository, a configurable host, port and stream count, and hard timeouts.
* An optional fixed server ID for Ookla.
* Every history record now carries its provider; the page filters by provider and the widget
  and sparkline show one provider at a time. Records written by 1.0 are read as Ookla.

### Fixed
* **Cloudflare never produced a result**: `__down` answers 429 from exactly 10,000,000 bytes
  upward for a single request, so the download now runs in 8 MB chunks.
* **Upload over-reported by about 80 %**: it counted bytes the socket accepted rather than
  bytes Cloudflare acknowledged.
* The upload overshot its own `Content-Length` by up to 256 KB; the surplus was read as the
  head of the next request on the keep-alive connection and answered HTTP 400.
* `speedtest-cli` prints a latency sentinel in the millions of milliseconds when its own probe
  fails; anything above 10 s is now replaced by the ICMP round trip measured alongside.
* Cloudflare jitter could exceed its own latency; the slowest 2 of 20 samples are now dropped.

## 1.0.0 — 2026-10-30

First release. Written from scratch for OPNsense 26.x.

* Reporting → Speedtest page: latest result, min/avg/max, chart, history table, Run now.
* Dashboard widget for the modern (≥ 24.1) dashboard, light and dark, with a sparkline.
* Ookla measurements through `py313-speedtest-cli`, installed from the OPNsense repository.
* configd actions behind `flock -n`, a cron command selectable under System → Settings → Cron,
  and a JSON history capped at the last 1000 results, written atomically.
