<?php

/*
 * Copyright (C) 2026 yutong.li
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * 1. Redistributions of source code must retain the above copyright notice,
 *    this list of conditions and the following disclaimer.
 *
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES,
 * INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
 * AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 * AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
 * OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 */

namespace OPNsense\Wan8021x\Api;

use OPNsense\Base\ApiMutableServiceControllerBase;
use OPNsense\Core\Backend;
use OPNsense\Wan8021x\Wan8021x;

class ServiceController extends ApiMutableServiceControllerBase
{
    protected static $internalServiceClass = '\OPNsense\Wan8021x\Wan8021x';
    protected static $internalServiceTemplate = 'OPNsense/Wan8021x';
    protected static $internalServiceEnabled = 'general.enabled';
    protected static $internalServiceName = 'wan8021x';

    /**
     * The daemon has nothing to do without an enabled supplicant, as in wan8021x_enabled().
     */
    protected function serviceEnabled()
    {
        return (new Wan8021x())->isActive();
    }

    /**
     * Per interface EAP state as reported by the running supplicants.
     */
    public function supplicantsAction()
    {
        $result = json_decode((new Backend())->configdRun('wan8021x supplicants'), true);
        return ['rows' => is_array($result) ? $result : []];
    }

    /**
     * Restart the 802.1X exchange on one interface, e.g. after changing credentials on the switch side.
     */
    public function reauthenticateAction($interface)
    {
        if ($this->request->isPost()) {
            $response = trim((new Backend())->configdpRun('wan8021x reauthenticate', [$interface]));
            return ['status' => $response == 'OK' ? 'ok' : 'failed', 'response' => $response];
        }
        return ['status' => 'failed'];
    }
}
