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

namespace OPNsense\Wan8021x;

use OPNsense\Base\BaseModel;
use OPNsense\Base\Messages\Message;

class Wan8021x extends BaseModel
{
    public function performValidation($validateFullModel = false)
    {
        $messages = parent::performValidation($validateFullModel);

        foreach ($this->supplicants->supplicant->iterateItems() as $supplicant) {
            if (!$validateFullModel && !$supplicant->isFieldChanged()) {
                continue;
            }
            $key = $supplicant->__reference;
            if ($supplicant->phase2->isEqual('PAP') && !$supplicant->eap_method->isEqual('TTLS')) {
                $messages->appendMessage(new Message(
                    gettext('PAP can only be used as the inner method of TTLS.'),
                    $key . '.phase2'
                ));
            }
            if (!$supplicant->domain_match->isEmpty() && $supplicant->ca->isEmpty()) {
                $messages->appendMessage(new Message(
                    gettext('Matching the server domain requires a certificate authority to validate against.'),
                    $key . '.domain_match'
                ));
            }
        }

        return $messages;
    }

    /**
     * @return bool true when the service should run: enabled with at least one enabled supplicant
     */
    public function isActive()
    {
        if (!$this->general->enabled->isEqual('1')) {
            return false;
        }
        foreach ($this->supplicants->supplicant->iterateItems() as $supplicant) {
            if ($supplicant->enabled->isEqual('1')) {
                return true;
            }
        }
        return false;
    }
}
