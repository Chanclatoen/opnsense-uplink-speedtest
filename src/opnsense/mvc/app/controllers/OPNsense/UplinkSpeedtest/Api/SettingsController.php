<?php

/*
 * Copyright (c) 2026 Chanclatoen. All rights reserved.
 * SPDX-License-Identifier: BSD-2-Clause (see LICENSE in the repository root).
 */

namespace OPNsense\UplinkSpeedtest\Api;

use OPNsense\Base\ApiMutableModelControllerBase;

class SettingsController extends ApiMutableModelControllerBase
{
    protected static $internalModelName = 'general';
    protected static $internalModelClass = 'OPNsense\UplinkSpeedtest\General';
}
