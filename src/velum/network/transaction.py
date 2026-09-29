"""Write-ahead rollback journal. This file must live in a root-owned 0700 directory."""
import json
from pathlib import Path

from velum.security.files import private_write


class Transaction:
    def __init__(self, runner, path: Path):
        self.runner = runner
        self.path = path
        self.undo = json.loads(path.read_text())['undo'] if path.exists() else []

    def apply(self, command, undo, input=None):
        self.undo.append(list(undo))
        private_write(self.path, {'undo': self.undo})
        self.runner.run(*command, input=input)

    def rollback(self):
        failures = []
        for command in reversed(self.undo):
            try:
                self.runner.run(*command)
            except Exception:
                failures.append(command)
        self.undo = list(reversed(failures))
        if failures:
            private_write(self.path, {'undo': self.undo})
            raise RuntimeError('Network cleanup incomplete; recovery journal retained')
        self.path.unlink(missing_ok=True)
