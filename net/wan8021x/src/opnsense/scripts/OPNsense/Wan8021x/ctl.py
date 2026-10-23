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
import os
import socket
import sys

CTRL_DIR = '/var/run/wan8021x'
STATUS_FILE = os.path.join(CTRL_DIR, 'status.json')

# wpa_cli status keys passed on to the GUI
STATUS_KEYS = {
    'Supplicant PAE state': 'pae_state',
    'suppPortStatus': 'port',
    'EAP state': 'eap_state',
    'selectedMethod': 'method',
}


def ctrl_command(device, cmd):
    local = os.path.join(CTRL_DIR, '.ctl-%s-%d' % (device, os.getpid()))
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.bind(local)
        sock.connect(os.path.join(CTRL_DIR, device))
        sock.settimeout(3)
        sock.send(cmd.encode())
        return sock.recv(16384).decode(errors='replace')
    finally:
        sock.close()
        os.unlink(local)


def load_status():
    try:
        with open(STATUS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def supplicants():
    rows = load_status()
    for row in rows:
        try:
            for line in ctrl_command(row['device'], 'STATUS').splitlines():
                key, _, value = line.partition('=')
                if key in STATUS_KEYS:
                    row[STATUS_KEYS[key]] = value
                elif key.endswith('Phase2 method'):
                    row['method'] = '%s / %s' % (row.get('method', ''), value)
        except OSError:
            row['port'] = ''
    print(json.dumps(rows))


def reauthenticate(interface):
    for row in load_status():
        if row['interface'] == interface:
            print(ctrl_command(row['device'], 'REAUTHENTICATE').strip())
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
