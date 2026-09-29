# Troubleshooting

## Service or authorization unavailable

```sh
systemctl status velum.socket velum.service
journalctl -u velum.service -b --no-pager
pkaction --action-id org.velum.manage --verbose
```

Install the package and enable `velum.socket`. On KDE ensure a Polkit agent is
running. Do not run the GUI as root or loosen the Polkit policy. Only one GUI owns
a session; close stale GUI instances. Helper code comes from the installed
package, not the development checkout.

## Xray started but routing failed

```sh
ip -d link show vpn0
ip -4 rule show
ip -4 route show table 28672
ip -4 route get 1.1.1.1
ip -4 route show table main
sudo nft list table inet velum_vpn
```

Expected: vpn0 UP, table 28672 default via vpn0, priorities 10998/10999/11000.
The physical default remaining in main is intentional. A rule/table collision or
another policy VPN is rejected. Do not delete another application's resources.

For the pinned provider IPv4, substitute its address locally (not credentials):

```sh
ip -4 route get PROVIDER_IPV4 mark 0x5650
```

It should use the physical upstream. A provider host-route collision is rejected
instead of overwritten. Automatic recovery uses the pinned IP; explicitly
reconnect if the provider changed DNS.

## DNS configuration failed

```sh
readlink -f /etc/resolv.conf
resolvectl status
resolvectl status vpn0
resolvectl query example.com
nmcli general status
```

Both regular NetworkManager-generated files and symlinks are supported when
127.0.0.53 is the sole nameserver and the resolved stub is reachable. External
resolvers, mixed resolver lists, and unreachable stub listeners are refused.
Configure resolved according to distro documentation first. No automatic resolver
migration is attempted. Do not replace resolv.conf merely to silence an error.

## TLS or connectivity fails

Check provider address/port, SNI, validity of the subscription, ALPN, system clock,
and whether the provider supports the imported transport. Unknown `flow`, REALITY,
XHTTP, and gRPC options are intentionally rejected. Never enable allowInsecure to
work around certificate errors. The generated configuration always validates
certificates. Raw Xray output is suppressed to avoid logging credentials; the GUI
cannot always distinguish a remote TLS failure from a dropped transport.

```sh
timedatectl status
xray version
tun2socks -version
curl -q --noproxy '*' -4 --max-time 10 https://api.ipify.org
curl -q --noproxy '*' -4 --max-time 10 https://checkip.amazonaws.com
```

Two HTTPS observations must agree. If services are unavailable or a provider uses
rotating egress per destination, verification can fail conservatively. Do not
claim CONNECTED by bypassing these checks. Before/after equality fails by default.

## IPv6

```sh
sudo nft list table inet velum_vpn
curl -q --noproxy '*' -6 --max-time 5 https://api64.ipify.org
```

The IPv6 request should fail while connected. IPv6-only provider endpoints cannot
connect in this release. The app does not permanently disable IPv6 via sysctl.

## Hotspot clients cannot reach the VPN

```sh
nmcli -f NAME,UUID,TYPE,DEVICE connection show --active
ip -4 route show table 28672
sudo nft list table inet velum_vpn
sysctl net.ipv4.conf.vpn0.forwarding
```

Also inspect `net.ipv4.conf.HOTSPOT_INTERFACE.forwarding` using the actual interface.
Verify the NM connection uses `ipv4.method=shared`, the interface differs from the
upstream, and the phone has a valid IPv4 lease. Third-party forward-chain drops can
block sharing. Velum does not override these rules. Compare the phone's public IP
with the laptop's VPN IP; laptop diagnostics alone do not certify a phone.

## Stale resources / failed cleanup

First try **Disconnect**. If necessary, explicitly restore normal networking:

```sh
sudo /usr/lib/velum/recover
sudo systemctl start velum.socket
```

The recovery wrapper stops the service before replaying only its root-owned
journals. A failed cleanup leaves the firewall rather than reporting success.
Do not `nft flush ruleset`, replace defaults, remove another VPN's interface, or
manually delete journals. A reboot clears transient Velum kernel state; it should
not be needed for ordinary disconnects.

## Reporting a bug

Attach copied diagnostics and sanitized structured logs, core versions, resolver
manager, and distro/kernel version. Remove personal public IPs if desired. Never
paste a real VLESS link, UUID, exported profile, or runtime xray.json in a public
issue. Include whether the isolated integration suite passes and which live
acceptance step failed.
