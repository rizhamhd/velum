import os
import sys

from PySide6.QtWidgets import QApplication

from velum.gui.window import Window
from velum.notifications.tray import Tray


def main():
    if os.geteuid() == 0:
        print('Do not run the GUI as root. The packaged helper handles authorization.', file=sys.stderr)
        return 1
    app = QApplication(sys.argv)
    app.setApplicationName('Velum')
    app.setDesktopFileName('org.velum.Velum')
    window = Window()
    window.tray = Tray(window)
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
