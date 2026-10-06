# Publishing a Velum update

1. Bump `pkgrel` (or `pkgver`) in PKGBUILD and keep `velum/version.py` in sync.
   Update the changelog and documented package filename.
2. Run `scripts/check.sh` and the relevant isolated/live acceptance checks from
   TESTING.md. Keep unverified release gates explicit.
3. Build with `makepkg --force --noconfirm`. Commit the tested code and tag the
   exact commit `vMAJOR.MINOR.PATCH-PKGREL`; push the commit/tag.
4. Create a source archive of that commit with `git archive --format=tar.gz`,
   prefix `velum-MAJOR.MINOR.PATCH-PKGREL/`, and filename
   `velum-MAJOR.MINOR.PATCH-PKGREL-installer.tar.gz`.
5. Publish that archive, the matching `velum-vpn-…-any.pkg.tar.zst`, and a
   `SHA256SUMS` file generated with `sha256sum` using their basenames. The updater
   expects exactly those installer and checksum asset names. Do not include
   profiles, runtime journals, credentials, or untracked files.
   Also export `install.sh` from the tagged commit as `velum-install.sh`, include
   its checksum, and attach it to every release. The README's version-free
   installation command depends on this exact asset name.
6. Create a GitHub release against that exact tag/commit and mark it Latest only
   after all assets are attached. The updater reads the latest published release;
   drafts and GitHub prereleases are not update candidates. This remains a 0.1
   development series; publishing a release does not certify production safety.
7. Check `velum-update --check` and download/verify the published bundle. Never
   change a published tag or silently replace a published release's files; issue
   a new package release instead.
   Download the published `velum-install.sh` and run `bash velum-install.sh --check`
   to verify the first-time install path without changing the host.

SHA-256 checksums are integrity checks, not cryptographic release signatures.
Keep previous releases available so users can read their notes and obtain their
original downloads. See the [GitHub release API documentation](https://docs.github.com/en/rest/releases/releases#get-the-latest-release).
