#!/usr/local/bin/python3

"""
    Copyright (c) 2026 yutong.li
    All rights reserved.

    Redistribution and use in source and binary forms, with or without
    modification, are permitted provided that the following conditions are met:

    1. Redistributions of source code must retain the above copyright notice,
     this list of conditions and the following disclaimer.

    2. Redistributions in binary form must reproduce the above copyright
     notice, this list of conditions and the following disclaimer in the
     documentation and/or other materials provided with the distribution.

    THIS SOFTWARE IS PROVIDED ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES,
    INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY
    AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
    AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
    OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
    SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
    INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
    CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
    ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
    POSSIBILITY OF SUCH DAMAGE.

    --------------------------------------------------------------------------------------
    ctl.py supplicants              JSON status of all supplicants
    ctl.py reauthenticate <if>      restart authentication on an interface (e.g. wan)
"""

import json
import sys

# nothing may be written next to the packaged files, it would survive package removal
sys.dont_write_bytecode = True
from wan8021x_lib import CtrlClient, load_status, parse_status  # noqa: E402

# wpa_cli status keys passed on to the GUI
STATUS_KEYS = {
    'Supplicant PAE state': 'pae_state',
    'suppPortStatus': 'port',
    'EAP state': 'eap_state',
}


def overall(row):
    """The daemon's view wins: after a cable pull wpa_supplicant still says Authorized
    although the switch has reset the port."""
    if row['state'] == 'authenticated' and row.get('port') == 'Authorized':
        return 'authorized'
    if row['state'] in ('failed', 'stopped'):
        return 'failed'
    return 'pending'


def supplicants():
    rows = load_status()
    for row in rows:
        try:
            status = parse_status(CtrlClient(row['device']).command('STATUS'))
        except OSError as e:
            status = {}
            row['ctrl_error'] = str(e)
        for key, name in STATUS_KEYS.items():
            row[name] = status.get(key, '')
        # "25 (EAP-PEAP)" -> "PEAP"
        method = status.get('selectedMethod', '')
        row['method'] = method.split('(')[-1].rstrip(')').removeprefix('EAP-') if '(' in method else method
        row['phase2'] = next((v for k, v in status.items() if k.endswith('Phase2 method')), '')
        row['status'] = overall(row)
    print(json.dumps(rows))


def reauthenticate(interface):
    for row in load_status():
        if row['interface'] == interface:
            try:
                print(CtrlClient(row['device']).command('REAUTHENTICATE').strip())
                return 0
            except OSError as e:
                # configd drops the output of a failing script, report through the text
                print('failed: %s' % e)
                return 0
    print('unknown interface')
    return 1


if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'supplicants':
        supplicants()
    elif len(sys.argv) >= 3 and sys.argv[1] == 'reauthenticate':
        sys.exit(reauthenticate(sys.argv[2]))
    else:
        print(__doc__.split('-' * 86)[1].strip())
        sys.exit(64)
