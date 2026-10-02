import json
import os
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from velum.config.profiles import ProfileStore
from velum.config.vless import ConfigurationError, parse_vless, with_certificate_name
from velum.security.files import private_write
from velum.security.logging import event
from velum.security.redact import redact
from velum.services.client import Client
from velum.vpn.configuration import generate_config


class ProfileDialog(QDialog):
    def __init__(self, parent, item=None):
        super().__init__(parent)
        self.setWindowTitle('VPN profile')
        self.resize(620, 180)
        layout = QFormLayout(self)
        self.name = QLineEdit(item['name'] if item else '')
        self.uri = QLineEdit(item['uri'] if item else '')
        self.uri.setEchoMode(QLineEdit.Password)
        self.uri.setPlaceholderText('vless://UUID@server:port?...')
        reveal = QCheckBox('Reveal sensitive URL')
        reveal.toggled.connect(lambda checked: self.uri.setEchoMode(
            QLineEdit.Normal if checked else QLineEdit.Password))
        layout.addRow('Name (optional)', self.name)
        layout.addRow('VLESS URL', self.uri)
        layout.addRow(reveal)
        self.certificate_name = QLineEdit()
        self.certificate_name.setPlaceholderText('Optional: provider’s certificate hostname')
        layout.addRow('Verify certificate for', self.certificate_name)
        self.tls_notice = QLabel('Leave blank to verify against the SNI. Set the provider’s certificate\n'
                                'hostname to keep a different SNI with certificate verification enabled.')
        self.tls_notice.setWordWrap(True)
        layout.addRow(self.tls_notice)
        self.uri.textChanged.connect(self.sync_tls_option)
        self.sync_tls_option()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def sync_tls_option(self):
        try:
            profile = parse_vless(self.uri.text())
        except ConfigurationError:
            self.certificate_name.clear()
            self.certificate_name.setEnabled(False)
        else:
            self.certificate_name.setEnabled(profile.security == 'tls')
            self.certificate_name.setText(profile.certificate_name)

    def profile_uri(self):
        return with_certificate_name(self.uri.text(), self.certificate_name.text())


