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
    Shared by the daemon (wan8021xd.py) and the configd helper (ctl.py).
    setup.php writes CONF_DIR and the ctrl_interface=CTRL_DIR line, keep in sync.
"""

import json
import os
import socket
import uuid

CONF_DIR = '/var/etc/wan8021x'
CTRL_DIR = '/var/run/wan8021x'
INDEX_FILE = os.path.join(CONF_DIR, 'supplicants.json')
STATUS_FILE = os.path.join(CTRL_DIR, 'status.json')


class CtrlClient:
    """Client for one wpa_supplicant control interface (unix datagram socket)."""

    def __init__(self, device):
        self.path = os.path.join(CTRL_DIR, device)
        self.device = device
        self.sock = None

    def _open(self, timeout):
        """Bind a uniquely named local socket and connect it; caller owns the returned pair."""
        local = os.path.join(CTRL_DIR, '.cli-%s-%s' % (self.device, uuid.uuid4().hex[:12]))
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            sock.bind(local)
        except OSError:
            sock.close()
            raise
        try:
            sock.connect(self.path)
            sock.settimeout(timeout)
        except OSError:
            sock.close()
            os.unlink(local)
            raise
        return sock, local

    def attach(self):
        """Subscribe to unsolicited events; the socket is left non-blocking for select()."""
        self.close()
        sock, local = self._open(2)
        try:
            sock.send(b'ATTACH')
            if not sock.recv(4096).startswith(b'OK'):
                raise OSError('ATTACH refused')
        except OSError:
            sock.close()
            os.unlink(local)
            raise
        sock.setblocking(False)
        self.sock, self.local = sock, local

    def command(self, cmd, timeout=3):
        """Send one command on a separate socket, so replies never mix with events."""
        sock, local = self._open(timeout)
        try:
            sock.send(cmd.encode())
            return sock.recv(16384).decode(errors='replace')
        finally:
            sock.close()
            os.unlink(local)

    def close(self):
        if self.sock is not None:
            try:
                self.sock.send(b'DETACH')
            except OSError:
                pass
            self.sock.close()
            self.sock = None
            try:
                os.unlink(self.local)
            except FileNotFoundError:
                pass


def parse_status(text):
    """wpa_cli STATUS output -> dict"""
    result = {}
    for line in text.splitlines():
        key, sep, value = line.partition('=')
        if sep:
            result[key] = value
    return result


def load_status():
    try:
        with open(STATUS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []
