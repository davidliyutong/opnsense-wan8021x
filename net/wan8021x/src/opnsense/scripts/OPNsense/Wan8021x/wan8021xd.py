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
    "route -n monitor" and a link up triggers a re-authentication, which is
    retried until the supplicant accepts it.

    Manual re-authentication requests (ctl.py) arrive on DAEMON_SOCK and take
    the same path.
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

# nothing may be written next to the packaged files, it would survive package removal
sys.dont_write_bytecode = True
from wan8021x_lib import CTRL_DIR, DAEMON_SOCK, INDEX_FILE, STATUS_FILE, CtrlClient, parse_status  # noqa: E402

WPA_SUPPLICANT = '/usr/local/sbin/wpa_supplicant'
RESTART_DELAY = 5
ATTACH_RETRY = 1
ATTACH_TIMEOUT = 2
# Requests to a supplicant block the shared loop, keep them short. One that stops
# answering on its control interface for HUNG_TIMEOUT is killed and restarted.
CTRL_TIMEOUT = 1
HUNG_TIMEOUT = 10
# After an EAPOL-Start, start over when the exchange has not begun (lost Start, common at
# link up) or not finished (lost frame mid-way) in time, instead of waiting for
# wpa_supplicant's own 30s startPeriod/authPeriod. Doubled per consecutive attempt up to
# EAP_TIMEOUT_SCALE times, so a port without an authenticator is not hammered.
EAP_START_TIMEOUT = 10
EAP_RESULT_TIMEOUT = 20
EAP_TIMEOUT_SCALE = 6

# "add/repl iface iface#2 vtnet1 admin UP oper DOWN mtu 1500"
IFACE_EVENT = re.compile(r'\biface#\d+\s+(\S+)\s+admin\s+(\S+)\s+oper\s+(\S+)')
CTRL_EVENT = re.compile(r'^<\d>(\S+)\s*(.*)$')


def log(priority, message):
    syslog.syslog(priority, message)


def guarded(sup, func, *args):
    """Run a per-interface step; an error on one interface must not stop the others."""
    try:
        return func(*args)
    except Exception as e:
        log(syslog.LOG_ERR, '%s: %s failed: %s' % (sup.interface, func.__name__, e))
        return None


