"""Tests for agent.ec2_wake.is_vm_asleep: the read-only, never-wakes guard
that agent.usage_limits relies on to answer a poll with vm_unreachable
instead of starting a stopped EC2 instance. Every other test in this repo
patches is_vm_asleep out, so it needs direct coverage of its own."""

import unittest
from unittest.mock import MagicMock, patch

from storage.dto.vm import VmConfig

from agent import ec2_wake


class IsVmAsleepTest(unittest.TestCase):
    def test_falsy_ec2_config_is_not_asleep(self):
        """A non-EC2 VM (no ec2_instance_id/ec2_region, e.g. local dev)
        doesn't apply to this guard at all, and must never touch boto3."""
        vm_config = VmConfig(ec2_instance_id="", ec2_region="")
        with patch("agent.ec2_wake.boto3.client") as client:
            self.assertFalse(ec2_wake.is_vm_asleep(vm_config))
        client.assert_not_called()

    def test_running_instance_is_not_asleep(self):
        vm_config = VmConfig(ec2_instance_id="i-123", ec2_region="us-east-1")
        ec2 = MagicMock()
        ec2.describe_instance_status.return_value = {
            "InstanceStatuses": [{"InstanceState": {"Name": "running"}}]
        }
        with patch("agent.ec2_wake.boto3.client", return_value=ec2):
            self.assertFalse(ec2_wake.is_vm_asleep(vm_config))
        ec2.start_instances.assert_not_called()
        ec2.get_waiter.assert_not_called()

    def test_stopped_instance_is_asleep(self):
        vm_config = VmConfig(ec2_instance_id="i-123", ec2_region="us-east-1")
        ec2 = MagicMock()
        ec2.describe_instance_status.return_value = {
            "InstanceStatuses": [{"InstanceState": {"Name": "stopped"}}]
        }
        with patch("agent.ec2_wake.boto3.client", return_value=ec2):
            self.assertTrue(ec2_wake.is_vm_asleep(vm_config))
        # The never-wake guarantee, pinned in the unit that owns it: a bare
        # MagicMock absorbs a stray start_instances/get_waiter call silently,
        # so these two assertions are what actually catches a regression
        # that turns this read-only check into a wake.
        ec2.start_instances.assert_not_called()
        ec2.get_waiter.assert_not_called()

    def test_empty_instance_statuses_is_treated_as_asleep(self):
        """A fail-safe: if EC2 can't even report a status for the instance,
        never assume it's safe to SSH (and thus never risk a wake)."""
        vm_config = VmConfig(ec2_instance_id="i-123", ec2_region="us-east-1")
        ec2 = MagicMock()
        ec2.describe_instance_status.return_value = {"InstanceStatuses": []}
        with patch("agent.ec2_wake.boto3.client", return_value=ec2):
            self.assertEqual(ec2_wake.get_instance_state("i-123", "us-east-1"), "unknown")
            self.assertTrue(ec2_wake.is_vm_asleep(vm_config))
        ec2.start_instances.assert_not_called()
        ec2.get_waiter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
