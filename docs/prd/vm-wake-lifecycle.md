# VM wake and hibernation

Runtime work renews `vm_config.last_active_at` on the execution node and its
default SSH anchor. The nullable epoch timestamp is independent of `last_up`
(SSH readiness); a missing activity timestamp does not protect a node.
Configuration updates and no-wake usage refreshes do not renew activity.

Every five minutes the worker considers Linux endpoints with one unambiguous
EC2 identity. An endpoint must match an AWS-described address on port 22, or
the operator-managed instance tag `y-agent:ssh-endpoint` (`host:port`). A
non-EC2 alias on its own owner's EC2 anchor shares the anchor wake path.
An alias with no wake path, conflicting identity, unsupported platform,
unknown activity or failed probe prevents a stop.

The worker requires 900 seconds of inactivity, no running SQL chat or DynamoDB
process on the target or through the anchor, and no other established SSH
session. It locks the physical instance, probes without waking, and rechecks
registry and activity before requesting hibernation. A launch touches activity
before checking the same lock and waits through an in-flight stop. EC2 must
reach `stopped` before starting; a jump node must accept SSH through its anchor
before launch. Never substitute a normal stop for hibernation.

The sweep checks enrolled Linux jump instances before their anchors. It keeps
an anchor up if any dependent cannot be confirmed stopped; a dry run uses
the same order without changing power state. If an anchor is already asleep,
the sweep never wakes it for a probe. It can use an existing direct `default`
registration of the same endpoint; otherwise it retries after the next normal
anchor wake. A failed probe never authorizes hibernation.

## Rollout and acceptance

1. Have the maintainer apply `migration/4407_vm_idle_stop.sql` before the new
   ORM runs. Grant the worker describe access and `ec2:StopInstances` only for
   the enrolled instance ARNs. Confirm wake principals can start those nodes.
2. Require `HibernationOptions.Configured=true` and guest swap/resume configured
   for the actual memory size. Verify `/swap` is active after boot and the
   runtime Ed25519 identity can log in. As maintainer set both `--ec2-instance-id` and
   `--ec2-region` on EC2 jump nodes. Read the existing row first: `node add`
   also writes platform, namespace and work directory. For the current tenant59
   registration, check the values before and after enrollment:

   ```sh
   y node show tenant59
   y node add tenant59 --host 10.2.1.152 --port 22 --user ec2-user \
     --platform linux --namespace tenant-base --work-dir /home/ec2-user \
     --ec2-instance-id i-07540a3a6724eacac --ec2-region us-east-1
   y node show tenant59
   ```

   If the existing SSH address, platform, namespace or work directory differs,
   use its current values instead. Only the two EC2 fields should change.
3. Invoke `idle_stop_nodes` with `"dry_run":true` and inspect decisions.
   No stop or wake is issued in dry run. Retire the node-local timer and cron
   entry before the sweep runs. `IdleStopNodesEnabled` defaults to `ENABLED`,
   matching the already-live rule, so the next deploy does not turn it off.
   Pass `DISABLED` only to pause the schedule.
4. In a quiescent window, verify EC2 reaches `stopped`, a chat wakes the same
   boot (unchanged Linux boot ID), and SSH and launch are ready in under 600s.
   Do not exercise this check against an active control host.
