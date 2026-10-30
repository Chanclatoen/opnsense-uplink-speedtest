#!/usr/local/bin/python3

"""
    Copyright (c) 2026 Uplink IT. All rights reserved.
    SPDX-License-Identifier: BSD-2-Clause (see LICENSE in the repository root).

    Cloudflare provider: measure the uplink against speed.cloudflare.com with nothing
    but the standard library, so the plugin needs no extra package for its default engine.

    Method: parallel HTTPS transfers kept running while a steady-state window in the
    middle is timed, which skips TCP slow start and the TLS handshake. Latency and jitter
    come from empty downloads on one warm connection. The PoP (colo) is Cloudflare's own.
"""

import http.client
import ssl
import statistics
import threading
import time

HOST = 'speed.cloudflare.com'
# per-request ceilings measured from this firewall 2026-10-30: __down answers 429 from
# exactly 10,000,000 bytes upward (and 403 from 100 MB), while __up still takes 100 MB.
# So the download runs on many small chunks instead; 200 MB over 25 requests drew no 429.
DOWN_CHUNK = 8000000
UP_CHUNK = 4000000      # small, so completed uploads land often inside the timed window
BLOCK = 262144
STREAMS = 4
RAMP_SECONDS = 2.0      # TCP slow start and the TLS handshake are not part of the measurement
WINDOW_SECONDS = 4.0    # the part that is timed
BUDGET = 700000000      # ceiling on bytes one direction may move, whatever the clock says
MAX_SECONDS = 25        # ... and a ceiling on the clock, whatever the bytes say
POLL = 0.02
SAMPLES = 20
TRIM = 2                # slowest samples dropped before latency is summarised
TIMEOUT = 30

_CONTEXT = ssl.create_default_context()


def connect():
    return http.client.HTTPSConnection(HOST, 443, context=_CONTEXT, timeout=TIMEOUT)


def check(response):
    """ turn Cloudflare's refusals into a message a human can act on
    """
    if response.status == 200:
        return
    if response.status == 429:
        raise RuntimeError('Cloudflare refused the transfer (HTTP 429): either the per-request '
                           'size is above its ceiling or this IP moved too much, try again later')
    raise RuntimeError('Cloudflare answered HTTP %d' % response.status)


def parse_trace(body):
    fields = dict(line.split('=', 1) for line in body.splitlines() if '=' in line)
    return fields.get('colo'), fields.get('loc')


def trace():
    """ which PoP and country Cloudflare served this box from
    """
    conn = connect()
    try:
        conn.request('GET', '/cdn-cgi/trace')
        response = conn.getresponse()
        body = response.read().decode('ascii', 'replace')
        if response.status != 200:
            return None, None
    finally:
        conn.close()
    return parse_trace(body)


def summarise(samples):
    """ median = ping, stddev = jitter, after dropping the slowest few

        An idle link gives ~40 ms with a 2 ms spread, but one stalled round trip is enough
        to report more jitter than latency, which is nonsense nobody can read a trend from.
    """
    if len(samples) < TRIM + 2:
        return None, None
    kept = sorted(samples)[:-TRIM]
    return round(statistics.median(kept), 3), round(statistics.stdev(kept), 3)


def latency():
    """ round trip of empty downloads on one warm connection

        speed.cloudflare.com does not answer ICMP, so unlike the other two providers this
        is an HTTPS round trip: a little above the network RTT, but consistently so.
    """
    conn = connect()
    samples = []
    try:
        for attempt in range(SAMPLES + 1):
            start = time.monotonic()
            conn.request('GET', '/__down?bytes=0')
            response = conn.getresponse()
            response.read()
            check(response)
            if attempt:  # the first one pays for TCP and TLS
                samples.append((time.monotonic() - start) * 1000)
    finally:
        conn.close()
    return summarise(samples)


def download_stream(counter, index, stop, errors):
    try:
        conn = connect()
        try:
            while not stop.is_set():
                conn.request('GET', '/__down?bytes=%d' % DOWN_CHUNK)
                response = conn.getresponse()
                check(response)
                while True:
                    block = response.read(BLOCK)
                    if not block:
                        break
                    counter[index] += len(block)
                    if stop.is_set():
                        return  # dropping the connection mid-body is what a browser does too
        finally:
            conn.close()
    except Exception as failure:
        errors.append(str(failure))


