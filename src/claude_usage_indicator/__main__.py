import sys


def main():
    if "--install" in sys.argv:
        from .install import install
        install()
    elif "--uninstall" in sys.argv:
        from .install import uninstall
        uninstall()
    else:
        from .tray import main as tray_main
        tray_main()


if __name__ == "__main__":
    main()
