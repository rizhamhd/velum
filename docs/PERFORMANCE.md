# CPU use and laptop temperatures

## Wi-Fi loss fix in 0.1.0-14

The reported sequence was: connect VPN, disable Wi-Fi, leave the laptop idle,
then return to high CPU use and severe gaming slowdown. An isolated kernel route
test reproduced a matching defect: after the upstream routes disappeared, a
marked VPN provider connection selected vpn0 instead of becoming unreachable.
That could feed engine connections back through tun2socks recursively.

The tunnel rule now excludes engine-marked packets even when their main-table
lookup fails. The helper stops both engines on loss or failed recovery, keeps
the protection firewall, and waits between retries. It also rejects down upstream
interfaces and clears stale egress results. Real-engine namespace tests remove
upstream routes, check that marked sockets have no route, test that application
traffic cannot escape, restore routes and verify tunnel traffic again.

This fixes the reproduced routing defect without relying on a CPU cap. The
original gaming/100°C condition has not been reproduced, so no particular
temperature or FPS improvement is claimed. The CPU budget below remains as a
second limit on helper/engine resource consumption.

## Changes in 0.1.0-13

- Rate-limit monitoring to at most one pass every two seconds even when GUI/IPC
  requests arrive continuously. Process, upstream, and route checks keep this cadence.
- Check resolved and firewall integrity every 15 seconds instead of every two
  seconds. Full verification still runs on connect, after detected resume, about
  once per minute, and when the user requests it. The installed firewall continues
  enforcing protection between checks.
- Measure the idle interval from the end of each check. A slow HTTPS check must
  not be mistaken for suspend/resume and trigger continuous full verification.
- Bound the helper and its child engines together to one CPU worth of scheduled
  time (`CPUQuota=100%`). This means one logical CPU, not 100% of the whole laptop.
  The 20 ms quota period limits throttle pauses compared with the 100 ms default.
- Set Go engine parallelism to two (`GOMAXPROCS=2`), including older tun2socks
  runtimes which otherwise size their scheduler for all host CPUs.
- Retain only the latest 2,000 GUI log blocks to bound long-running UI growth.

The CPU budget can reduce peak throughput and increase latency when saturated.
It does not limit games, GPU work, or all kernel networking work, and cannot promise
any particular laptop temperature. It changes no fan curves, CPU boost settings,
power profiles or TLS checks.

## Evidence and remaining investigation

At inspection the connected laptop reported a CPU package temperature near 59°C;
Xray and tun2socks showed low CPU use. The reported approximately 100°C gaming
condition was not reproduced. These changes address confirmed excess background
work and add a workload budget. The later Wi-Fi-loss investigation above identified
a concrete routing defect, but the original thermal event was not measured.

Regression tests exercise 6,000 calls during a simulated minute and permit only
30 route/upstream passes and four protection audits. Separate tests cover slow
probes, real resume, and route failure between protection audits. No thermal stress
workload is necessary to run these unit tests.

## Capture the actual workload

From the checkout, run this while reproducing your normal game or download:

```sh
python scripts/performance-report.py --seconds 15
```

This read-only report samples process CPU deltas, service CPU consumption, quota
throttling, and available temperature sensors. It prints process names, never
command lines, IP addresses, or profile credentials. It creates no traffic or CPU
stress of its own. Compare the same workload with the VPN connected and, if you
choose to disconnect it, disconnected. Idle temperature alone is not a useful
before/after comparison with a running game.

Inspect the actual applied service settings:

```sh
systemctl show velum.service -p CPUQuotaPerSecUSec -p CPUQuotaPeriodUSec -p CPUWeight
cat /sys/fs/cgroup/system.slice/velum.service/cpu.max
sensors
```

The packaged quota should appear as `20000 20000` in cpu.max. Administrator
service overrides can change it. New monitor/Go settings load when the helper
restarts; a runtime quota change can take effect on an existing session without
restarting it. A helper restart disconnects the VPN, so reconnect afterward.

Reference: [systemd CPU resource controls](https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html).
