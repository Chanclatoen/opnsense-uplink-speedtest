#!/usr/local/bin/python3

"""
    Copyright (c) 2026 Uplink IT. All rights reserved.
    SPDX-License-Identifier: BSD-2-Clause (see LICENSE in the repository root).

    Measure the uplink with speedtest-cli and keep a capped JSON history.

    Not named speedtest.py on purpose: the script directory is first on sys.path, so
    that name would shadow the speedtest module this imports for the server list.
"""

import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree
from datetime import datetime, timezone

CONFIG = '/conf/config.xml'
DATA_DIR = '/var/db/uplink-speedtest'
HISTORY = os.path.join(DATA_DIR, 'history.json')
STATE = os.path.join(DATA_DIR, 'state.json')
MAX_RECORDS = 1000
SPEEDTEST = '/usr/local/bin/speedtest-cli'
PING = '/sbin/ping'


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'


def configured_server():
    """ server ID from config.xml; empty means let speedtest-cli pick the nearest one
    """
    try:
        node = xml.etree.ElementTree.parse(CONFIG).getroot().find(
            './OPNsense/UplinkSpeedtest/general/server'
        )
    except (xml.etree.ElementTree.ParseError, OSError):
        return ''
    if node is None or node.text is None:
        return ''
    return node.text.strip()


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


def parse_jitter(ping_output):
    """ pull stddev (ms) out of the ping summary line, None when it is not there
    """
    for line in ping_output.splitlines():
        if 'stddev' in line:
            fields = line.rsplit('=', 1)[-1].split('/')
            if len(fields) == 4:
                try:
                    return round(float(fields[3].split()[0]), 3)
                except ValueError:
                    return None
    return None


def measure_jitter(host):
    """ speedtest-cli reports no jitter, so use ICMP round-trip stddev to the test server
    """
    host = host.split(':')[0]
    if not host:
        return None
    try:
        done = subprocess.run([PING, '-q', '-c', '10', '-i', '0.2', '-t', '10', host],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_jitter(done.stdout)


def trim(records):
    return records[-MAX_RECORDS:]


def run():
    write_json(STATE, {'running': True, 'started': now(), 'finished': None,
                       'status': 'running', 'message': ''})
    try:
        record = measure()
    except BaseException as failure:
        write_json(STATE, {'running': False, 'started': None, 'finished': now(),
                           'status': 'failed', 'message': str(failure)[:300]})
        raise
    write_json(HISTORY, trim(read_json(HISTORY, []) + [record]))
    write_json(STATE, {'running': False, 'started': None, 'finished': record['timestamp'],
                       'status': 'ok', 'message': ''})
    return record


def measure():
    command = [SPEEDTEST, '--json', '--secure']
    server = configured_server()
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
    return {
        'timestamp': raw.get('timestamp') or now(),
        'download': round(raw['download']),
        'upload': round(raw['upload']),
        'ping': round(raw['ping'], 3),
        'jitter': measure_jitter(target.get('host') or ''),
        'server_id': target.get('id'),
        'server_name': target.get('name'),
        'server_sponsor': target.get('sponsor'),
        'server_country': target.get('country'),
        'bytes_received': raw.get('bytes_received'),
        'bytes_sent': raw.get('bytes_sent'),
    }


def servers():
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
    assert parse_jitter('round-trip min/avg/max/stddev = 17.263/20.222/28.379/3.756 ms') == 3.756
    assert parse_jitter('10 packets transmitted, 0 packets received, 100.0% packet loss') is None
    assert parse_jitter('round-trip min/avg/max/stddev = a/b/c/d ms') is None
    assert read_json('/nonexistent/uplink-speedtest', []) == []
    return {'selftest': 'ok'}


if __name__ == '__main__':
    actions = {'run': run, 'servers': servers, 'selftest': selftest}
    action = sys.argv[1] if len(sys.argv) > 1 else ''
    if action not in actions:
        print('usage: uplink_speedtest.py run|servers|selftest', file=sys.stderr)
        sys.exit(1)
    try:
        print(json.dumps(actions[action]()))
    except Exception as failure:
        # exit 0 with the message on stdout: the API shows it, configd logs stderr
        print(str(failure)[:300], file=sys.stderr)
        print(json.dumps({'error': str(failure)[:300]}))
