#!/usr/local/bin/php
<?php

/*
 * Copyright (c) 2026 Chanclatoen. All rights reserved.
 * SPDX-License-Identifier: BSD-2-Clause (see LICENSE in the repository root).
 *
 * Carry an older release of this plugin over to the identifiers this one uses, so an
 * upgrade keeps the settings, the cron schedule, the page privilege and the widget that
 * is already on somebody's dashboard. legacy-migrate.sh reads the old identifiers off
 * the files on disk and passes them in; nothing here is specific to one name.
 *
 * usage: migrate-legacy-config.php <oldNamespace> <newNamespace> <oldAction> <newAction>
 *                                  <oldWidgetId> <newWidgetId>
 */

if ($argc !== 7) {
    fwrite(STDERR, "usage: {$argv[0]} oldNs newNs oldAction newAction oldWidget newWidget\n");
    exit(2);
}
list(, $oldNs, $newNs, $oldAction, $newAction, $oldWidget, $newWidget) = $argv;
foreach (['oldNs' => $oldNs, 'newNs' => $newNs] as $name => $value) {
    if (!preg_match('/^[A-Za-z][A-Za-z0-9_]*$/', $value)) {
        fwrite(STDERR, "{$name} is not a usable XML element name\n");
        exit(2);
    }
}

chdir('/usr/local/opnsense/mvc');
require_once('script/load_phalcon.php');

$config = \OPNsense\Core\Config::getInstance();
$dom = dom_import_simplexml($config->object())->ownerDocument;
$xpath = new DOMXPath($dom);
$done = [];

/* the settings node, kept whole: only if this release has not already written its own */
if ($oldNs !== $newNs && $xpath->query("/opnsense/OPNsense/{$newNs}")->length === 0) {
    foreach ($xpath->query("/opnsense/OPNsense/{$oldNs}") as $old) {
        $new = $dom->createElement($newNs);
        foreach (iterator_to_array($old->attributes) as $attribute) {
            $new->setAttributeNode($attribute->cloneNode(true));
        }
        while ($old->firstChild !== null) {
            $new->appendChild($old->firstChild);
        }
        $old->parentNode->replaceChild($new, $old);
        $done[] = 'settings';
    }
}

/* cron jobs keep their schedule and description, only the command is renamed */
if ($oldAction !== $newAction) {
    foreach ($xpath->query('//job/command') as $command) {
        $value = trim($command->textContent);
        if ($value === $oldAction || strpos($value, $oldAction . ' ') === 0) {
            $command->nodeValue = $newAction . substr($value, strlen($oldAction));
            $done[] = 'cron';
        }
    }
}

/* the page privilege, so a non-admin user keeps the access an admin gave them */
$oldPriv = 'page-' . $oldWidget;
$newPriv = 'page-' . $newWidget;
if ($oldPriv !== $newPriv) {
    foreach ($xpath->query('//priv') as $priv) {
        if (trim($priv->textContent) === $oldPriv) {
            $priv->nodeValue = $newPriv;
            $done[] = 'privilege';
        }
    }
}

/* every user's dashboard layout is base64-encoded JSON holding the widget ids */
if ($oldWidget !== $newWidget) {
    foreach ($xpath->query('//dashboard') as $dashboard) {
        $layout = base64_decode(trim($dashboard->textContent), true);
        if ($layout === false || strpos($layout, '"' . $oldWidget . '"') === false) {
            continue;
        }
        $dashboard->nodeValue = base64_encode(
            str_replace('"' . $oldWidget . '"', '"' . $newWidget . '"', $layout)
        );
        $done[] = 'dashboard';
    }
}

if (empty($done)) {
    echo "nothing to migrate\n";
    exit(0);
}
$config->save();
echo 'migrated: ' . implode(', ', array_unique($done)) . "\n";
