<?php

/*
 * Copyright (c) 2026 Uplink IT. All rights reserved.
 * SPDX-License-Identifier: BSD-2-Clause (see LICENSE in the repository root).
 */

namespace OPNsense\UplinkSpeedtest\Api;

use OPNsense\Base\ApiControllerBase;
use OPNsense\Core\Backend;
use OPNsense\UplinkSpeedtest\General;

class ServiceController extends ApiControllerBase
{
    private const DATA_DIR = '/var/db/uplink-speedtest';
    private const MAX_ROWS = 1000;
    private const PROVIDERS = ['cloudflare', 'ookla', 'iperf3'];
    /* results written by 1.0 predate the provider field and were all Ookla */
    private const LEGACY_PROVIDER = 'ookla';

    /**
     * start a measurement in the background; the test outlives a web request, so do not wait for it
     */
    public function runAction()
    {
        if (!$this->request->isPost()) {
            return ['status' => 'failed', 'message' => gettext('Use POST to start a test.')];
        }
        $provider = (string)$this->request->getPost('provider', null, '');
        if ($provider === '') {
            (new Backend())->configdRun('uplinkspeedtest run', true);
            return ['status' => 'started', 'provider' => $this->defaultProvider()];
        }
        if (!in_array($provider, self::PROVIDERS, true)) {
            return ['status' => 'failed', 'message' => gettext('Unknown provider.')];
        }
        (new Backend())->configdpRun('uplinkspeedtest runwith', [$provider], true);
        return ['status' => 'started', 'provider' => $provider];
    }

    /**
     * progress of the last/current run, so the UI can poll instead of holding a request open
     */
    public function statusAction()
    {
        $state = $this->readJson('state.json');
        return [
            'running' => !empty($state['running']),
            'last_status' => $state['status'] ?? 'unknown',
            'last_message' => $state['message'] ?? '',
            'provider' => $state['provider'] ?? '',
            'finished' => $state['finished'] ?? null,
        ];
    }

    /**
     * newest first, optionally one provider only ("default" = the configured one), so a
     * chart or sparkline never mixes engines that are not comparable
     */
    public function historyAction()
    {
        $records = $this->readJson('history.json');
        if (!array_is_list($records)) {
            $records = [];
        }
        $provider = (string)$this->request->get('provider', null, '');
        if ($provider === 'default') {
            $provider = $this->defaultProvider();
        }
        $matching = [];
        foreach ($records as $record) {
            if (!is_array($record)) {
                continue;
            }
            $record['provider'] = $record['provider'] ?? self::LEGACY_PROVIDER;
            if ($provider !== '' && $record['provider'] !== $provider) {
                continue;
            }
            $matching[] = $record;
        }
        $limit = (int)$this->request->get('limit', null, 50);
        $limit = max(1, min($limit, self::MAX_ROWS));
        $rows = array_slice($matching, -$limit);
        return [
            'provider' => $provider,
            'total' => count($matching),
            'rows' => array_reverse($rows),
            'stats' => $this->stats($rows),
        ];
    }

    /**
     * which providers produced results, so the page can offer a filter that is not empty
     */
    public function providersAction()
    {
        $records = $this->readJson('history.json');
        $counts = [];
        foreach ($records as $record) {
            if (is_array($record)) {
                $name = $record['provider'] ?? self::LEGACY_PROVIDER;
                $counts[$name] = ($counts[$name] ?? 0) + 1;
            }
        }
        return ['default' => $this->defaultProvider(), 'counts' => $counts];
    }

    public function serversAction()
    {
        $output = (new Backend())->configdRun('uplinkspeedtest servers', false, 120);
        $servers = json_decode(trim((string)$output), true);
        if (!is_array($servers) || !array_is_list($servers)) {
            $message = is_array($servers) ? ($servers['error'] ?? '') : '';
            return ['status' => 'failed',
                    'message' => $message ?: gettext('Could not fetch the speedtest server list.')];
        }
        return ['status' => 'ok', 'rows' => $servers];
    }

    private function defaultProvider(): string
    {
        $configured = (string)(new General())->provider;
        return in_array($configured, self::PROVIDERS, true) ? $configured : 'cloudflare';
    }

    private function readJson(string $name): array
    {
        $filename = self::DATA_DIR . '/' . $name;
        if (!is_readable($filename)) {
            return [];
        }
        $data = json_decode((string)file_get_contents($filename), true);
        return is_array($data) ? $data : [];
    }

    /**
     * min/avg/max over the returned window; nulls (no jitter measured) are left out
     */
    private function stats(array $rows): array
    {
        $stats = [];
        foreach (['download', 'upload', 'ping', 'jitter'] as $field) {
            $values = [];
            foreach ($rows as $row) {
                if (isset($row[$field]) && is_numeric($row[$field])) {
                    $values[] = (float)$row[$field];
                }
            }
            $stats[$field] = $values === [] ? null : [
                'min' => min($values),
                'avg' => array_sum($values) / count($values),
                'max' => max($values),
                'count' => count($values),
            ];
        }
        return $stats;
    }
}
