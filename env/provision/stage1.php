<?php

/*
 * Golden image, stage 1 (run over the serial console):
 * LAN on the QEMU user network, ssh with key-only root login, no wizard.
 * Usage: php stage1.php <authorized_key>
 */

require_once 'config.inc';

use OPNsense\Core\Config;

$cfg = Config::getInstance();
$o = $cfg->object();

unset($o->trigger_initial_wizard);
$o->system->hostname = 'opnsense';
$o->system->domain = 'wan8021x.test';

$o->interfaces->lan->ipaddr = '10.0.2.15';
$o->interfaces->lan->subnet = '24';
unset($o->interfaces->lan->ipaddrv6);
unset($o->interfaces->lan->subnetv6);
unset($o->interfaces->lan->track6_interface);
unset($o->interfaces->lan->{'track6-interface'});
unset($o->interfaces->lan->{'track6-prefix-id'});
$o->interfaces->wan->ipaddrv6 = 'none';
/* the test WAN uses RFC1918 addressing */
unset($o->interfaces->wan->blockpriv);
unset($o->interfaces->wan->blockbogons);

$o->system->ssh->enabled = 'enabled';
$o->system->ssh->permitrootlogin = '1';
foreach ($o->system->user as $user) {
    if ((string)$user->name == 'root') {
        $user->authorizedkeys = base64_encode($argv[1] . "\n");
    }
}

$cfg->save();
echo "stage1 done\n";
