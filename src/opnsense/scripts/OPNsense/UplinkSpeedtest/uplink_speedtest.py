#!/usr/local/bin/python3

"""
    Copyright (c) 2026 Chanclatoen. All rights reserved.
    SPDX-License-Identifier: BSD-2-Clause (see LICENSE in the repository root).

    Measure the uplink with one of three providers and keep a capped JSON history:
      cloudflare  stdlib HTTPS against speed.cloudflare.com (default, no extra package)
      ookla       the speedtest-cli engine, aimed at a server from Ookla's own server API
      iperf3      iperf3 against a public server, download (-R) and upload

    Not named speedtest.py on purpose: the script directory is first on sys.path, so
    that name would shadow the speedtest module this imports for the server list.
"""

import json
import os
import subprocess
import sys
import time
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree
from datetime import datetime, timezone

import uplink_cloudflare

CONFIG = '/conf/config.xml'
DATA_DIR = '/var/db/uplink-speedtest'
HISTORY = os.path.join(DATA_DIR, 'history.json')
STATE = os.path.join(DATA_DIR, 'state.json')
MAX_RECORDS = 1000
IPERF3 = '/usr/local/bin/iperf3'
PING = '/sbin/ping'

PROVIDERS = ('cloudflare', 'ookla', 'iperf3')
MAX_PLAUSIBLE_PING = 10000   # ms; above this the engine reported a failure, not a latency
DEFAULT_PROVIDER = 'cloudflare'
AUTO = 'auto'

# speedtest-cli carries a static server list that stopped being updated, and it geolocates
# this box by its WAN IP (which is wrong by thousands of km), so its "closest" server is
# neither closest nor always alive. Ookla's own site uses this endpoint instead: it places
# the client from the request itself and returns servers that exist today. It answers 403
# without a User-Agent and silently ignores a limit above 20.
OOKLA_API = 'https://www.speedtest.net/api/js/servers'
OOKLA_API_LIMIT = 20
OOKLA_API_UA = 'Mozilla/5.0 (compatible; opnsense-speedtest)'
OOKLA_API_TIMEOUT = 20
OOKLA_AUTO_CANDIDATES = 4   # inject this many nearest servers; the engine takes the fastest
SERVER_CACHE = os.path.join(DATA_DIR, 'ookla_servers.json')
SERVER_CACHE_MAX = 300
AUTO_PICK = os.path.join(DATA_DIR, 'auto.json')

# Public iperf3 servers, every one of them reachable from both a German and a Dutch uplink
# on 2026-10-30. Deliberately not a default in the settings: an empty server field means
# "pick by location", so the same package is sensible wherever the firewall stands.
IPERF3_REGIONS = {
    'NL': (('ams.speedtest.clouvider.net', tuple(range(5200, 5210))),
           ('iperf-ams-nl.eranium.net', (5201,)),
           ('iperf.worldstream.nl', (5201,))),
    'DE': (('fra.speedtest.clouvider.net', tuple(range(5200, 5210))),),
    'FR': (('ping.online.net', tuple(range(5200, 5210))),
           ('iperf3.moji.fr', (5200, 5201))),
    'GB': (('lon.speedtest.clouvider.net', tuple(range(5200, 5210))),),
    'CH': (('speedtest.init7.net', (5201,)),),
    'US': (('nyc.speedtest.clouvider.net', tuple(range(5200, 5210))),
           ('dal.speedtest.clouvider.net', tuple(range(5200, 5210))),
           ('la.speedtest.clouvider.net', tuple(range(5200, 5210)))),
}

