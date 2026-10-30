# Contributing

Issues and pull requests are welcome. This is a small plugin maintained in spare time, so
please keep changes focused.

## Reporting a bug

Open an issue with the template. It asks for the two things that are needed almost every
time: your **OPNsense version** (`opnsense-version`) and
**`/var/lib/php/tmp/PHP_errors.log`**. Add which provider you were using — Cloudflare, Ookla
and iperf3 fail in completely different ways.

For anything measurement-related, the output of these three on the firewall says more than a
description:

```sh
configctl uplinkspeedtest selftest
configctl uplinkspeedtest run
pkg info os-uplink-speedtest
```

Security problems go to [SECURITY.md](SECURITY.md), not to an issue.

## Pull requests

* Say which OPNsense version you tested on. **26.1 and 26.4 behave differently** — 26.4 is
  stricter about Volt templates, so compile every `.volt` you touched with Phalcon's Volt
  compiler, and run `php -l` over the PHP.
* Keep the engines honest: no binaries downloaded at install or run time, and no new package
  that is not in the official OPNsense repository.
* `configctl uplinkspeedtest selftest` must stay green; add a case to it for logic worth
  protecting rather than adding a test framework the firewall does not have.
* Match the surrounding style. PHP and the MVC layout follow the `opnsense/plugins`
  conventions; the Python is standard library only.
* One change per pull request, and say in the description what you measured to know it works.

## Building and installing a change

```sh
tar -czf /tmp/uplink-speedtest.tgz --exclude=.git opnsense-uplink-speedtest
scp /tmp/uplink-speedtest.tgz <user>@<firewall>:/tmp/
ssh <user>@<firewall> 'mkdir -p /tmp/ust && tar -xzf /tmp/uplink-speedtest.tgz -C /tmp/ust \
    && cd /tmp/ust/opnsense-uplink-speedtest && sudo ./install.sh'
```

`install.sh` builds a real package, so `pkg info -l os-uplink-speedtest` shows exactly what
landed and `./uninstall.sh` takes it away again. Your measurement history survives both.
