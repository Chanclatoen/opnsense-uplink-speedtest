# Security policy

## Supported versions

The latest release is the supported one. There is no long-term branch: fixes land in a new
version.

## Reporting a vulnerability

Please report privately first — use GitHub's **Report a vulnerability** button under the
[Security tab](https://github.com/Chanclatoen/opnsense-uplink-speedtest/security/advisories),
which opens a private advisory. If that is not available to you, open a normal issue saying
only that you have a security report and asking for a private channel; do not put the details
in it.

Please include:

* what an attacker can do, and what access they need to start (an unauthenticated web
  request, a logged-in non-admin user, local shell on the firewall, …);
* the OPNsense version and the plugin version;
* the smallest reproduction you have.

You will get an acknowledgement within a week. This is a spare-time project maintained by one
person, so a fix may take longer than that; you will be told what is happening either way, and
credited in the changelog unless you would rather not be.

## Scope

Things worth reporting: command or SQL injection, path traversal, anything that lets a
non-admin user reach the plugin's API or run its configd actions, anything that writes outside
`/var/db/uplink-speedtest`, and any secret the plugin writes to a log or to `config.xml`.

Out of scope: a speedtest server returning wrong numbers, denial of service by running tests
constantly (the configd action is already serialised with `flock`), and the bandwidth a
measurement uses by design — that one is documented in the README.
