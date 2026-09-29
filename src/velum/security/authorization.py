import socket
import struct
import subprocess
from pathlib import Path


def peer_identity(connection):
    pid, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    # comm can include spaces and parentheses; fields after its last ')' start at field 3.
    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return pid, uid, fields[19]


def authorize(connection):
    pid, uid, start = peer_identity(connection)
    result = subprocess.run(['/usr/bin/pkcheck', '--action-id', 'org.velum.manage',
                             '--process', f'{pid},{start},{uid}', '--allow-user-interaction'],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=120)
    if result.returncode:
        raise PermissionError('Polkit authorization was denied or no authentication agent is available')
    return uid
