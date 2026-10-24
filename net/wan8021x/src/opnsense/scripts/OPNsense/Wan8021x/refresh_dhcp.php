#!/usr/local/bin/php
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

/* Authentication can move the port from a guest subnet to an authorized one.
 * Restart only IPv4 DHCP, forgetting its old lease without cycling the link. */

openlog('wan8021x', LOG_PID, LOG_DAEMON);

function dhcp_refresh_fail(string $message)
{
    syslog(LOG_ERR, 'DHCP refresh: ' . $message);
    exit(1);
}

$interface = $argv[1] ?? '';
$device = $argv[2] ?? '';
if (!preg_match('/^[a-zA-Z0-9_]+$/', $interface) || !preg_match('/^[a-zA-Z0-9_.]+$/', $device)) {
    dhcp_refresh_fail('invalid interface or device');
}

/* The daemon creates this directory. Close-on-exec prevents the DHCP daemon
 * from inheriting the lock after this helper has finished. */
$lock = @fopen("/var/run/wan8021x/dhcp.{$device}.lock", 'ce');
if ($lock === false || !flock($lock, LOCK_EX)) {
    dhcp_refresh_fail('cannot lock device ' . $device);
}

/* Load configuration after taking the lock, since this event may have waited
 * behind another refresh or an interface assignment change. */
require_once 'config.inc';
require_once 'util.inc';
require_once 'interfaces.inc';
openlog('wan8021x', LOG_PID, LOG_DAEMON);

$ifcfg = config_read_array('interfaces', $interface, false);
if (!isset($ifcfg['enable']) || ($ifcfg['ipaddr'] ?? '') !== 'dhcp' || ($ifcfg['if'] ?? '') !== $device) {
    exit(0);
}
$details = legacy_interfaces_details($device);
if (!isset($details[$device])) {
    exit(0);
}

/* This PID belongs to core's restarting supervisor. Killing only dhclient
 * would let it respawn while the lease and address are being cleared. */
$pidfile = "/var/run/dhclient.{$device}.pid";
killbypid($pidfile);

$leasefile = "/var/db/dhclient.leases.{$device}";
if (file_exists($leasefile) && !unlink($leasefile)) {
    dhcp_refresh_fail('cannot remove the old lease on ' . $device);
}

/* Exclude configured IP aliases and CARP addresses. The first remaining IPv4
 * address is the dynamic primary; leave all other addresses and IPv6 intact. */
foreach (interfaces_addresses($interface) as $address) {
    if (
        $address['family'] !== 'inet' || $address['name'] !== $device || $address['alias'] ||
        is_linklocal($address['address']) || $address['address'] === ($ifcfg['alias-address'] ?? '')
    ) {
        continue;
    }
    if (mwexecf('/sbin/ifconfig %s inet %s -alias', [$device, $address['address']]) !== 0) {
        dhcp_refresh_fail('cannot remove the old address on ' . $device);
    }
    break;
}

if (mwexecf('/usr/local/sbin/ifctl -4c -i %s', $device) !== 0) {
    dhcp_refresh_fail('cannot clear dynamic IPv4 state on ' . $device);
}

/* Reuse core's generated options, PID locking and process supervision. Its
 * normal BOUND event updates DNS, routes and services when the new lease arrives. */
interface_dhcp_configure($interface);
if (!waitforpid($pidfile, 3)) {
    dhcp_refresh_fail('DHCP supervisor did not start on ' . $device);
}
syslog(LOG_NOTICE, "{$interface}: restarted IPv4 DHCP after authentication on {$device}");
flock($lock, LOCK_UN);
fclose($lock);