class Supplicant:
    def __init__(self, entry, debug):
        self.interface = entry['interface']
        self.description = entry.get('description', '')
        self.device = entry['device']
        self.config = entry['config']
        self.debug = debug
        self.proc = None
        self.ctrl = CtrlClient(self.device)
        self.attached_before = False
        # deadlines on the monotonic clock, a wall clock step must not delay recovery
        self.next_start = 0
        self.next_attach = 0
        self.next_reauth = 0
        self.attach_sent = 0
        self.detached_at = None
        self.reauth_pending = None
        self.kicked_at = 0
        self.eap_started = False
        self.retries = 0
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

    def link_state(self):
        """True/False from the media status, None when the device does not report one."""
        out = subprocess.run(['/sbin/ifconfig', self.device], capture_output=True, text=True).stdout
        match = re.search(r'^\s*status: (.+)$', out, re.M)
        return None if match is None else match.group(1).strip() == 'active'

    def start(self):
        # back off before anything can fail, a broken start must not spin
        self.next_start = time.monotonic() + RESTART_DELAY
        if not self.device_exists():
            self.set_state('waiting', 'device %s does not exist' % self.device)
            return
        self.link = self.link_state()
        args = [WPA_SUPPLICANT, '-D', 'wired', '-i', self.device, '-c', self.config]
        if self.debug:
            args.append('-d')
        log(syslog.LOG_NOTICE, '%s: starting supplicant on %s' % (self.interface, self.device))
        self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        os.set_blocking(self.proc.stdout.fileno(), False)
        self.set_state('authenticating' if self.link is not False else 'link down')
        self.kicked()
        # the control socket shows up shortly, check() attaches without blocking the loop
        self.next_attach = 0
        self.detached_at = time.monotonic()

    def kicked(self):
        """An EAPOL-Start went out (start or re-authentication), wait for the exchange."""
        self.kicked_at = time.monotonic()
        self.eap_started = False

    def stop(self, kill=False):
        """kill: for a hung (e.g. stopped) process, which would not act on SIGTERM."""
        self.ctrl.close()
        if self.proc is not None and self.proc.poll() is None:
            if not kill:
                self.proc.terminate()
                try:
                    self.proc.wait(5)
                except subprocess.TimeoutExpired:
                    kill = True
            if kill:
                self.proc.kill()
                self.proc.wait()
        self.proc = None

    def restart(self, reason, kill=False):
        log(syslog.LOG_ERR if kill else syslog.LOG_NOTICE, '%s: restarting supplicant (%s)' % (self.interface, reason))
        self.stop(kill)
        self.start()

    def set_state(self, state, error=None):
        if error is not None:
            self.last_error = error
        # a known link loss outranks results that were still on their way
        if self.link is False and state not in ('link down', 'stopped', 'waiting'):
            return
        self.state = state

    def awaiting_attach(self):
        return self.proc is not None and not self.ctrl.attached

    def attach(self):
        """(Re)connect to the control interface; on_ctrl() takes the reply."""
        try:
            self.ctrl.attach()
        except OSError:
            self.next_attach = time.monotonic() + ATTACH_RETRY
            return
        self.attach_sent = time.monotonic()

    def on_attached(self):
        """Catch up on what was missed while detached."""
        self.detached_at = None
        if self.attached_before:
            log(syslog.LOG_NOTICE, '%s: control interface reattached' % self.interface)
        self.attached_before = True
        try:
            self.sync_status()
        except OSError as e:
            self.lost('status request failed: %s' % e)
            return
        if self.reauth_pending:
            self.reauthenticate(self.reauth_pending)

    def lost(self, reason):
        """The control interface stopped answering, reattach (check() restarts a hung supplicant)."""
        log(syslog.LOG_WARNING, '%s: %s' % (self.interface, reason))
        self.ctrl.close()
        self.next_attach = time.monotonic() + ATTACH_RETRY
        if self.detached_at is None:
            self.detached_at = time.monotonic()

    def sync_status(self):
        """Events sent while detached are lost, take the current EAP state instead."""
        status = parse_status(self.ctrl.command('STATUS', CTRL_TIMEOUT))
        if status.get('EAP state') == 'SUCCESS' and status.get('suppPortStatus') == 'Authorized':
            if self.state != 'authenticated':
                self.set_state('authenticated', '')
                if self.state == 'authenticated':
                    self.authenticated_at = int(time.time())
        elif status.get('EAP state') == 'FAILURE':
            self.set_state('failed', self.last_error or 'authentication rejected (check identity and password)')
        elif self.state == 'authenticated':
            self.set_state('authenticating')

    def reauthenticate(self, reason):
        """Start a new 802.1X exchange; kept pending and retried until it went out.
        Returns '' once it did, else why not (for manual requests).

        REAUTHENTICATE only acts in the AUTHENTICATED PAE state (eapol_sm_request_reauth),
        anywhere else (CONNECTING, AUTHENTICATING, HELD) the supplicant is restarted,
        which begins with an EAPOL-Start."""
        self.reauth_pending = reason
        if not self.ctrl.attached:
            # check() attaches and then sends it
            return 'supplicant control interface not attached, re-authentication queued'
        try:
            pae = parse_status(self.ctrl.command('STATUS', CTRL_TIMEOUT)).get('Supplicant PAE state')
            if pae != 'AUTHENTICATED':
                self.reauth_pending = None
                self.restart('%s, PAE state %s' % (reason, pae or 'not reported'))
                return ''
            accepted = self.ctrl.command('REAUTHENTICATE', CTRL_TIMEOUT).startswith('OK')
        except OSError as e:
            self.lost('re-authentication request failed: %s' % e)
            return 'supplicant not responding (%s), re-authentication queued' % e
        if not accepted:
            self.next_reauth = time.monotonic() + ATTACH_RETRY
            return 'supplicant refused the request, retrying'
        log(syslog.LOG_NOTICE, '%s: re-authenticating (%s)' % (self.interface, reason))
        self.reauth_pending = None
        self.set_state('authenticating')
        self.kicked()
        return ''

    def retry(self, reason):
        """The exchange did not progress in time: unless it actually completed, start over."""
        try:
            self.sync_status()
        except OSError as e:
            self.lost('status request failed: %s' % e)
            return
        if self.state == 'authenticating':
            self.retries += 1
            self.reauthenticate(reason)

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
            # on_attached() may restart the supplicant, which closes the socket
            while self.ctrl.sock is not None:
                msg = self.ctrl.sock.recv(4096).decode(errors='replace')
                if self.ctrl.attached:
                    self.on_event(msg)
                elif msg.startswith('OK'):
                    self.ctrl.attached = True
                    self.on_attached()
                else:
                    raise OSError('ATTACH refused')
        except BlockingIOError:
            pass
        except OSError as e:
            self.lost('control interface lost: %s' % e)

    def on_event(self, msg):
        match = CTRL_EVENT.match(msg)
        if not match:
            return
        event, args = match.groups()
        self.last_event = event
        if event == 'CTRL-EVENT-EAP-STARTED':
            self.eap_started = True
            self.set_state('authenticating')
        elif event == 'CTRL-EVENT-EAP-SUCCESS':
            self.retries = 0
            self.set_state('authenticated', '')
            if self.state == 'authenticated':
                self.authenticated_at = int(time.time())
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

    def on_link(self, up):
        if up and self.link is False:
            self.link = True
            self.retries = 0
            self.set_state('authenticating')
            self.reauthenticate('link up')
        elif not up and self.link is not False:
            self.link = False
            log(syslog.LOG_NOTICE, '%s: link down' % self.interface)
            self.set_state('link down')
        elif up:
            self.link = True

    def check(self, now):
        """Restart an exited supplicant, reattach a lost control interface, retry a
        pending re-authentication (now: monotonic)."""
        if self.proc is not None and self.proc.poll() is not None:
            self.on_output()
            log(syslog.LOG_ERR, '%s: supplicant exited with %d' % (self.interface, self.proc.returncode))
            self.ctrl.close()
            self.proc = None
            self.set_state('stopped', 'supplicant exited unexpectedly')
            self.next_start = now + RESTART_DELAY
        if self.proc is None:
            if now >= self.next_start:
                self.start()
        elif not self.ctrl.attached:
            if now - self.detached_at >= HUNG_TIMEOUT:
                self.restart('not responding for %ds' % HUNG_TIMEOUT, kill=True)
            elif self.ctrl.sock is None:
                if now >= self.next_attach:
                    self.attach()
            elif now - self.attach_sent >= ATTACH_TIMEOUT:
                self.ctrl.close()
                self.next_attach = now + ATTACH_RETRY
        elif self.reauth_pending and now >= self.next_reauth:
            self.reauthenticate(self.reauth_pending)
        elif self.state == 'authenticating' and self.link is not False:
            scale = min(2 ** self.retries, EAP_TIMEOUT_SCALE)
            if not self.eap_started and now - self.kicked_at >= EAP_START_TIMEOUT * scale:
                self.retry('no answer to EAPOL-Start')
            elif now - self.kicked_at >= EAP_RESULT_TIMEOUT * scale:
                self.retry('EAP exchange stalled')

    def status(self):
        return {
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


class Daemon:
    def __init__(self, index):
        debug = index.get('debug', False)
        self.supplicants = {s['device']: Supplicant(s, debug) for s in index.get('supplicants', [])}
        self.monitor = None
        self.control = None
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
            if sup is not None:
                guarded(sup, sup.on_link, oper == 'UP')

    def start_control(self):
        if os.path.exists(DAEMON_SOCK):
            os.unlink(DAEMON_SOCK)
        self.control = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.control.bind(DAEMON_SOCK)
        os.chmod(DAEMON_SOCK, 0o600)
        self.control.setblocking(False)

    def on_control(self):
        """'REAUTHENTICATE <interface>' from ctl.py, answered with OK or 'failed: <reason>'."""
        try:
            data, addr = self.control.recvfrom(4096)
        except BlockingIOError:
            return
        cmd, _sep, interface = data.decode(errors='replace').strip().partition(' ')
        sup = next((s for s in self.supplicants.values() if s.interface == interface), None)
        if cmd != 'REAUTHENTICATE':
            reply = 'unknown command'
        elif sup is None:
            reply = 'unknown interface'
        elif sup.link is False:
            reply = 'failed: link is down, authentication starts when it comes back'
        else:
            sup.retries = 0
            error = guarded(sup, sup.reauthenticate, 'requested')
            reply = 'OK' if error == '' else 'failed: %s' % (error or 'internal error, see the log')
        if addr:
            try:
                self.control.sendto(reply.encode(), addr)
            except OSError:
                pass  # the client gave up waiting

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
        try:
            self.start_monitor()
            self.start_control()
            for sup in self.supplicants.values():
                guarded(sup, sup.start)
            self.loop()
        finally:
            # never leave supplicants behind: a restarted daemon would race them for the device
            for sup in self.supplicants.values():
                guarded(sup, sup.stop)
            if self.monitor is not None:
                self.monitor.terminate()
            if self.control is not None:
                self.control.close()
                os.unlink(DAEMON_SOCK)
            if os.path.exists(STATUS_FILE):
                os.unlink(STATUS_FILE)

    def loop(self):
        while self.running:
            fds = {self.monitor.stdout: None, self.control: None}
            for sup in self.supplicants.values():
                for fd in sup.fds():
                    fds[fd] = sup
            # poll briefly while a freshly started supplicant has no control interface yet
            timeout = 0.2 if any(s.awaiting_attach() for s in self.supplicants.values()) else 2
            try:
                readable, _, _ = select.select(list(fds), [], [], timeout)
            except InterruptedError:
                continue
            for fd in readable:
                sup = fds[fd]
                if fd is self.control:
                    self.on_control()
                elif sup is None:
                    self.on_monitor()
                elif sup.proc is not None and fd is sup.proc.stdout:
                    guarded(sup, sup.on_output)
                else:
                    guarded(sup, sup.on_ctrl)
            if self.monitor.poll() is not None:
                self.start_monitor()
            now = time.monotonic()
            for sup in self.supplicants.values():
                guarded(sup, sup.check, now)
            self.write_status()


def main():
    syslog.openlog('wan8021x', syslog.LOG_PID, syslog.LOG_DAEMON)
    os.makedirs(CTRL_DIR, mode=0o700, exist_ok=True)
    try:
        with open(INDEX_FILE) as f:
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
