import os
import sys

from PySide6.QtWidgets import QApplication

from velum.gui.window import Window


def main():
    if os.geteuid() == 0:
        print('Do not run the GUI as root. The packaged helper handles authorization.', file=sys.stderr)
        return 1
    app = QApplication(sys.argv)
    app.setApplicationName('Velum')
    app.setDesktopFileName('org.velum.Velum')
    window = Window()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
