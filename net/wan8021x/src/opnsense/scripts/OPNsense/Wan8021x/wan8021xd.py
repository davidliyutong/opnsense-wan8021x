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
    Supervisor for wired 802.1X supplicants.

    For every entry in supplicants.json (written by setup.php) it runs one
    wpa_supplicant with the wired driver, restarts it when it exits, and
    follows its control interface to keep a status file for the GUI.

    The FreeBSD wired driver does not notice link changes: after a cable
    pull the switch resets the port to unauthorized while the supplicant still
    believes it is authenticated. Link state is therefore followed through
    "route -n monitor" and a link up triggers a re-authentication.
"""

import json
import os
import re
import select
import signal
import socket
import subprocess
import sys
import syslog
import time

CONF_DIR = '/var/etc/wan8021x'
CTRL_DIR = '/var/run/wan8021x'
STATUS_FILE = os.path.join(CTRL_DIR, 'status.json')
WPA_SUPPLICANT = '/usr/local/sbin/wpa_supplicant'
RESTART_DELAY = 5

# "add/repl iface iface#2 vtnet1 admin UP oper DOWN mtu 1500"
IFACE_EVENT = re.compile(r'\biface#\d+\s+(\S+)\s+admin\s+(\S+)\s+oper\s+(\S+)')
CTRL_EVENT = re.compile(r'^<\d>(\S+)\s*(.*)$')


def log(priority, message):
    syslog.syslog(priority, message)


class CtrlClient:
    """Attached client on a wpa_supplicant control socket (unix datagram)."""

    def __init__(self, device):
        self.path = os.path.join(CTRL_DIR, device)
        self.local = os.path.join(CTRL_DIR, '.cli-%s-%d' % (device, os.getpid()))
        self.sock = None

    def connect(self):
        self.close()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.bind(self.local)
        sock.connect(self.path)
        sock.settimeout(2)
        sock.send(b'ATTACH')
        if not sock.recv(4096).startswith(b'OK'):
            sock.close()
            raise OSError('ATTACH refused')
        sock.setblocking(False)
        self.sock = sock

    def command(self, cmd):
        """Send a command on a separate socket, unsolicited events stay on the attached one."""
        local = self.local + '.cmd'
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            if os.path.exists(local):
                os.unlink(local)
            sock.bind(local)
            sock.connect(self.path)
            sock.settimeout(3)
            sock.send(cmd.encode())
            return sock.recv(16384).decode(errors='replace')
        finally:
            sock.close()
            if os.path.exists(local):
                os.unlink(local)

    def close(self):
        if self.sock is not None:
            try:
                self.sock.send(b'DETACH')
            except OSError:
                pass
            self.sock.close()
            self.sock = None
        if os.path.exists(self.local):
            os.unlink(self.local)


class Supplicant:
    def __init__(self, entry, debug):
        self.interface = entry['interface']
        self.description = entry.get('description', '')
        self.device = entry['device']
        self.config = entry['config']
        self.debug = debug
        self.proc = None
        self.ctrl = CtrlClient(self.device)
        self.next_start = 0
        self.link = None
        self.state = 'starting'
        self.last_error = ''
        self.last_event = ''
        self.authenticated_at = None

    def device_exists(self):
        try:
            socket.if_nametoindex(self.device)
            return True
        except OSError:
            return False

    def start(self):
        if not self.device_exists():
            self.set_state('waiting', 'device %s does not exist' % self.device)
            self.next_start = time.time() + RESTART_DELAY
            return
        args = [WPA_SUPPLICANT, '-D', 'wired', '-i', self.device, '-c', self.config]
        if self.debug:
            args.append('-d')
        log(syslog.LOG_NOTICE, '%s: starting supplicant on %s' % (self.interface, self.device))
        self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        os.set_blocking(self.proc.stdout.fileno(), False)
        self.set_state('authenticating')
        # the control socket appears shortly after start
        for _ in range(50):
            if os.path.exists(self.ctrl.path):
                try:
                    self.ctrl.connect()
                    break
                except OSError:
                    pass
            time.sleep(0.1)
        else:
            log(syslog.LOG_WARNING, '%s: control interface not available' % self.interface)

    def stop(self):
        self.ctrl.close()
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None

    def set_state(self, state, error=None):
        self.state = state
        if error is not None:
            self.last_error = error

    def reauthenticate(self, reason):
        if self.ctrl.sock is None:
            return False
        log(syslog.LOG_NOTICE, '%s: re-authenticating (%s)' % (self.interface, reason))
        self.set_state('authenticating')
        return self.ctrl.command('REAUTHENTICATE').startswith('OK')

    def fds(self):
        result = []
        if self.proc is not None:
            result.append(self.proc.stdout)
        if self.ctrl.sock is not None:
            result.append(self.ctrl.sock)
        return result

    def on_output(self):
        data = self.proc.stdout.read()
        if data:
            for line in data.decode(errors='replace').splitlines():
                if line.strip():
                    # most supplicant messages already carry the interface name
                    if not line.startswith(self.device + ':'):
                        line = '%s: %s' % (self.device, line)
                    log(syslog.LOG_INFO, line)

    def on_ctrl(self):
        try:
            while True:
                msg = self.ctrl.sock.recv(4096).decode(errors='replace')
                self.on_event(msg)
        except BlockingIOError:
            pass
        except OSError:
            self.ctrl.close()

    def on_event(self, msg):
        match = CTRL_EVENT.match(msg)
        if not match:
            return
        event, args = match.groups()
        self.last_event = event
        if event == 'CTRL-EVENT-EAP-STARTED':
            self.set_state('authenticating')
        elif event == 'CTRL-EVENT-EAP-SUCCESS':
            self.authenticated_at = int(time.time())
            self.set_state('authenticated', '')
            log(syslog.LOG_NOTICE, '%s: authentication succeeded' % self.interface)
        elif event == 'CTRL-EVENT-EAP-FAILURE':
            if self.state != 'failed' or not self.last_error:
                self.last_error = 'authentication rejected (check identity and password)'
            self.set_state('failed')
            log(syslog.LOG_ERR, '%s: authentication failed: %s' % (self.interface, self.last_error))
        elif event == 'CTRL-EVENT-EAP-TLS-CERT-ERROR':
            err = re.search(r"err='([^']*)'", args)
            self.set_state('failed', 'server certificate rejected: %s' % (err.group(1) if err else args))
        elif event == 'CTRL-EVENT-EAP-TIMEOUT-FAILURE' or event == 'CTRL-EVENT-EAP-TIMEOUT-FAILURE2':
            self.set_state('failed', 'authentication timed out')
        elif event == 'CTRL-EVENT-DISCONNECTED':
            self.set_state('authenticating')
        elif event.startswith('CTRL-REQ-'):
            # the supplicant waits for interactive input that will never come
            field = event[len('CTRL-REQ-'):].split('-')[0].lower()
            self.set_state('failed', 'credentials incomplete: %s missing' % field)
            log(syslog.LOG_ERR, '%s: %s' % (self.interface, self.last_error))

    def check(self, now):
        """Restart a supplicant that exited."""
        if self.proc is not None and self.proc.poll() is not None:
            self.on_output()
            log(syslog.LOG_ERR, '%s: supplicant exited with %d' % (self.interface, self.proc.returncode))
            self.ctrl.close()
            self.proc = None
            self.set_state('stopped', 'supplicant exited unexpectedly')
            self.next_start = now + RESTART_DELAY
        if self.proc is None and now >= self.next_start:
            self.start()

    def status(self):
        result = {
            'interface': self.interface,
            'description': self.description,
            'device': self.device,
            'state': self.state,
            'link': self.link,
            'last_error': self.last_error,
            'last_event': self.last_event,
            'authenticated_at': self.authenticated_at,
            'pid': self.proc.pid if self.proc is not None else None,
        }
        return result


class Daemon:
    def __init__(self, index):
        debug = index.get('debug', False)
        self.supplicants = {s['device']: Supplicant(s, debug) for s in index.get('supplicants', [])}
        self.monitor = None
        self.running = True
        self.last_status = None

    def start_monitor(self):
        self.monitor = subprocess.Popen(['/sbin/route', '-n', 'monitor'], stdout=subprocess.PIPE,
                                        stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.set_blocking(self.monitor.stdout.fileno(), False)
        self.monitor_buf = b''

    def on_monitor(self):
        data = self.monitor.stdout.read()
        if not data:
            return
        self.monitor_buf += data
        *lines, self.monitor_buf = self.monitor_buf.split(b'\n')
        for line in lines:
            match = IFACE_EVENT.search(line.decode(errors='replace'))
            if not match:
                continue
            device, _admin, oper = match.groups()
            sup = self.supplicants.get(device)
            if sup is None:
                continue
            up = oper == 'UP'
            if up and sup.link is False:
                sup.link = True
                sup.reauthenticate('link up')
            elif not up and sup.link is not False:
                sup.link = False
                log(syslog.LOG_NOTICE, '%s: link down' % sup.interface)
                sup.set_state('link down')
            elif up:
                sup.link = True

    def write_status(self):
        status = [s.status() for s in self.supplicants.values()]
        if status != self.last_status:
            tmp = STATUS_FILE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(status, f)
            os.rename(tmp, STATUS_FILE)
            self.last_status = status

    def stop(self, *_args):
        self.running = False

    def run(self):
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        self.start_monitor()
        for sup in self.supplicants.values():
            sup.start()
        while self.running:
            fds = {self.monitor.stdout: None}
            for sup in self.supplicants.values():
                for fd in sup.fds():
                    fds[fd] = sup
            try:
                readable, _, _ = select.select(list(fds), [], [], 2)
            except InterruptedError:
                continue
            for fd in readable:
                sup = fds[fd]
                if sup is None:
                    self.on_monitor()
                elif sup.proc is not None and fd is sup.proc.stdout:
                    sup.on_output()
                else:
                    sup.on_ctrl()
            if self.monitor.poll() is not None:
                self.start_monitor()
            now = time.time()
            for sup in self.supplicants.values():
                sup.check(now)
            self.write_status()
        for sup in self.supplicants.values():
            sup.stop()
        self.monitor.terminate()
        if os.path.exists(STATUS_FILE):
            os.unlink(STATUS_FILE)


def main():
    syslog.openlog('wan8021x', syslog.LOG_PID, syslog.LOG_DAEMON)
    os.makedirs(CTRL_DIR, mode=0o700, exist_ok=True)
    try:
        with open(os.path.join(CONF_DIR, 'supplicants.json')) as f:
            index = json.load(f)
    except (OSError, ValueError) as e:
        log(syslog.LOG_ERR, 'cannot read configuration: %s' % e)
        return 1
    if not index.get('supplicants'):
        # stay up for the service supervisor, there is just nothing to do
        log(syslog.LOG_NOTICE, 'no supplicant configured')
        signal.signal(signal.SIGTERM, lambda *_args: sys.exit(0))
        while True:
            signal.pause()
    Daemon(index).run()
    return 0


if __name__ == '__main__':
    sys.exit(main())
