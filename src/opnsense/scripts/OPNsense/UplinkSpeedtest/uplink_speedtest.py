#!/usr/local/bin/python3

"""
    Copyright (c) 2026 Chanclatoen. All rights reserved.
    SPDX-License-Identifier: BSD-2-Clause (see LICENSE in the repository root).

    Measure the uplink with one of three providers and keep a capped JSON history:
      cloudflare  stdlib HTTPS against speed.cloudflare.com (default, no extra package)
      ookla       speedtest-cli, optionally pinned to one server ID
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
import xml.etree.ElementTree
from datetime import datetime, timezone

import uplink_cloudflare

CONFIG = '/conf/config.xml'
DATA_DIR = '/var/db/uplink-speedtest'
HISTORY = os.path.join(DATA_DIR, 'history.json')
STATE = os.path.join(DATA_DIR, 'state.json')
MAX_RECORDS = 1000
SPEEDTEST = '/usr/local/bin/speedtest-cli'
IPERF3 = '/usr/local/bin/iperf3'
PING = '/sbin/ping'

PROVIDERS = ('cloudflare', 'ookla', 'iperf3')
MAX_PLAUSIBLE_PING = 10000   # ms; above this the engine reported a failure, not a latency
DEFAULT_PROVIDER = 'cloudflare'

# verified reachable from this box 2026-10-30; the configured server is tried first and
# these follow, so one busy or sulking server does not cost a measurement. Clouvider
# Frankfurt offers ports 5200-5209, one test at a time each, and is the nearest of these.
IPERF3_FALLBACKS = tuple(
    [('fra.speedtest.clouvider.net', port) for port in range(5200, 5210)]
    + [('iperf.worldstream.nl', 5201), ('speedtest.init7.net', 5201)]
)
IPERF3_SECONDS = 6
IPERF3_STREAMS = 4
IPERF3_CANDIDATES = 8
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


def measure_ookla(config):
    command = [SPEEDTEST, '--json', '--secure']
    server = config.get('server', '')
    if server:
        command += ['--server', server]
    done = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if done.returncode != 0:
        message = (done.stderr or done.stdout).strip()
        raise RuntimeError(message.splitlines()[-1] if message else 'speedtest-cli failed')
    raw = json.loads(done.stdout)
    for field in ('download', 'upload', 'ping'):
        if not isinstance(raw.get(field), (int, float)):
            raise RuntimeError('speedtest-cli returned no %s value' % field)
    target = raw.get('server') or {}
    icmp_ping, icmp_jitter = measure_latency(target.get('host') or '')
    return {
        'provider': 'ookla',
        'timestamp': raw.get('timestamp'),
        'download': round(raw['download']),
        'upload': round(raw['upload']),
        'ping': plausible_ping(raw['ping'], icmp_ping),
        'jitter': icmp_jitter,
        'server_id': target.get('id'),
        'server_name': target.get('name'),
        'server_sponsor': target.get('sponsor'),
        'server_country': target.get('country'),
        'bytes_received': raw.get('bytes_received'),
        'bytes_sent': raw.get('bytes_sent'),
    }


def iperf3_candidates(config):
    """ configured server first, then the verified fallbacks, no duplicates
    """
    host = config.get('iperf3_server', '') or IPERF3_FALLBACKS[0][0]
    try:
        port = int(config.get('iperf3_port', '') or IPERF3_FALLBACKS[0][1])
    except ValueError:
        port = IPERF3_FALLBACKS[0][1]
    ordered = [(host, port)]
    ordered += [pair for pair in IPERF3_FALLBACKS if pair != (host, port)]
    return ordered[:IPERF3_CANDIDATES]


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

    problems = []
    deadline = time.monotonic() + IPERF3_DEADLINE
    for host, port in iperf3_candidates(config):
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
        return {
            'provider': 'iperf3',
            'download': download,
            'upload': upload,
            'ping': ping,
            'jitter': jitter,
            'server_id': None,
            'server_name': '%s:%d' % (host, port),
            'server_sponsor': 'iperf3',
            'server_country': None,
            'bytes_received': received,
            'bytes_sent': sent,
        }
    raise RuntimeError('no iperf3 server available: %s' % '; '.join(problems)[:250])


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


def servers():
    """ Ookla server list, for pinning one server on the settings form
    """
    import speedtest
    client = speedtest.Speedtest(secure=True)
    return [{
        'id': entry.get('id'),
        'sponsor': entry.get('sponsor'),
        'name': entry.get('name'),
        'country': entry.get('country'),
        'distance': round(entry.get('d', 0), 1),
    } for entry in client.get_closest_servers(limit=20)]


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

    # the configured server leads and is never offered twice
    first = iperf3_candidates({'iperf3_server': 'example.net', 'iperf3_port': '5202'})
    assert first[0] == ('example.net', 5202)
    assert len(first) == len(set(first)) == IPERF3_CANDIDATES
    default_order = iperf3_candidates({})
    assert default_order[0] == IPERF3_FALLBACKS[0]
    assert len(default_order) == len(set(default_order))
    assert iperf3_candidates({'iperf3_port': 'abc'})[0] == IPERF3_FALLBACKS[0]

    uplink_cloudflare.selftest()
    return {'selftest': 'ok'}


if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    argument = sys.argv[2] if len(sys.argv) > 2 else ''
    actions = {'run': lambda: run(argument), 'servers': servers, 'selftest': selftest}
    if action not in actions:
        print('usage: uplink_speedtest.py run [cloudflare|ookla|iperf3]|servers|selftest',
              file=sys.stderr)
        sys.exit(1)
    try:
        print(json.dumps(actions[action]()))
    except Exception as failure:
        # exit 0 with the message on stdout: the API shows it, configd logs stderr
        print(str(failure)[:300], file=sys.stderr)
        print(json.dumps({'error': str(failure)[:300]}))