# which regions to try, in order, for the country the box reports from
IPERF3_NEIGHBOURS = {
    'NL': ('NL', 'DE', 'GB'), 'BE': ('NL', 'FR', 'DE'), 'LU': ('FR', 'DE', 'NL'),
    'DE': ('DE', 'NL', 'CH'), 'AT': ('DE', 'CH', 'NL'), 'CZ': ('DE', 'NL', 'GB'),
    'PL': ('DE', 'NL', 'GB'), 'DK': ('DE', 'NL', 'GB'), 'SE': ('DE', 'NL', 'GB'),
    'NO': ('DE', 'NL', 'GB'), 'FI': ('DE', 'NL', 'GB'), 'CH': ('CH', 'DE', 'FR'),
    'FR': ('FR', 'NL', 'GB'), 'ES': ('FR', 'GB', 'NL'), 'PT': ('FR', 'GB', 'NL'),
    'IT': ('CH', 'FR', 'DE'), 'GB': ('GB', 'NL', 'FR'), 'IE': ('GB', 'NL', 'FR'),
    'US': ('US', 'GB', 'NL'), 'CA': ('US', 'GB', 'NL'),
}
IPERF3_DEFAULT_REGIONS = ('NL', 'DE', 'GB', 'FR', 'CH')

IPERF3_SECONDS = 6
IPERF3_STREAMS = 4
IPERF3_DEFAULT_PORT = 5201
IPERF3_CANDIDATES = 10
IPERF3_PORTS_PER_HOST = 4   # so one dead host cannot use up the whole candidate list
IPERF3_DEADLINE = 180   # seconds spent hunting for a free server before giving up
IPERF3_PAUSE = 2        # let the server release its one test slot between the two directions


class Busy(Exception):
    """ this iperf3 server cannot be used right now; try the next one """


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'


def settings():
    """ the general settings node from config.xml; empty dict when never saved
    """
    try:
        node = xml.etree.ElementTree.parse(CONFIG).getroot().find(
            './OPNsense/UplinkSpeedtest/general'
        )
    except (xml.etree.ElementTree.ParseError, OSError):
        return {}
    if node is None:
        return {}
    return {child.tag: (child.text or '').strip() for child in node}


def default_provider(config=None):
    chosen = (config if config is not None else settings()).get('provider', '')
    return chosen if chosen in PROVIDERS else DEFAULT_PROVIDER


def read_json(filename, fallback):
    try:
        with open(filename) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return fallback
    return data if isinstance(data, type(fallback)) else fallback


def write_json(filename, data):
    """ atomic replace, so a reader never sees a half-written history
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    handle, path = tempfile.mkstemp(dir=DATA_DIR)
    try:
        with os.fdopen(handle, 'w') as stream:
            json.dump(data, stream)
        os.chmod(path, 0o644)
        os.replace(path, filename)
    except BaseException:
        if os.path.exists(path):
            os.unlink(path)
        raise


def parse_latency(ping_output):
    """ the min/avg/max/stddev summary line -> (avg ms, stddev ms), (None, None) without it
    """
    for line in ping_output.splitlines():
        if 'stddev' in line:
            fields = line.rsplit('=', 1)[-1].split('/')
            if len(fields) == 4:
                try:
                    return round(float(fields[1]), 3), round(float(fields[3].split()[0]), 3)
                except ValueError:
                    return None, None
    return None, None


def measure_latency(host):
    """ ICMP round trip to the test server; neither speedtest-cli nor iperf3 (TCP) report jitter
    """
    host = host.split(':')[0]
    if not host:
        return None, None
    try:
        done = subprocess.run([PING, '-q', '-c', '10', '-i', '0.2', '-t', '10', host],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None, None
    return parse_latency(done.stdout)


def plausible_ping(reported, fallback):
    """ speedtest-cli prints a sentinel in the millions when its own latency probe failed
        (seen: 1800000.0 against a Lille server), and a chart cannot survive that in a
        series. Fall back to the ICMP round trip we measure anyway, or to nothing.
    """
    if isinstance(reported, (int, float)) and 0 < reported < MAX_PLAUSIBLE_PING:
        return round(reported, 3)
    return fallback


def api_search_text(text):
    """ keep a free-text search harmless: letters, digits and the few separators a city or
        sponsor name needs. The UI and configd already pass it as one argument, never a shell
        word, so this only guards what ends up in the query string.
    """
    cleaned = ''.join(c for c in (text or '') if c.isalnum() or c in " .,'&-_")
    return cleaned.strip()[:60]


def ookla_api(search='', limit=OOKLA_API_LIMIT):
    """ Ookla's live server list, nearest first by the geo it derives from the request itself
    """
    query = {'engine': 'js', 'limit': str(max(1, min(limit, OOKLA_API_LIMIT)))}
    search = api_search_text(search)
    if search:
        query['search'] = search
    url = '%s?%s' % (OOKLA_API, urllib.parse.urlencode(query))
    request = urllib.request.Request(url, headers={'User-Agent': OOKLA_API_UA,
                                                   'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=OOKLA_API_TIMEOUT) as response:
            rows = json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as failure:
        raise RuntimeError('Ookla server API unreachable: %s' % failure)
    if not isinstance(rows, list):
        raise RuntimeError('Ookla server API returned no list')
    return [row for row in rows if isinstance(row, dict) and row.get('id') and row.get('url')]


def api_server(entry):
    """ one API entry as the dict the speedtest-cli engine expects for a server, so a server
        that only the modern list knows can still be measured against.

        Over TLS the entry's `host` is used, not the host in its `url`: many servers are
        listed under a vanity name whose certificate only covers the operator's own domain,
        and a name mismatch makes every transfer fail silently at 0 bit/s (seen on Glasnet
        Den Haag, 26476). `host` is the ooklaserver.net name the certificate is issued for.
    """
    url = str(entry.get('url') or '')
    host = str(entry.get('host') or '')
    if str(entry.get('https_functional') or '0') == '1' and host:
        url = 'https://%s%s' % (host, urllib.parse.urlparse(url).path)
    try:
        distance = float(entry.get('distance') or 0)
    except (TypeError, ValueError):
        distance = 0.0
    return {
        'url': url,
        'lat': entry.get('lat'),
        'lon': entry.get('lon'),
        'name': entry.get('name'),
        'country': entry.get('country'),
        'cc': entry.get('cc'),
        'sponsor': entry.get('sponsor'),
        'id': str(entry.get('id')),
        'host': entry.get('host'),
        'd': distance,
    }


def remember_servers(rows):
    """ cache what the API showed, keyed by ID: a pinned server that is not in today's
        nearest list (another city, another country) still has to be resolvable at run time
    """
    cache = read_json(SERVER_CACHE, {})
    for entry in rows:
        cache[str(entry.get('id'))] = entry
    if len(cache) > SERVER_CACHE_MAX:
        cache = dict(list(cache.items())[-SERVER_CACHE_MAX:])
    try:
        write_json(SERVER_CACHE, cache)
    except OSError:
        pass


def remember_auto_pick(host, port, country):
    """ what Auto settled on last, so the settings page can name it instead of leaving the
        user guessing which server an empty field means
    """
    try:
        write_json(AUTO_PICK, {'iperf3': {'server': '%s:%d' % (host, port),
                                          'country': country, 'when': now()}})
    except OSError:
        pass


def ookla_targets(config):
    """ (servers to inject, how they were chosen) for this run.

        custom: exactly the pinned ID, looked up in the live list and then in the cache.
        auto:   the nearest few from the API, so the engine can skip one that does not answer.
        Returns an empty list when the API is unreachable; the caller then lets speedtest-cli
        fall back to its own list.
    """
    pinned = ookla_pinned(config)
    try:
        rows = ookla_api()
    except RuntimeError:
        rows = []
    if rows:
        remember_servers(rows)
    if not pinned:
        return [api_server(entry) for entry in rows[:OOKLA_AUTO_CANDIDATES]], 'auto'
    for entry in rows:
        if str(entry.get('id')) == pinned:
            return [api_server(entry)], 'pinned'
    cached = read_json(SERVER_CACHE, {}).get(pinned)
    if isinstance(cached, dict):
        return [api_server(cached)], 'pinned (cached)'
    return [], 'pinned'


def ookla_pinned(config):
    """ the server ID to measure against, '' for automatic. A pin only counts when the mode
        says custom, so switching back to Auto keeps the ID for later instead of losing it.
    """
    if (config.get('server_mode') or AUTO) != 'custom':
        return ''
    return (config.get('server') or '').strip()


def measure_ookla(config):
    try:
        import speedtest
    except ImportError as failure:
        raise RuntimeError('speedtest-cli is not installed: %s' % failure)
    try:
        client = speedtest.Speedtest(secure=True)
    except Exception as failure:
        raise RuntimeError('cannot reach speedtest.net: %s' % failure)

    targets, how = ookla_targets(config)
    pinned = ookla_pinned(config)
    try:
        if targets:
            client.get_best_server(targets)
        elif pinned:
            # the API does not know this ID; speedtest-cli's own list is the last resort
            client.get_servers([int(pinned)])
            client.get_best_server()
        else:
            client.get_best_server()
    except ValueError:
        raise RuntimeError('server ID %r is not a number' % pinned)
    except Exception as failure:
        if pinned and not targets:
            # neither the live list nor the cache knows it, and the static list is tiny:
            # the page is the only thing that can tell us where this server stands
            raise RuntimeError('Ookla server %s is not among the nearest and has not been '
                               'listed on this page yet: search for it under Settings and '
                               'press Use, which records where it is' % pinned)
        raise RuntimeError('no usable Ookla server (%s): %s'
                           % (how, failure or type(failure).__name__))

    client.download()
    client.upload(pre_allocate=False)
    raw = client.results.dict()
    for field in ('download', 'upload'):
        if not isinstance(raw.get(field), (int, float)):
            raise RuntimeError('the Ookla engine returned no %s value' % field)
        # the engine swallows a failed transfer and reports 0 bit/s; that is a broken server,
        # not a measurement, and it must never reach the history
        if raw[field] <= 0:
            raise RuntimeError('server %s moved no data (%s came back as 0); it is not usable'
                               % ((raw.get('server') or {}).get('id', '?'), field))
    target = raw.get('server') or {}
    icmp_ping, icmp_jitter = measure_latency(target.get('host') or '')
    return {
        'provider': 'ookla',
        'timestamp': raw.get('timestamp'),
        'download': round(raw['download']),
        'upload': round(raw['upload']),
        'ping': plausible_ping(raw.get('ping'), icmp_ping),
        'jitter': icmp_jitter,
        'server_id': target.get('id'),
        'server_name': target.get('name'),
        'server_sponsor': target.get('sponsor'),
        'server_country': target.get('country'),
        'server_mode': 'custom' if pinned else AUTO,
        'bytes_received': raw.get('bytes_received'),
        'bytes_sent': raw.get('bytes_sent'),
    }


def iperf3_regions(country):
    """ the regions to draw candidates from, nearest first, for a two-letter country code
    """
    return IPERF3_NEIGHBOURS.get((country or '').upper(), IPERF3_DEFAULT_REGIONS)


def iperf3_region_candidates(country):
    """ host:port pairs for this country's regions. Each public server runs one test at a
        time, so a host with a port range contributes several entries - but only a few, so
        one host that is down cannot use up the whole list before the next region is tried.
    """
    pairs = []
    for region in iperf3_regions(country):
        for host, ports in IPERF3_REGIONS.get(region, ()):
            pairs += [(host, port) for port in ports[:IPERF3_PORTS_PER_HOST]]
    return pairs[:IPERF3_CANDIDATES]


def iperf3_country():
    """ where this box actually is, from Cloudflare's own view of the connection. Only used
        to order the candidate list, so a failure costs nothing but the ordering.
    """
    try:
        return (uplink_cloudflare.trace()[1] or '').upper()
    except Exception:
        return ''


def iperf3_candidates(config):
    """ (candidates, mode, country): one configured server when the settings name one,
        otherwise the verified public servers for the region the box sits in
    """
    host = (config.get('iperf3_server') or '').strip()
    if (config.get('iperf3_mode') or AUTO) == 'custom' and host:
        try:
            port = int((config.get('iperf3_port') or '').strip() or IPERF3_DEFAULT_PORT)
        except ValueError:
            port = IPERF3_DEFAULT_PORT
        return [(host, port)], 'custom', ''
    country = iperf3_country()
    return iperf3_region_candidates(country), AUTO, country


def iperf3_once(host, port, streams, reverse):
    """ one direction; every failure the next server could fix is a Busy
    """
    command = [IPERF3, '-c', host, '-p', str(port), '-t', str(IPERF3_SECONDS),
               '-P', str(streams), '-J', '--connect-timeout', '5000']
    if reverse:
        command.append('-R')
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=IPERF3_SECONDS + 40)
    except subprocess.TimeoutExpired:
        raise Busy('no answer within %ds' % (IPERF3_SECONDS + 40))
    except OSError as failure:
        raise RuntimeError('cannot run iperf3: %s' % failure)
    try:
        raw = json.loads(done.stdout)
    except ValueError:
        raise Busy((done.stderr or done.stdout or 'no JSON from iperf3').strip()[:120])
    if raw.get('error'):
        raise Busy(str(raw['error'])[:120])
    end = raw.get('end') or {}
    totals = end.get('sum_received') or end.get('sum_sent')
    if not isinstance(totals, dict) or not isinstance(totals.get('bits_per_second'), (int, float)):
        raise Busy('iperf3 reported no throughput')
    return round(totals['bits_per_second']), round(totals.get('bytes') or 0)


def measure_iperf3(config):
    try:
        streams = int(config.get('iperf3_streams', '') or IPERF3_STREAMS)
    except ValueError:
        streams = IPERF3_STREAMS
    streams = max(1, min(streams, 16))

    candidates, mode, country = iperf3_candidates(config)
    problems = []
    deadline = time.monotonic() + IPERF3_DEADLINE
    for host, port in candidates:
        if time.monotonic() > deadline:
            problems.append('gave up after %ds' % IPERF3_DEADLINE)
            break
        try:
            download, received = iperf3_once(host, port, streams, True)
            time.sleep(IPERF3_PAUSE)
            upload, sent = iperf3_once(host, port, streams, False)
        except Busy as busy:
            problems.append('%s:%d %s' % (host, port, busy))
            continue
        ping, jitter = measure_latency(host)
        if mode == AUTO:
            remember_auto_pick(host, port, country)
        return {
            'provider': 'iperf3',
            'download': download,
            'upload': upload,
            'ping': ping,
            'jitter': jitter,
            'server_id': None,
            'server_name': '%s:%d' % (host, port),
            'server_sponsor': 'iperf3',
            'server_country': country or None,
            'server_mode': mode,
            'bytes_received': received,
            'bytes_sent': sent,
        }
    if mode == AUTO and not candidates:
        raise RuntimeError('no reachable iperf3 server for %s: no server listed for that '
                           'region' % (country or 'an unknown location'))
    if mode == AUTO:
        raise RuntimeError('no reachable iperf3 server for %s: %s'
                           % (country or 'an unknown location', '; '.join(problems)[:250]))
    raise RuntimeError('iperf3 server not usable: %s' % '; '.join(problems)[:250])


ENGINES = {
    'cloudflare': lambda config: uplink_cloudflare.measure(),
    'ookla': measure_ookla,
    'iperf3': measure_iperf3,
}


def measure(provider, config):
    record = ENGINES[provider](config)
    record.setdefault('timestamp', now())
    if not record['timestamp']:
        record['timestamp'] = now()
    return record


def trim(records):
    return records[-MAX_RECORDS:]


def run(provider=''):
    config = settings()
    if provider not in PROVIDERS:
        provider = default_provider(config)
    write_json(STATE, {'running': True, 'started': now(), 'finished': None,
                       'status': 'running', 'message': '', 'provider': provider})
    try:
        record = measure(provider, config)
    except BaseException as failure:
        write_json(STATE, {'running': False, 'started': None, 'finished': now(),
                           'status': 'failed', 'message': str(failure)[:300],
                           'provider': provider})
        raise
    write_json(HISTORY, trim(read_json(HISTORY, []) + [record]))
    write_json(STATE, {'running': False, 'started': None, 'finished': record['timestamp'],
                       'status': 'ok', 'message': '', 'provider': provider})
    return record


def server_row(entry, source):
    return {
        'id': str(entry.get('id')),
        'sponsor': entry.get('sponsor'),
        'name': entry.get('name'),
        'country': entry.get('country'),
        'distance': round(float(entry.get('distance', entry.get('d', 0)) or 0), 1),
        'source': source,
    }


def legacy_servers():
    """ speedtest-cli's own static list, only used when the API cannot be reached. Its
        distances come from the WAN IP's geolocation, which is why it is the fallback.
    """
    import speedtest
    client = speedtest.Speedtest(secure=True)
    return [server_row(entry, 'speedtest-cli')
            for entry in client.get_closest_servers(limit=OOKLA_API_LIMIT)]


def servers(search=''):
    """ Ookla server list for the settings page: nearest by Ookla's own geo, or the servers
        matching a city or sponsor when a search text is given
    """
    try:
        rows = ookla_api(search)
    except RuntimeError as failure:
        if api_search_text(search):
            raise
        return legacy_servers()
    remember_servers(rows)
    return [server_row(entry, 'api') for entry in rows]


def selftest():
    assert len(trim(list(range(MAX_RECORDS + 50)))) == MAX_RECORDS
    assert trim(list(range(MAX_RECORDS + 50)))[-1] == MAX_RECORDS + 49
    assert trim([1, 2, 3]) == [1, 2, 3]
    assert parse_latency(
        'round-trip min/avg/max/stddev = 17.263/20.222/28.379/3.756 ms') == (20.222, 3.756)
    assert parse_latency('10 packets transmitted, 0 packets received, 100.0% loss') == (None, None)
    assert parse_latency('round-trip min/avg/max/stddev = a/b/c/d ms') == (None, None)
    assert read_json('/nonexistent/uplink-speedtest', []) == []

    assert plausible_ping(23.5, None) == 23.5
    assert plausible_ping(1800000.0, 4.2) == 4.2      # the sentinel, replaced by our ICMP
    assert plausible_ping(1800000.0, None) is None    # ... and dropped when ICMP had nothing
    assert plausible_ping(0, 4.2) == 4.2
    assert plausible_ping(None, 4.2) == 4.2

    assert default_provider({}) == DEFAULT_PROVIDER
    assert default_provider({'provider': 'iperf3'}) == 'iperf3'
    assert default_provider({'provider': 'nonsense'}) == DEFAULT_PROVIDER

    # Custom means exactly the configured server, and only when the mode says so
    custom = {'iperf3_mode': 'custom', 'iperf3_server': 'example.net', 'iperf3_port': '5202'}
    assert iperf3_candidates(custom) == ([('example.net', 5202)], 'custom', '')
    assert iperf3_candidates(dict(custom, iperf3_port='')) == \
        ([('example.net', IPERF3_DEFAULT_PORT)], 'custom', '')
    assert iperf3_candidates(dict(custom, iperf3_port='abc')) == \
        ([('example.net', IPERF3_DEFAULT_PORT)], 'custom', '')
    # a host left over from an earlier Custom setting is ignored while the mode is Auto
    assert iperf3_candidates({'iperf3_server': 'example.net'})[1] == AUTO

    # Auto: nearest region first, every pair unique, every host in the verified list
    known = {host for region in IPERF3_REGIONS.values() for host, _ in region}
    for country, first in (('NL', 'NL'), ('BE', 'NL'), ('DE', 'DE'), ('FR', 'FR'),
                           ('GB', 'GB'), ('US', 'US'), ('ZZ', IPERF3_DEFAULT_REGIONS[0])):
        pairs = iperf3_region_candidates(country)
        assert pairs, country
        assert len(pairs) == len(set(pairs)) <= IPERF3_CANDIDATES, country
        assert all(host in known for host, _ in pairs), country
        assert pairs[0][0] == IPERF3_REGIONS[first][0][0], country
    assert iperf3_regions('nl') == iperf3_regions('NL')   # the form may save either case
    assert all(region in IPERF3_REGIONS
               for regions in list(IPERF3_NEIGHBOURS.values()) + [IPERF3_DEFAULT_REGIONS]
               for region in regions)

    # a pin only counts in Custom mode, so Auto does not throw the saved ID away
    assert ookla_pinned({'server': '1234'}) == ''
    assert ookla_pinned({'server_mode': 'auto', 'server': '1234'}) == ''
    assert ookla_pinned({'server_mode': 'custom', 'server': '1234'}) == '1234'
    assert ookla_pinned({'server_mode': 'custom'}) == ''

    # the free-text search cannot carry anything but a name into the query string
    assert api_search_text(" Den Haag ") == 'Den Haag'
    assert api_search_text("KPN B.V. & Co-op_1") == 'KPN B.V. & Co-op_1'
    assert api_search_text('a?b=c#d<e>f"g/h\\i') == 'abcdefghi'
    assert api_search_text('x' * 200) == 'x' * 60
    assert api_search_text(None) == ''

    # an API entry becomes a server the engine can use, https only where it is supported
    entry = {'id': 69740, 'url': 'http://a.example:8080/speedtest/upload.php',
             'host': 'a.example:8080', 'lat': '52.0', 'lon': '4.0', 'name': 'Naaldwijk',
             'country': 'Netherlands', 'cc': 'NL', 'sponsor': 'X', 'distance': 3,
             'https_functional': 1}
    # over TLS the certificate name wins over the vanity name in the url
    assert api_server(entry)['url'] == 'https://a.example:8080/speedtest/upload.php'
    assert api_server(dict(entry, host='real.ooklaserver.net:8080'))['url'] == \
        'https://real.ooklaserver.net:8080/speedtest/upload.php'
    assert api_server(dict(entry, host=''))['url'] == entry['url']
    assert api_server(entry)['id'] == '69740'
    assert api_server(entry)['d'] == 3.0
    assert api_server(dict(entry, https_functional=0))['url'].startswith('http://')
    assert api_server(dict(entry, distance=None))['d'] == 0.0
    assert server_row(entry, 'api')['distance'] == 3.0
    assert server_row({'id': 1, 'd': 12.34}, 'speedtest-cli')['distance'] == 12.3

    uplink_cloudflare.selftest()
    return {'selftest': 'ok'}


if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    argument = sys.argv[2] if len(sys.argv) > 2 else ''
    actions = {'run': lambda: run(argument), 'servers': lambda: servers(argument),
               'selftest': selftest}
    if action not in actions:
        print('usage: uplink_speedtest.py run [cloudflare|ookla|iperf3]'
              '|servers [search text]|selftest', file=sys.stderr)
        sys.exit(1)
    try:
        print(json.dumps(actions[action]()))
    except Exception as failure:
        # exit 0 with the message on stdout: the API shows it, configd logs stderr
        print(str(failure)[:300], file=sys.stderr)
        print(json.dumps({'error': str(failure)[:300]}))
