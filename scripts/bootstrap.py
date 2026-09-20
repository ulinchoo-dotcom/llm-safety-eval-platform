"""Create local config without printing or overwriting credentials."""

import secrets
from pathlib import Path

path = Path(".env")
if path.exists():
    print("Existing .env retained.")
else:
    with path.open("x") as target:
        target.write(
            "DATABASE_URL=postgresql://safety:safety_local_dev@127.0.0.1:55432/safety_eval\n"
        )
        target.write("API_TOKEN=" + secrets.token_urlsafe(36) + "\n")
    path.chmod(0o600)
    print("Created local .env. Token is not printed; file is excluded from Git.")
