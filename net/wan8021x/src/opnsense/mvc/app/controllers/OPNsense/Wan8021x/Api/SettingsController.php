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

use OPNsense\Base\ApiMutableModelControllerBase;

class SettingsController extends ApiMutableModelControllerBase
{
    protected static $internalModelName = 'wan8021x';
    protected static $internalModelClass = '\OPNsense\Wan8021x\Wan8021x';

    /**
     * The grid serializes raw field values, which would expose the write-only password, and
     * searches all listed fields, which would allow guessing it. Name the fields explicitly and
     * strip the password from the rows.
     */
    public function searchSupplicantAction()
    {
        $fields = [
            'enabled', 'interface', 'description', 'eap_method', 'phase2', 'identity',
            'anonymous_identity', 'ca', 'domain_match', 'eapol_version',
        ];
        $result = $this->searchBase('supplicants.supplicant', $fields);
        foreach ($result['rows'] as &$row) {
            unset($row['password'], $row['%password']);
        }
        unset($row);
        return $result;
    }

    public function getSupplicantAction($uuid = null)
    {
        return $this->getBase('supplicant', 'supplicants.supplicant', $uuid);
    }

    public function addSupplicantAction()
    {
        return $this->addBase('supplicant', 'supplicants.supplicant');
    }

    public function setSupplicantAction($uuid)
    {
        return $this->setBase('supplicant', 'supplicants.supplicant', $uuid);
    }

    public function delSupplicantAction($uuid)
    {
        return $this->delBase('supplicants.supplicant', $uuid);
    }

    public function toggleSupplicantAction($uuid, $enabled = null)
    {
        return $this->toggleBase('supplicants.supplicant', $uuid, $enabled);
    }
}
