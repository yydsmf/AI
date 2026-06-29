import os
import sys


def _default_factory_app_dir():
    if sys.platform.startswith("win"):
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if root:
            return os.path.join(root, "GPTLocalToolboxFactory")
    return os.path.join(os.path.expanduser("~"), ".gpt_desktop_app_factory")


factory_app_dir = os.environ.get("GPT_DESKTOP_FACTORY_APP_DIR") or _default_factory_app_dir()
os.environ.setdefault("GPT_DESKTOP_APP_DIR", factory_app_dir)

from gpt_desktop.app import main


if __name__ == "__main__":
    main()
