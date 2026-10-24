"""DHCP refreshes follow authorization without blocking the supplicant supervisor."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "net/wan8021x/src/opnsense/scripts/OPNsense/Wan8021x"))
import wan8021xd as daemon  # noqa: E402


class DhcpRefreshTest(unittest.TestCase):
    def setUp(self):
        logging = patch.object(daemon, "log")
        logging.start()
        self.addCleanup(logging.stop)
        self.sup = daemon.Supplicant({"interface": "wan", "device": "vtnet1", "config": "unused"}, False)
        self.sup.link = True
        self.job = MagicMock()
        self.job.poll.return_value = None
        spawning = patch.object(daemon.subprocess, "Popen", return_value=self.job)
        self.spawn = spawning.start()
        self.addCleanup(spawning.stop)

    def authorize(self):
        self.sup.on_event("<3>CTRL-EVENT-EAP-SUCCESS")

    def test_status_and_success_event_only_queue_one_refresh(self):
        self.sup.ctrl.command = MagicMock(return_value="EAP state=SUCCESS\nsuppPortStatus=Authorized\n")
        self.sup.sync_status()
        self.authorize()
        self.sup.sync_status()
        self.spawn.assert_not_called()
        self.sup.check_dhcp(10)
        self.sup.check_dhcp(11)
        self.spawn.assert_called_once()
        self.job.poll.return_value = 0
        self.sup.check_dhcp(12)
        self.authorize()
        self.sup.check_dhcp(13)
        self.spawn.assert_called_once()

    def test_periodic_reauthentication_preserves_the_lease(self):
        self.authorize()
        self.sup.check_dhcp(10)
        self.job.poll.return_value = 0
        self.sup.check_dhcp(11)
        self.sup.on_event("<3>CTRL-EVENT-EAP-STARTED")
        self.authorize()
        self.sup.check_dhcp(100)
        self.assertEqual(self.spawn.call_count, 1)
        self.assertTrue(self.sup.port_authorized)
        self.assertFalse(self.sup.dhcp_pending)

    def test_requested_reauthentication_preserves_authorization(self):
        self.authorize()
        self.sup.check_dhcp(10)
        self.job.poll.return_value = 0
        self.sup.check_dhcp(11)
        self.sup.ctrl.attached = True
        self.sup.ctrl.command = MagicMock(side_effect=lambda cmd, _: (
            "Supplicant PAE state=AUTHENTICATED\n" if cmd == "STATUS" else "OK\n"))
        self.assertEqual(self.sup.reauthenticate("requested"), "")
        self.sup.on_event("<3>CTRL-EVENT-EAP-STARTED")
        self.authorize()
        self.sup.check_dhcp(100)
        self.assertEqual(self.spawn.call_count, 1)
        self.assertFalse(self.sup.dhcp_pending)

    def test_failure_recovery_refreshes_after_cooldown(self):
        self.authorize()
        self.sup.check_dhcp(10)
        self.job.poll.return_value = 0
        self.sup.check_dhcp(11)
        self.sup.on_event("<3>CTRL-EVENT-EAP-FAILURE")
        self.assertFalse(self.sup.port_authorized)
        self.authorize()
        self.sup.check_dhcp(12)
        self.assertEqual(self.spawn.call_count, 1)
        self.assertTrue(self.sup.dhcp_pending)
        self.sup.check_dhcp(10 + daemon.DHCP_INTERVAL)
        self.assertEqual(self.spawn.call_count, 2)

    def test_status_catches_up_on_a_missed_authorization_loss(self):
        self.authorize()
        self.sup.check_dhcp(10)
        self.job.poll.return_value = 0
        self.sup.check_dhcp(11)
        self.sup.ctrl.command = MagicMock(return_value="EAP state=IDLE\nsuppPortStatus=Unauthorized\n")
        self.sup.sync_status()
        self.assertFalse(self.sup.port_authorized)
        self.sup.ctrl.command.return_value = "EAP state=SUCCESS\nsuppPortStatus=Authorized\n"
        self.sup.sync_status()
        self.sup.check_dhcp(10 + daemon.DHCP_INTERVAL)
        self.assertEqual(self.spawn.call_count, 2)

    def test_missing_status_fields_do_not_invent_an_authorization_loss(self):
        self.authorize()
        self.sup.check_dhcp(10)
        self.job.poll.return_value = 0
        self.sup.check_dhcp(11)
        self.sup.ctrl.command = MagicMock(return_value="")
        self.sup.sync_status()
        self.assertTrue(self.sup.port_authorized)
        self.authorize()
        self.sup.check_dhcp(100)
        self.assertEqual(self.spawn.call_count, 1)

    def test_link_flaps_coalesce_without_resetting_the_cooldown(self):
        self.authorize()
        self.sup.check_dhcp(10)
        self.job.poll.return_value = 0
        self.sup.check_dhcp(11)
        self.sup.reauthenticate = MagicMock(return_value="")
        for now in (12, 20, 30):
            self.sup.on_link(False)
            self.assertFalse(self.sup.port_authorized)
            self.sup.on_link(True)
            self.authorize()
            self.sup.check_dhcp(now)
        self.assertEqual(self.spawn.call_count, 1)
        self.assertTrue(self.sup.dhcp_pending)
        self.sup.check_dhcp(10 + daemon.DHCP_INTERVAL)
        self.assertEqual(self.spawn.call_count, 2)
        self.sup.check_dhcp(100)
        self.assertEqual(self.spawn.call_count, 2)

    def test_late_success_while_link_down_does_not_refresh(self):
        self.sup.on_link(False)
        self.authorize()
        self.sup.check_dhcp(10)
        self.assertEqual(self.sup.state, "link down")
        self.assertIsNone(self.sup.authenticated_at)
        self.assertFalse(self.sup.dhcp_pending)
        self.assertFalse(self.sup.port_authorized)
        self.spawn.assert_not_called()

    def test_refresh_waits_for_authorization_and_link(self):
        self.authorize()
        self.sup.state = "authenticating"
        self.sup.check_dhcp(10)
        self.sup.state = "authenticated"
        self.sup.link = False
        self.sup.check_dhcp(11)
        self.spawn.assert_not_called()
        self.assertTrue(self.sup.dhcp_pending)
        self.sup.link = True
        self.sup.check_dhcp(12)
        self.spawn.assert_called_once()

    def test_running_refresh_does_not_block_or_start_a_second_helper(self):
        self.authorize()
        self.sup.check_dhcp(10)
        self.sup.check_dhcp(11)
        self.spawn.assert_called_once_with([daemon.DHCP_REFRESH, "wan", "vtnet1"],
                                           stdin=daemon.subprocess.DEVNULL, stdout=daemon.subprocess.DEVNULL,
                                           stderr=daemon.subprocess.DEVNULL)
        self.job.wait.assert_not_called()

    def test_authentication_during_a_refresh_is_not_lost(self):
        self.authorize()
        self.sup.check_dhcp(10)
        self.sup.on_event("<3>CTRL-EVENT-DISCONNECTED")
        self.sup.on_event("<3>CTRL-EVENT-EAP-STARTED")
        self.authorize()
        self.sup.check_dhcp(11)
        self.assertEqual(self.spawn.call_count, 1)
        self.job.poll.return_value = 0
        self.sup.check_dhcp(12)
        self.assertTrue(self.sup.dhcp_pending)
        self.assertEqual(self.spawn.call_count, 1)
        self.sup.check_dhcp(10 + daemon.DHCP_INTERVAL)
        self.assertEqual(self.spawn.call_count, 2)
        self.assertFalse(self.sup.dhcp_pending)

    def test_failed_helper_retries_without_changing_authentication(self):
        self.authorize()
        self.sup.check_dhcp(10)
        self.job.poll.return_value = 1
        self.sup.check_dhcp(11)
        self.assertEqual(self.sup.state, "authenticated")
        self.assertTrue(self.sup.dhcp_pending)
        self.sup.check_dhcp(11 + daemon.RESTART_DELAY - 1)
        self.assertEqual(self.spawn.call_count, 1)
        self.sup.check_dhcp(10 + daemon.DHCP_INTERVAL - 1)
        self.assertEqual(self.spawn.call_count, 1)
        self.sup.check_dhcp(10 + daemon.DHCP_INTERVAL)
        self.assertEqual(self.spawn.call_count, 2)

    def test_failed_spawn_backs_off_and_keeps_the_request(self):
        self.spawn.side_effect = OSError("temporarily unavailable")
        self.authorize()
        self.sup.check_dhcp(10)
        self.sup.check_dhcp(10 + daemon.RESTART_DELAY - 1)
        self.assertEqual(self.spawn.call_count, 1)
        self.assertTrue(self.sup.dhcp_pending)
        self.spawn.side_effect = None
        self.sup.check_dhcp(10 + daemon.RESTART_DELAY)
        self.assertEqual(self.spawn.call_count, 2)

    def test_hung_helper_is_reaped_and_retried(self):
        self.authorize()
        self.sup.check_dhcp(10)
        deadline = 10 + daemon.DHCP_TIMEOUT
        self.sup.check_dhcp(deadline)
        self.job.terminate.assert_called_once()
        self.job.wait.assert_called_once_with(2)
        self.assertIsNone(self.sup.dhcp_proc)
        self.assertTrue(self.sup.dhcp_pending)
        self.assertEqual(self.sup.state, "authenticated")
        self.sup.check_dhcp(deadline + daemon.RESTART_DELAY)
        self.assertEqual(self.spawn.call_count, 2)

    def test_shutdown_allows_a_refresh_to_finish(self):
        self.authorize()
        self.sup.check_dhcp(10)
        with patch.object(daemon.time, "monotonic", return_value=11):
            self.sup.stop_dhcp()
        self.job.terminate.assert_not_called()
        self.job.wait.assert_called_once_with(daemon.DHCP_TIMEOUT - 1)
        self.assertIsNone(self.sup.dhcp_proc)

    def test_supplicant_restart_keeps_an_inflight_dhcp_refresh(self):
        self.authorize()
        self.sup.check_dhcp(10)
        self.sup.stop()
        self.assertIs(self.sup.dhcp_proc, self.job)
        self.job.terminate.assert_not_called()
        self.job.wait.assert_not_called()

    def test_shutdown_reaps_a_helper_that_does_not_finish(self):
        self.authorize()
        self.sup.check_dhcp(10)
        self.job.wait.side_effect = [daemon.subprocess.TimeoutExpired("refresh", daemon.DHCP_TIMEOUT), None]
        with patch.object(daemon.time, "monotonic", return_value=11):
            self.sup.stop_dhcp()
        self.job.terminate.assert_called_once()
        expected = [unittest.mock.call(daemon.DHCP_TIMEOUT - 1), unittest.mock.call(2)]
        self.assertEqual(self.job.wait.call_args_list, expected)
        self.assertIsNone(self.sup.dhcp_proc)


if __name__ == "__main__":
    unittest.main()
