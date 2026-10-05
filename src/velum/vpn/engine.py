import subprocess
from pathlib import Path
from typing import Protocol

from velum.security.files import private_write
from velum.vpn.configuration import generate_config, generate_sing_box_config


class Backend(Protocol):
    def start(self): ...
    def stop(self): ...
    def status(self) -> bool: ...
    def validate_config(self, profile, server_ip=None): ...


class Xray:
    name = 'Xray'
    program = 'xray'
    def __init__(self, directory: Path, binary='/usr/bin/xray'):
        self.directory = directory
        self.binary = binary
        self.process = None
        self.logfile = None
        self.config = directory / 'xray.json'

    def version(self):
        return subprocess.run([self.binary, 'version'], capture_output=True,
                              text=True, check=True, timeout=5).stdout.splitlines()[0]

    def generate_config(self, profile, server_ip=None):
        return generate_config(profile, server_ip)

    def check_command(self):
        return [self.binary, 'run', '-test', '-config', str(self.config)]

    def run_command(self):
        return [self.binary, 'run', '-config', str(self.config)]

    def validate_config(self, profile, server_ip=None):
        private_write(self.config, self.generate_config(profile, server_ip))
        result = subprocess.run(self.check_command(),
                                capture_output=True, text=True, timeout=15)
        if result.returncode:
            # Engines may echo arbitrary authentication data in parser errors.
            raise RuntimeError(f'{self.name} rejected this profile configuration. '
                               'Check its protocol/transport options and installed engine version.')

    def start(self):
        if self.status():
            raise RuntimeError(f'{self.name} is already running')
        # Do not retain raw engine logs: server responses can include credentials.
        self.process = subprocess.Popen(self.run_command(),
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process = None
        self.config.unlink(missing_ok=True)

    def restart(self):
        if self.process and self.status():
            self.process.terminate()
            self.process.wait(timeout=5)
        self.start()

    def status(self):
        return self.process is not None and self.process.poll() is None

    def get_logs(self):
        return 'Raw engine output is suppressed to protect credentials; see structured diagnostics.'


class SingBox(Xray):
    name = 'sing-box'
    program = 'sing-box'

    def __init__(self, directory: Path, binary='/usr/bin/sing-box'):
        super().__init__(directory, binary)
        self.config = directory / 'sing-box.json'

    def generate_config(self, profile, server_ip=None):
        return generate_sing_box_config(profile, server_ip)

    def check_command(self):
        return [self.binary, 'check', '-c', str(self.config)]

    def run_command(self):
        return [self.binary, 'run', '-c', str(self.config)]


def engine_for(profile, directory):
    return (SingBox if profile.allow_insecure else Xray)(directory)
