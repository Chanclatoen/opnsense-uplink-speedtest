# os-uplink-speedtest

Periodic uplink speedtest for OPNsense, with the results on the dashboard.

Everything stays on the firewall: the measurement, the history file and the UI. Nothing is
sent anywhere except the speedtest itself, and both engines that need one come from the
OPNsense repository (`py313-speedtest-cli`, `iperf3`) — no downloaded binaries.

Three providers, pick the default on the settings tab:

| Provider | Engine | Measures | Reports |
| --- | --- | --- | --- |
| **Cloudflare** (default) | Python standard library only | HTTPS against `speed.cloudflare.com`, 4 parallel streams | the PoP it was served from (`colo`, e.g. `CDG`) |
| **Ookla** | `speedtest-cli` | speedtest.net, nearest server or one you pin | server id, sponsor, city, country |
| **iperf3** | `iperf3` | raw TCP against a public iperf3 server, `-R` then forward | `host:port` |

Every result carries the provider that produced it, and the chart, the sparkline and the
widget each show one provider at a time — mixing them would compare three different things.
Results written by 1.0 have no provider field and are read as Ookla, which is what they were.

Written from scratch for OPNsense 26.x. The idea of a speedtest plugin for OPNsense comes
from [mihakralj/opnsense-speedtest](https://github.com/mihakralj/opnsense-speedtest) (last
code 2021, old-style PHP dashboard widget that 26.x no longer renders, no licence file);
none of its code, files or assets are used here.

## What you get

* **Reporting → Speedtest** — latest download, upload, latency and jitter, min/avg/max over
  the shown window, a Chart.js line chart, a history table with a provider column, a
  provider filter, **Run now** (default provider) with a dropdown to run any single
  provider, and the Ookla "nearest servers" lookup.
* **Dashboard widget** — latest four numbers of the **default** provider, its name, a
  sparkline of its last 20 tests, and the time and server of the last one; the title links
  to the Reporting page. It follows the dashboard theme, light or dark, because it uses the
  core widget base class and palette.
* **Cron job** — "Run uplink speedtest" is selectable under
  **System → Settings → Cron** and runs the default provider, so the schedule is yours to pick.
* **History** — `/var/db/uplink-speedtest/history.json`, capped at the last 1000 results,
  written atomically. Kept across a reinstall.

## Install

OPNsense ships no `git` and this repo is private, so copy the checkout over and build it
there. From a machine that has the repo:

```sh
tar -czf /tmp/uplink-speedtest.tgz --exclude=.git opnsense-uplink-speedtest
scp /tmp/uplink-speedtest.tgz <user>@<firewall>:/tmp/
ssh <user>@<firewall> 'mkdir -p /tmp/jst && tar -xzf /tmp/uplink-speedtest.tgz -C /tmp/jst \
    && cd /tmp/jst/opnsense-uplink-speedtest && sudo ./install.sh'
```

`install.sh` installs `py313-speedtest-cli` and `iperf3` if they are missing, builds the tree in `src/` into a
real `os-uplink-speedtest` package and `pkg add`s it. Because pkg owns the files,
`pkg info -l os-uplink-speedtest` lists them and uninstalling removes exactly those.

Then add the cron job (System → Settings → Cron → **+**, command "Run uplink speedtest"). For three tests a day: minutes `0`, hours `6,12,18`.

## Uninstall

On the firewall, as root:

```sh
pkg delete os-uplink-speedtest        # keeps the measurement history
rm -rf /var/db/uplink-speedtest       # and this drops the history too
```

`uninstall.sh` from the checkout does the same (`--purge` for the second line).

## Build as part of the official plugin tree

The `src/` layout and `Makefile` match `opnsense/plugins`: copy this directory to
`plugins/net/uplink-speedtest` in a plugins checkout and run `make package`.

## How it works

| Piece | Path |
| --- | --- |
| Engine | `/usr/local/opnsense/scripts/OPNsense/UplinkSpeedtest/uplink_speedtest.py` (`run [provider]`, `servers`, `selftest`) |
| Cloudflare provider | `.../UplinkSpeedtest/uplink_cloudflare.py` (standard library only) |
| configd actions | `/usr/local/opnsense/service/conf/actions.d/actions_uplinkspeedtest.conf` |
| API | `/api/uplink_speedtest/service/{run,status,history,providers,servers}`, `/api/uplink_speedtest/settings/{get,set}` |
| Page | `/ui/uplink_speedtest` |
| Widget | `/usr/local/opnsense/www/js/widgets/UplinkSpeedtest.js` + `Metadata/UplinkSpeedtest.xml` |
| History / state | `/var/db/uplink-speedtest/history.json`, `state.json` |

`configctl uplinkspeedtest selftest` runs the built-in checks on the history cap, the latency
parsers, the provider defaulting and the iperf3 server ordering.
`configctl uplinkspeedtest runwith <provider>` measures with one named provider; an unknown
name falls back to the default rather than failing, and configd passes the name as an
argument, never through a shell.

Only one test runs at a time: the configd action is wrapped in `flock -n`, so a second
trigger exits instead of competing for the uplink. **Run now** starts the test detached and
the page polls `service/status`, so a slow test can never time out a web request.

## Known limits

* **Each run moves real data.** Cloudflare moves roughly 0.7 GB per direction per run (a
  2 s ramp plus a 4 s timed window, capped at 700 MB and 25 s either way), and iperf3 about
  the same over its 6 s per direction. On a gigabit line that is seconds of traffic, but it
  is not free on a metered one — which is part of why three runs a day is plenty.
* **Cloudflare has per-request ceilings.** Measured from a real firewall: `__down` answers
  **429 from exactly 10,000,000 bytes upward** and 403 from 100 MB, so the download runs as
  many 8 MB chunks instead of a few big ones. The upload counts a chunk only once Cloudflare
  has answered for it; counting bytes the socket accepted over-reported by about 80%.
* **Cloudflare latency is an HTTPS round trip**, not ICMP — `speed.cloudflare.com` does not
  answer ping. It reads a little above the network RTT (~40 ms where ICMP to a Frankfurt
  iperf3 server reads 4 ms), but consistently so, which is what a trend needs. The slowest
  two of the 20 samples are dropped before the median and stddev, because one stalled round
  trip is otherwise enough to report more jitter than latency.
* **Ookla is CPU-bound and its latency is not always real.** `speedtest-cli` is pure Python
  and does the transfer on the firewall's CPU, so on a multi-gigabit uplink the number is the
  box's ceiling, not the line's. It also prints a sentinel in the millions of milliseconds
  when its own latency probe fails (seen: 1800000.0); the plugin replaces anything above
  10 s with the ICMP round trip it measures anyway.
* **Ookla jitter is ours, not Ookla's.** `speedtest-cli` reports no jitter, so the plugin uses
  ICMP round-trip stddev to the chosen server (`ping -c 10`); `null` when it does not answer.
* **Ookla server choice matters.** The automatic pick is nearest-by-geoIP, which can be the
  wrong country when the WAN IP geolocates badly. Pin a server ID if the auto pick wanders.
* **Public iperf3 servers are single-slot.** Each port takes one test at a time, so the
  plugin tries the configured server first and then a short built-in list, with hard
  timeouts, and reports what every candidate said if none was free.
* The history table and chart show the most recent 50 results of the selected provider; the
  file keeps 1000 across all providers.