def upload_stream(counter, index, stop, errors):
    """ counts a chunk once Cloudflare has answered for it, never when the socket took it:
        the send buffer alone is tens of megabytes on this box and reported ~80% too much
    """
    block = b'\0' * BLOCK
    try:
        conn = connect()
        try:
            while not stop.is_set():
                conn.putrequest('POST', '/__up')
                conn.putheader('Content-Length', str(UP_CHUNK))
                conn.putheader('Content-Type', 'application/octet-stream')
                conn.endheaders()
                sent = 0
                while sent < UP_CHUNK:
                    # never a byte past Content-Length: the surplus would be read as the
                    # head of the next request on this connection and answered with a 400
                    conn.send(block[:min(BLOCK, UP_CHUNK - sent)])
                    sent = min(sent + BLOCK, UP_CHUNK)
                response = conn.getresponse()
                response.read()
                check(response)
                counter[index] += sent
        finally:
            conn.close()
    except Exception as failure:
        errors.append(str(failure))


def rate(moved, elapsed):
    return round(moved * 8 / elapsed) if elapsed > 0 else 0


def transfer(worker, streams):
    """ keep `streams` transfers running and time a fixed window once they are up to speed

        The clock decides the window, so the rate is steady state on a fast link and on a
        slow one alike; the byte budget and MAX_SECONDS are only ceilings, so one run can
        never cost Cloudflare (or the uplink) an arbitrary amount.
    """
    counter = [0] * streams
    stop = threading.Event()
    errors = []
    threads = [threading.Thread(target=worker, args=(counter, index, stop, errors))
               for index in range(streams)]
    for thread in threads:
        thread.start()
    began = time.monotonic()
    start, first = None, 0
    while True:
        total = sum(counter)
        clock = time.monotonic()
        if start is None and clock - began >= RAMP_SECONDS:
            start, first = clock, total
        elif start is not None and clock - start >= WINDOW_SECONDS:
            break
        if total >= BUDGET or clock - began >= MAX_SECONDS:
            break
        if not any(thread.is_alive() for thread in threads):
            break
        time.sleep(POLL)
    moved, elapsed = sum(counter) - first, time.monotonic() - (start or time.monotonic())
    stop.set()
    for thread in threads:
        thread.join(TIMEOUT)
    if moved <= 0 or elapsed <= 0:
        raise RuntimeError(errors[0] if errors else 'no data moved to or from Cloudflare')
    # a stream that died took its share of the link with it, so the number would read low
    if errors:
        raise RuntimeError('%d of %d Cloudflare streams failed: %s'
                           % (len(errors), streams, errors[0]))
    return rate(moved, elapsed), sum(counter)


def measure(streams=STREAMS):
    colo, country = trace()
    ping, jitter = latency()
    download, received = transfer(download_stream, streams)
    upload, sent = transfer(upload_stream, streams)
    return {
        'provider': 'cloudflare',
        'download': download,
        'upload': upload,
        'ping': ping,
        'jitter': jitter,
        'server_id': None,
        'server_name': colo,
        'server_sponsor': 'Cloudflare',
        'server_country': country,
        'bytes_received': received,
        'bytes_sent': sent,
    }


def selftest():
    assert parse_trace('fl=1\nh=speed.cloudflare.com\ncolo=FRA\nloc=DE\n') == ('FRA', 'DE')
    assert parse_trace('') == (None, None)
    assert parse_trace('colo=CDG') == ('CDG', None)
    assert rate(125000000, 4.0) == 250000000
    assert rate(10, 0) == 0
    # the 429 ceiling is the whole reason the download is chunked; keep a guard on it
    assert DOWN_CHUNK < 10000000
    # and the upload must land on Content-Length exactly, not on a whole number of blocks
    assert UP_CHUNK % BLOCK != 0

    steady = [40.0, 41.0, 39.0, 40.0, 41.0, 39.0]
    assert summarise(steady) == (39.5, 0.577)
    # one stalled round trip must not outweigh five good ones
    assert summarise(steady[:-1] + [900.0]) == summarise(steady[:-1] + [500.0])
    assert summarise([40.0, 41.0]) == (None, None)

    class Refused:
        status = 429
    class Served:
        status = 200
    try:
        check(Refused())
        raise AssertionError('429 must raise')
    except RuntimeError as failure:
        assert '429' in str(failure)
    check(Served())
