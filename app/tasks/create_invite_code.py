from __future__ import annotations

import argparse

from app.setting import Settings
from app.infra.db.client import RedDatabaseClient
from app.infra.db.auth_repository import AuthRepository
from app.infra.auth.otp import OTPService


def main() -> None:
    settings = Settings()
    dsn = f"{settings.rdb_host}/{settings.rdb_port}:{settings.rdb_database}"

    parser = argparse.ArgumentParser(description="Create invite code in AUTH_INVITE_CODES")
    parser.add_argument("--max-uses", type=int, default=1, help="How many times the code can be used")
    parser.add_argument("--ttl", type=int, default=None, help="TTL in minutes (optional)")
    parser.add_argument("--created-by", type=int, default=None, help="Telegram ID of admin (optional)")
    args = parser.parse_args()


    db = RedDatabaseClient(
        host=settings.rdb_host,
        port=settings.rdb_port,
        database=settings.rdb_database,
        user=settings.rdb_user,
        password=settings.rdb_password,
        charset=settings.rdb_charset,
    )
    repo = AuthRepository(db, invite_salt=settings.invite_salt)
    otp = OTPService(repo)

    invite = otp.create_invite_code(
        created_by=args.created_by,
        max_uses=args.max_uses,
        ttl_minutes=args.ttl,
    )

    print("Invite code created:")
    print(f"CODE: {invite.code}")
    print(f"MAX_USES: {invite.max_uses}")
    print(f"TTL_MINUTES: {invite.ttl_minutes}")
    # hash печатать не обязательно, но иногда полезно:
    # print(f"HASH: {invite.code_hash}")


if __name__ == "__main__":
    main()