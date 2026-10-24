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

function wan8021x_enabled()
{
    return (new \OPNsense\Wan8021x\Wan8021x())->isActive();
}

/*
 * The port must be authorized before DHCP on the interface can succeed, so
 * start right after the interfaces are configured at boot. dhclient keeps
 * retrying in the meantime and picks up a lease once the port opens.
 */
function wan8021x_configure()
{
    return [
        'early' => ['wan8021x_configure_do'],
        /* runs after every interface_configure(); assignments applied from the GUI are
         * saved only afterwards, rc.syshook.d/config/50-wan8021x catches up on those */
        'dhcp' => ['wan8021x_configure_devices'],
    ];
}

/*
 * Follow interface reassignments (WAN moved to another NIC or VLAN): restart
 * only when the interface -> device mapping differs from what is running, as
 * this hook also fires on every link up.
 */
function wan8021x_configure_devices($verbose = false)
{
    /* only follow a running service; starting and stopping belong to the service itself */
    $wanted = (new \OPNsense\Wan8021x\Wan8021x())->activeDevices();
    if (empty($wanted) || !isvalidpid('/var/run/wan8021x.pid')) {
        return;
    }

    $running = [];
    $index = json_decode(@file_get_contents('/var/etc/wan8021x/supplicants.json') ?: '[]', true);
    foreach ($index['supplicants'] ?? [] as $entry) {
        $running[$entry['interface']] = $entry['device'];
    }
    ksort($running);

    /* devices that do not resolve are not started, compare like with like */
    if (array_filter($wanted) == $running) {
        return;
    }

    service_log('Restarting WAN 802.1X supplicant for changed interfaces...', $verbose);
    mwexecf('/usr/local/etc/rc.d/wan8021x restart');
    service_log("done.\n", $verbose);
}

function wan8021x_configure_do($verbose = false)
{
    if (!wan8021x_enabled()) {
        return;
    }

    service_log('Starting WAN 802.1X supplicant...', $verbose);
    mwexecf('/usr/local/etc/rc.d/wan8021x restart');
    service_log("done.\n", $verbose);
}

/* Must match the program name the daemon logs under, and the Syslog/local filter. */
function wan8021x_syslog()
{
    return ['wan8021x' => ['facility' => ['wan8021x']]];
}

function wan8021x_services()
{
    $services = [];

    if (!wan8021x_enabled()) {
        return $services;
    }

    $services[] = [
        'description' => gettext('WAN 802.1X supplicant'),
        'name' => 'wan8021x',
        'pidfile' => '/var/run/wan8021x.pid',
        'configd' => [
            'restart' => ['wan8021x restart'],
            'start' => ['wan8021x start'],
            'stop' => ['wan8021x stop'],
        ],
    ];

    return $services;
}
