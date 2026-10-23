<?php

/*
 * Golden image, stage 2 (run over ssh): create an API key for root and
 * print it as JSON.
 */

require_once 'config.inc';

use OPNsense\Auth\User;
use OPNsense\Core\Config;

Config::getInstance()->lock();
$mdl = new User();
$user = $mdl->getUserByName('root');
if ($user == null) {
    exit(1);
}
$key = $user->apikeys->add();
$mdl->serializeToConfig(false, true);
Config::getInstance()->save();
echo json_encode($key) . "\n";
