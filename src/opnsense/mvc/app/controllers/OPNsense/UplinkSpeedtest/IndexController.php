<?php

/*
 * Copyright (c) 2026 Uplink IT. All rights reserved.
 * SPDX-License-Identifier: BSD-2-Clause (see LICENSE in the repository root).
 */

namespace OPNsense\UplinkSpeedtest;

class IndexController extends \OPNsense\Base\IndexController
{
    public function indexAction()
    {
        $this->view->generalForm = $this->getForm('general');
        $this->view->pick('OPNsense/UplinkSpeedtest/index');
    }
}
