from fromthecraft.__main__ import main


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import logging
        import sys

        logging.exception("Application failed to start")
        if getattr(sys, "frozen", False) and sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, f"{exc}\nSee fromthecraft.log in the application folder.", "FromTheCraft", 0x10
            )
        else:
            raise
