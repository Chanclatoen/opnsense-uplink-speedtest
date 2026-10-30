<?php

/*
 * Copyright (c) 2026 Uplink IT. All rights reserved.
 * SPDX-License-Identifier: BSD-2-Clause (see LICENSE in the repository root).
 */

namespace OPNsense\UplinkSpeedtest\Api;

use OPNsense\Base\ApiControllerBase;
use OPNsense\Core\Backend;

class ServiceController extends ApiControllerBase
{
    private const DATA_DIR = '/var/db/uplink-speedtest';
    private const MAX_ROWS = 1000;

    /**
     * start a measurement in the background; the test outlives a web request, so do not wait for it
     */
    public function runAction()
    {
        if (!$this->request->isPost()) {
            return ['status' => 'failed', 'message' => gettext('Use POST to start a test.')];
        }
        (new Backend())->configdRun('uplinkspeedtest run', true);
        return ['status' => 'started'];
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
            'finished' => $state['finished'] ?? null,
        ];
    }

    public function historyAction()
    {
        $records = $this->readJson('history.json');
        if (!array_is_list($records)) {
            $records = [];
        }
        $limit = (int)$this->request->get('limit', null, 50);
        $limit = max(1, min($limit, self::MAX_ROWS));
        $rows = array_slice($records, -$limit);
        return [
            'total' => count($records),
            'rows' => array_reverse($rows),
            'stats' => $this->stats($rows),
        ];
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