class Window(QMainWindow):
    def __init__(self, store=None, client=None):
        super().__init__()
        self.setWindowTitle('Velum • VPN Manager')
        self.resize(1060, 740)
        config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'velum'
        self.store = store or ProfileStore(config / 'profiles.json')
        self.preferences_path = self.store.path.with_name('settings.json')
        self.client = client or Client(self)
        self.client.received.connect(self.update_status)
        self.client.failure.connect(self.error)
        self.tray = None
        self.last_status = 'UNKNOWN'
        self.pending_request = None
        self.pending_operation = None
        self.control_buttons = {}
        self.control_actions = {}
        self.last_report = []
        self.records = []
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        home = QWidget()
        layout = QVBoxLayout(home)
        title = QLabel('Velum')
        title.setStyleSheet('font-size: 30px; font-weight: 700;')
        layout.addWidget(title)
        layout.addWidget(QLabel('Full-device VLESS • Your Wi-Fi or Ethernet remains the internet transport'))
        self.summary = QLabel('Checking VPN status…')
        self.summary.setTextFormat(Qt.PlainText)
        self.summary.setStyleSheet('padding: 18px; font-size: 16px;')
        layout.addWidget(self.summary)
        buttons = QHBoxLayout()
        for label, action in [('Connect', self.connect_vpn), ('Disconnect', self.disconnect_vpn),
                              ('Reconnect', self.reconnect), ('Run connection test', self.diagnose)]:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, action=action: action())
            self.control_buttons[label] = button
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.profiles = QTableWidget(0, 8)
        self.profiles.setHorizontalHeaderLabels(['Name', 'Server', 'Port', 'Protocol', 'Transport', 'TLS', 'SNI', 'Certificate name'])
        self.profiles.setSelectionBehavior(QTableWidget.SelectRows)
        self.profiles.setSelectionMode(QTableWidget.SingleSelection)
        self.profiles.itemSelectionChanged.connect(self.update_controls)
        self.profiles.setEditTriggers(QTableWidget.NoEditTriggers)
        self.profiles.setContextMenuPolicy(Qt.CustomContextMenu)
        self.profiles.customContextMenuRequested.connect(self.context_menu)
        self.profiles.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.profiles.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.profiles.setAlternatingRowColors(True)
        self.profiles.verticalHeader().hide()
        layout.addWidget(self.profiles)
        actions = QHBoxLayout()
        for label, action in [('Add / Import VLESS', self.add_profile), ('Edit', self.edit_profile),
                              ('Import file', self.import_file), ('Export', self.export_profile)]:
            button = QPushButton(label)
            button.clicked.connect(action)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.tabs.addTab(home, 'Profiles')
        diag = QWidget()
        dlayout = QVBoxLayout(diag)
        self.diagnostics = QTextEdit()
        self.diagnostics.setReadOnly(True)
        dlayout.addWidget(self.diagnostics)
        for title, action in [('Run Full Test', self.diagnose), ('Copy Diagnostic Report', self.copy_report)]:
            button = QPushButton(title)
            button.clicked.connect(action)
            if title == 'Run Full Test':
                self.control_buttons[title] = button
            dlayout.addWidget(button)
        self.tabs.addTab(diag, 'Diagnostics')
        logs_page = QWidget()
        logs_layout = QVBoxLayout(logs_page)
        self.logs = QTextEdit()
        self.logs.setReadOnly(True)
        logs_layout.addWidget(self.logs)
        for title, action in [('Copy logs', lambda: QApplication.clipboard().setText(self.logs.toPlainText())),
                              ('Save logs', self.save_logs), ('Clear logs', self.logs.clear)]:
            button = QPushButton(title)
            button.clicked.connect(action)
            logs_layout.addWidget(button)
        self.tabs.addTab(logs_page, 'Logs')
        settings = QWidget()
        form = QFormLayout(settings)
        self.kill = QComboBox()
        self.kill.addItems(['VPN only', 'VPN + hotspot', 'OFF'])
        self.expect_change = QCheckBox('Require public IP to change')
        self.expect_change.setChecked(True)
        self.expect_change.setToolTip(
            'Checks your public IP before connecting, which can use regular ISP data. '
            'Turn off for connections with only an app-specific data package. '
            'Tunnel routing and internet connectivity are still verified.')
        self.ipv6 = QComboBox()
        self.ipv6.addItem('Block IPv6 temporarily (safe default)', 'block')
        self.ipv6.addItem('Tunnel IPv6 (not supported in this release)', 'tunnel')
        form.addRow('Kill switch', self.kill)
        form.addRow('IPv6', self.ipv6)
        form.addRow(self.expect_change)
        package_help = QLabel('Uses regular data for a public-IP check before connecting.\n'
                              'Turn off to check internet access only after the VPN starts.\n'
                              'Velum cannot verify which ISP data allowance is charged.')
        package_help.setWordWrap(True)
        form.addRow(package_help)
        form.addRow(QLabel('Settings apply on the next connection.\nLocal LAN bypass is disabled in this release.'))
        self.tabs.addTab(settings, 'Settings')
        hotspot = QWidget()
        hform = QFormLayout(hotspot)
        self.share = QCheckBox('Share VPN with an existing NetworkManager hotspot')
        self.hotspot_interface = QLineEdit()
        self.hotspot_interface.setPlaceholderText('Existing hotspot interface, e.g. wlp3s0')
        self.hotspot_status = QLabel('NOT ENABLED')
        hform.addRow(self.share)
        hform.addRow('Hotspot interface', self.hotspot_interface)
        hform.addRow(self.hotspot_status)
        hform.addRow(QLabel('Create the hotspot in KDE Network Settings first.\nSharing never disables the upstream connection.'))
        self.tabs.addTab(hotspot, 'Hotspot')
        self.load_preferences()
        self.expect_change.toggled.connect(self.save_preferences)
        self.reload()
        self.tray = None
        self.update_controls()

    def load_preferences(self):
        try:
            if self.preferences_path.exists():
                data = json.loads(self.preferences_path.read_text())
                if (not isinstance(data, dict) or data.get('version') != 1
                        or not isinstance(data.get('expect_change'), bool)):
                    raise ValueError('Invalid public-IP check preference')
                self.expect_change.setChecked(data['expect_change'])
        except (OSError, ValueError) as exc:
            self.error('Cannot read saved settings: ' + str(exc))

    def save_preferences(self):
        try:
            private_write(self.preferences_path, {'version': 1,
                          'expect_change': self.expect_change.isChecked()})
        except OSError as exc:
            self.error('Cannot save settings: ' + str(exc))

    def reload(self):
        try:
            self.records = self.store.list()
        except Exception as exc:
            self.error('Cannot read saved profiles: ' + str(exc))
            return
        self.profiles.setRowCount(len(self.records))
        for row, item in enumerate(self.records):
            p = parse_vless(item['uri'])
            for col, value in enumerate([item['name'], p.server, p.port, 'VLESS', p.transport,
                                          p.security, p.sni, p.certificate_name or 'Same as SNI/server']):
                self.profiles.setItem(row, col, QTableWidgetItem(str(value)))
        if self.records:
            self.profiles.selectRow(0)

    def selected(self):
        row = self.profiles.currentRow()
        return self.records[row] if 0 <= row < len(self.records) else None

    def edit(self, item=None):
        dialog = ProfileDialog(self, item)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.store.save(dialog.profile_uri(), dialog.name.text() or None,
                                item['id'] if item else None)
                self.reload()
            except Exception as exc:
                self.error(str(exc))

    def add_profile(self):
        self.edit()

    def edit_profile(self):
        if item := self.selected():
            self.edit(item)

    def duplicate(self):
        if item := self.selected():
            self.store.duplicate(item['id'])
            self.reload()

    def rename(self):
        if item := self.selected():
            name, ok = QInputDialog.getText(self, 'Rename VPN', 'Name', text=item['name'])
            if ok:
                try:
                    self.store.save(item['uri'], name, item['id'])
                    self.reload()
                except Exception as exc:
                    self.error(str(exc))

    def delete(self):
        if item := self.selected():
            if QMessageBox.question(self, 'Delete profile?', 'Delete this saved VPN profile?') == QMessageBox.Yes:
                self.store.delete(item['id'])
                self.reload()

    def copy_url(self):
        if item := self.selected():
            if QMessageBox.question(self, 'Copy credentials?',
                    'The URL contains account credentials. Desktop clipboard history may retain it. Copy?') == QMessageBox.Yes:
                QApplication.clipboard().setText(item['uri'])

    def export_profile(self):
        if item := self.selected():
            path, _ = QFileDialog.getSaveFileName(self, 'Export sensitive profile', 'vpn-profile.json', 'JSON (*.json)')
            if path:
                try:
                    self.store.export(item['id'], path)
                except Exception as exc:
                    self.error(str(exc))

    def export_xray(self):
        if item := self.selected():
            path, _ = QFileDialog.getSaveFileName(self, 'Export sensitive Xray configuration', 'xray.json', 'JSON (*.json)')
            if path:
                try:
                    private_write(Path(path), generate_config(parse_vless(item['uri'])))
                except Exception as exc:
                    self.error(str(exc))

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import profiles', '', 'JSON (*.json)')
        if path:
            try:
                self.store.import_file(path)
                self.reload()
            except Exception as exc:
                self.error(str(exc))

    def context_menu(self, position):
        menu = QMenu(self)
        for label, action in [('Connect', self.connect_vpn), ('Edit', self.edit_profile),
                              ('Rename', self.rename), ('Duplicate', self.duplicate),
                              ('Share / Copy URL', self.copy_url), ('Export profile', self.export_profile),
                              ('Export Xray JSON', self.export_xray),
                              ('Delete', self.delete)]:
            menu.addAction(label, action)
        menu.exec(self.profiles.viewport().mapToGlobal(position))

    def connect_vpn(self, reconnect=False):
        allowed = ('CONNECTED', 'ERROR') if reconnect else ('DISCONNECTED',)
        if self.pending_request or self.last_status not in allowed:
            return
        if item := self.selected():
            self.send_operation('reconnect' if reconnect else 'connect', uri=item['uri'], settings={
                'kill_switch': self.kill.currentText(), 'ipv6': self.ipv6.currentData(),
                'expect_change': self.expect_change.isChecked(),
                'hotspot': self.hotspot_interface.text().strip() if self.share.isChecked() else ''})

    def reconnect(self):
        self.connect_vpn(True)

    def disconnect_vpn(self):
        if not self.pending_request and self.last_status not in ('DISCONNECTED', 'UNKNOWN'):
            self.send_operation('disconnect')

    def diagnose(self):
        self.tabs.setCurrentIndex(1)
        if not self.pending_request:
            self.send_operation('status' if self.last_status == 'UNKNOWN' else 'diagnostics')

    def refresh_status(self):
        if not self.pending_request:
            self.send_operation('status')

    def send_operation(self, operation, **data):
        self.pending_request = uuid4().hex
        self.pending_operation = operation
        self.update_controls()
        self.statusBar().showMessage({
            'connect': 'Connecting…', 'disconnect': 'Disconnecting…',
            'reconnect': 'Reconnecting…', 'status': 'Checking VPN status…',
            'diagnostics': 'Testing connection…',
        }[operation])
        self.client.send(operation, request_id=self.pending_request, **data)

    def update_controls(self):
        idle = self.pending_request is None
        selected = self.selected() is not None
        enabled = {
            'Connect': idle and selected and self.last_status == 'DISCONNECTED',
            'Disconnect': idle and self.last_status not in ('DISCONNECTED', 'UNKNOWN'),
            'Reconnect': idle and selected and self.last_status in ('CONNECTED', 'ERROR'),
            'Run connection test': idle,
            'Run Full Test': idle,
        }
        for label, control in [*self.control_buttons.items(), *self.control_actions.items()]:
            control.setEnabled(enabled[label])

    def closeEvent(self, event):
        self.client.close()
        super().closeEvent(event)

    def copy_report(self):
        QApplication.clipboard().setText(redact(json.dumps(self.last_report, indent=2)))

    def save_logs(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save redacted logs', 'velum-log.txt')
        if path:
            Path(path).write_text(redact(self.logs.toPlainText()))

    def update_status(self, data):
        if data.get('control_denied'):
            self.error(data.get('error', 'Helper access denied'))
            return
        completed = self.pending_request and data.get('request_complete') == self.pending_request
        if completed:
            if self.pending_operation == 'status' and data.get('profile_key'):
                for row, item in enumerate(self.records):
                    if sha256(item['uri'].strip().encode()).hexdigest() == data['profile_key']:
                        self.profiles.selectRow(row)
                        break
                else:
                    self.profiles.setCurrentCell(-1, -1)
                    self.profiles.clearSelection()
                settings = data.get('settings', {})
                self.kill.setCurrentText(settings.get('kill_switch', 'VPN only'))
                self.expect_change.setChecked(settings.get('expect_change', True))
                self.share.setChecked(bool(settings.get('hotspot')))
                self.hotspot_interface.setText(settings.get('hotspot', ''))
            self.pending_request = None
            self.pending_operation = None
            self.statusBar().clearMessage()
        state = data.get('state', self.last_status)
        self.last_status = state
        self.update_controls()
        self.summary.setText(f"{state}\nInternet: {data.get('upstream', '—')}\n"
                             f"Original IP: {data.get('original_ip') or 'Not measured'}\n"
                             f"VPN IP: {data.get('vpn_ip', '—')}\n"
                             f"Tunnel: {data.get('tunnel', '—')}\n"
                             f"Latency: {data.get('latency_ms', '—')} ms\n"
                             f"Core: {data.get('engine_version', 'Not inspected')}")
        if 'checks' in data:
            self.last_report = data['checks']
            self.diagnostics.setPlainText('\n'.join(
                f"{c['status']:12} {c['name']}: {c['detail']}" for c in self.last_report))
        self.hotspot_status.setText(data.get('hotspot', 'NOT ENABLED'))
        self.logs.insertPlainText(event('ERROR' if data.get('error') else 'INFO', data.get('error', state), state=state) + '\n')
        if self.tray:
            self.tray.update(state, data.get('error', ''))
        if data.get('error'):
            self.statusBar().showMessage(redact(data['error']))

    def error(self, message):
        self.last_status = 'UNKNOWN'
        self.pending_request = None
        self.pending_operation = None
        self.update_controls()
        self.summary.setText('ERROR — protection is not verified\n' + redact(message))
        self.logs.insertPlainText(event('ERROR', message) + '\n')
        self.statusBar().showMessage(redact(message))
        if self.tray:
            self.tray.update('ERROR', redact(message))
