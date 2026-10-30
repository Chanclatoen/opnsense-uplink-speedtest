# os-uplink-speedtest

Periodic uplink speedtest for OPNsense, with the results on the dashboard.

Everything stays on the firewall: the measurement, the history file and the UI. Nothing
is sent anywhere except the speedtest itself, and the engine is the
`py313-speedtest-cli` package from the OPNsense repository — no downloaded binaries.

Written from scratch for OPNsense 26.x. The idea of a speedtest plugin for OPNsense comes
from [mihakralj/opnsense-speedtest](https://github.com/mihakralj/opnsense-speedtest) (last
code 2021, old-style PHP dashboard widget that 26.x no longer renders, no licence file);
none of its code, files or assets are used here.

## What you get

* **Reporting → Speedtest** — latest download, upload, latency and jitter, min/avg/max over
  the shown window, a Chart.js line chart, a history table, a **Run now** button, and the
  server choice with a "nearest servers" lookup.
* **Dashboard widget** — latest four numbers, a sparkline of the last 20 tests, the time of
  the last test and the server it used; the title links to the Reporting page. It follows the
  dashboard theme, light or dark, because it uses the core widget base class and palette.
* **Cron job** — "Run uplink speedtest (Uplink)" is selectable under
  **System → Settings → Cron**, so the schedule is yours to pick.
* **History** — `/var/db/uplink-speedtest/history.json`, capped at the last 1000 results,
  written atomically. Kept across a reinstall.

## Install

On the firewall, as root:

```sh
git clone https://github.com/Chanclatoen/opnsense-uplink-speedtest.git
cd opnsense-uplink-speedtest
./install.sh
```

`install.sh` installs `py313-speedtest-cli` if it is missing, builds the tree in `src/` into a
real `os-uplink-speedtest` package and `pkg add`s it. Because pkg owns the files,
`pkg info -l os-uplink-speedtest` lists them and uninstalling removes exactly those.

Then add the cron job (System → Settings → Cron → **+**, command "Run uplink speedtest
(Uplink)"). For three tests a day: minutes `0`, hours `6,12,18`.

## Uninstall

```sh
./uninstall.sh            # keeps the measurement history
./uninstall.sh --purge    # deletes /var/db/uplink-speedtest too
```

Plain `pkg delete os-uplink-speedtest` does the same as the first form.

## Build as part of the official plugin tree

The `src/` layout and `Makefile` match `opnsense/plugins`: copy this directory to
`plugins/net/uplink-speedtest` in a plugins checkout and run `make package`.

## How it works

| Piece | Path |
| --- | --- |
| Engine | `/usr/local/opnsense/scripts/OPNsense/UplinkSpeedtest/uplink_speedtest.py` (`run`, `servers`, `selftest`) |
| configd actions | `/usr/local/opnsense/service/conf/actions.d/actions_uplinkspeedtest.conf` |
| API | `/api/uplink_speedtest/service/{run,status,history,servers}`, `/api/uplink_speedtest/settings/{get,set}` |
| Page | `/ui/uplink_speedtest` |
| Widget | `/usr/local/opnsense/www/js/widgets/UplinkSpeedtest.js` + `Metadata/UplinkSpeedtest.xml` |
| History / state | `/var/db/uplink-speedtest/history.json`, `state.json` |

`configctl uplinkspeedtest selftest` runs the built-in checks on the history cap and the
jitter parser.

Only one test runs at a time: the configd action is wrapped in `flock -n`, so a second
trigger exits instead of competing for the uplink. **Run now** starts the test detached and
the page polls `service/status`, so a slow test can never time out a web request.

## Known limits

* **Fast links are CPU-bound.** `speedtest-cli` is pure Python and does the transfer on the
  firewall's CPU. On a multi-gigabit uplink the number you get is the box's ceiling, not the
  line's, and the test is a real load on the firewall while it runs — which is also why
  scheduling it three times a day is plenty.
* **Jitter is ours, not Ookla's.** `speedtest-cli` reports no jitter, so the plugin measures
  ICMP round-trip stddev to the chosen test server (`ping -c 10`). It is a jitter figure for
  that path, not the value an Ookla client would print, and it is `null` when the server does
  not answer ICMP.
* **Server choice matters.** The automatic pick is Ookla's nearest-by-geoIP, which can be the
  wrong continent when the WAN IP geolocates badly. Set a server ID if the auto pick looks odd.
* The history table and chart show the most recent 50 results; the file keeps 1000.
