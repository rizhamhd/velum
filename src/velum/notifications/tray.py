from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


class Tray:
    def __init__(self, window):
        self.window = window
        self.last = None
        self.last_notice = None
        self.icon = QSystemTrayIcon(window)
        menu = QMenu(window)
        window.control_actions['Connect'] = menu.addAction('Connect', window.connect_vpn)
        window.control_actions['Disconnect'] = menu.addAction('Disconnect', window.disconnect_vpn)
        self.profiles = menu.addMenu('Profiles')
        self.profiles.aboutToShow.connect(self.refresh_profiles)
        window.control_actions['Reconnect'] = menu.addAction('Reconnect', window.reconnect)
        menu.addAction('Diagnostics', self.diagnostics)
        menu.addAction('Open', self.open)
        menu.addSeparator()
        menu.addAction('Quit app (keep VPN running)', self.quit)
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(lambda reason: self.open()
                                   if reason == QSystemTrayIcon.Trigger else None)
        self.update(window.last_status)
        window.update_controls()
        self.icon.show()

    def refresh_profiles(self):
        self.profiles.clear()
        for index, record in enumerate(self.window.records):
            self.profiles.addAction(record['name'], lambda i=index: self.select(i))

    def select(self, index):
        self.window.profiles.selectRow(index)
        self.open()

    def open(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def diagnostics(self):
        self.open()
        self.window.diagnose()

    def quit(self):
        self.window.client.close()
        QApplication.quit()

    def update(self, state, error=''):
        color = {'CONNECTED': '#42c994', 'DISCONNECTED': '#8494a7', 'ERROR': '#ed6877'}.get(state, '#efbf61')
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor('transparent'))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(QColor(color))
        painter.drawEllipse(4, 4, 24, 24)
        painter.end()
        self.icon.setIcon(QIcon(pixmap))
        self.icon.setToolTip('Velum: ' + state)
        key = (state, error)
        if state in ('CONNECTED', 'DISCONNECTED', 'ERROR') and key != self.last_notice:
            previous = self.last_notice
            self.last_notice = key
            if previous is None:
                self.last = key
                return
            self.icon.showMessage('Velum', error or {
                'CONNECTED': 'VPN connected successfully; routing verified',
                'DISCONNECTED': 'VPN disconnected', 'ERROR': 'VPN tunnel lost; check diagnostics',
            }[state], QSystemTrayIcon.Warning if error else QSystemTrayIcon.Information)
        self.last = key
