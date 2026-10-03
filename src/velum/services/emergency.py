"""Administrator-only recovery, independent of the running VPN helper."""
import fcntl
import os
import subprocess
import sys


def stop_and_recover(run=subprocess.run):
    def command(*args, check=True, timeout=20):
        return run(list(args), check=check, timeout=timeout, stdin=subprocess.DEVNULL,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                   env={'PATH': '/usr/bin:/usr/sbin', 'LC_ALL': 'C'})

    # Queue a deliberate stop before killing: Restart=on-failure must not restart
    # the helper, and socket activation must stop before journals are recovered.
    command('/usr/bin/systemctl', 'stop', '--no-block', 'velum.socket', 'velum.service')
    command('/usr/bin/systemctl', 'kill', '--kill-whom=all', '--signal=SIGKILL',
            'velum.service', check=False)
    command('/usr/bin/systemctl', 'stop', 'velum.socket', 'velum.service')
    command('/usr/bin/python', '-I', '-m', 'velum.services.helper', '--recover', timeout=120)
    # Only reopen control after successful recovery. No VPN is started here.
    command('/usr/bin/systemctl', 'start', 'velum.socket')


def main():
    if os.geteuid() != 0 or sys.argv[1:]:
        print('Emergency recovery requires administrator access and accepts no arguments.', file=sys.stderr)
        return 1
    os.umask(0o077)
    fd = os.open('/run/velum-emergency.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stop_and_recover()
    except BlockingIOError:
        print('Another Velum emergency recovery is running.', file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError):
        print('Emergency recovery did not complete. Inspect Velum and run sudo /usr/lib/velum/recover.',
              file=sys.stderr)
        return 1
    finally:
        os.close(fd)
    return 0


if __name__ == '__main__':
    sys.exit(main())
