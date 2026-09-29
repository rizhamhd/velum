# Architecture

Velum separates untrusted imported data, profile persistence, Xray generation,
network transactions, verification, and the Qt view. The privileged helper takes
only bounded JSON requests over a private pipe from its authorized caller. It
owns network resources for a single session. The UI never infers protection from
process existence: only the full verification result can enter CONNECTED.

Initial compatibility target: Xray plus xjasonlyu/tun2socks; systemd-resolved's
stub resolver (including NetworkManager delegating to resolved). Other resolver
managers are detected and refused rather than modifying /etc/resolv.conf.
IPv6 is blocked during this release's sessions; native IPv6 tunneling is deferred.

Routes use a private policy table. Physical defaults stay intact. A pinned server
route and an Xray socket mark bypass the tunnel. nftables resources are isolated.
Every mutation has a compensating operation recorded before execution.
