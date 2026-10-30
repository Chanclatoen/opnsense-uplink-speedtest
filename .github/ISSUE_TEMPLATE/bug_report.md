---
name: Bug report
about: Something in the plugin does not work
title: ''
labels: bug
assignees: ''
---

## What happens

<!-- and what you expected instead -->

## Versions

* OPNsense version (`opnsense-version`):
* Plugin version (`pkg info os-uplink-speedtest`):
* Provider in use: Cloudflare / Ookla / iperf3
* Server choice: Auto / Custom (which one?)

## PHP error log

<!-- /var/lib/php/tmp/PHP_errors.log on the firewall. Paste the lines from around the time it
     went wrong, or "empty" if it is. This is where a page crash lands. -->

```
```

## What the engine says

<!-- On the firewall, as root. Paste the output. -->

```
configctl uplinkspeedtest selftest
configctl uplinkspeedtest run
```

```
```

## Anything else

<!-- Screenshot of the page, the relevant history rows, how your uplink is connected -->
