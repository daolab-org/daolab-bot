import os
import sys

# Prefer certifi's CA bundle on platforms where system CAs may be missing (e.g., macOS python.org builds)
try:  # pragma: no cover - environment hardening only
    import certifi  # type: ignore

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except Exception:
    pass

# Ensure project root is on sys.path when executed as a script (python app/main.py)
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def main() -> None:
    from app.bot import create_bot
    from app.settings import settings

    bot = create_bot()
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
