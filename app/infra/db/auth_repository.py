from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.infra.db.client import RedDatabaseClient


@dataclass(frozen=True)
class ConsumeCodeResult:
    ok: bool
    reason: str = ""  # текст причины, если ok=False

class AuthRepository:
    def __init__(self, db: RedDatabaseClient, *, invite_salt: str) -> None:
        self.db = db
        self.invite_salt = invite_salt

    # ---------- utils ----------

    def hash_code(self, code: str) -> str:
        """
        Хэш, который должен совпадать с CODE_HASH в AUTH_INVITE_CODES.
        Храним hex sha256(code + ":" + salt)
        """
        raw = f"{code}:{self.invite_salt}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    # ---------- users ----------

    def is_user_active(self, telegram_id: int) -> bool:
        row = self.db.fetchone(
            "SELECT STATUS FROM AUTH_USERS WHERE TELEGRAM_ID = ?",
            (telegram_id,),
        )
        return bool(row) and (str(row[0]).strip().lower() == "active")

    def upsert_user_active(self, telegram_id: int, display_name: Optional[str] = None) -> None:
        """
        Делает пользователя active:
        - если есть: обновит status и display_name
        - если нет: вставит
        """
        with self.db.transaction() as con:
            cur = con.cursor()

            cur.execute("SELECT ID FROM AUTH_USERS WHERE TELEGRAM_ID = ?", [telegram_id])
            row = cur.fetchone()

            if row:
                cur.execute(
                    "UPDATE AUTH_USERS SET STATUS = 'active', DISPLAY_NAME = ? WHERE TELEGRAM_ID = ?",
                    [display_name, telegram_id],
                )
            else:
                # ID задаётся триггером (как ты делал для AUTH_USERS)
                cur.execute(
                    "INSERT INTO AUTH_USERS (TELEGRAM_ID, STATUS, ROLE, DISPLAY_NAME) VALUES (?, 'active', 'user', ?)",
                    [telegram_id, display_name],
                )

    # ---------- sessions ----------

    def upsert_session(self, telegram_id: int, ttl_minutes: int) -> None:
        """
        Одна сессия на пользователя (PK = TELEGRAM_ID).
        """
        with self.db.transaction() as con:
            cur = con.cursor()

            # UPDATE
            cur.execute(
                "UPDATE AUTH_SESSIONS "
                "SET AUTHORIZED_AT = CURRENT_TIMESTAMP, "
                "    EXPIRES_AT = DATEADD(? MINUTE TO CURRENT_TIMESTAMP) "
                "WHERE TELEGRAM_ID = ?",
                [ttl_minutes, telegram_id],
            )

            # INSERT if not exists
            cur.execute(
                "INSERT INTO AUTH_SESSIONS (TELEGRAM_ID, AUTHORIZED_AT, EXPIRES_AT) "
                "SELECT ?, CURRENT_TIMESTAMP, DATEADD(? MINUTE TO CURRENT_TIMESTAMP) "
                "FROM RDB$DATABASE "
                "WHERE NOT EXISTS (SELECT 1 FROM AUTH_SESSIONS WHERE TELEGRAM_ID = ?)",
                [telegram_id, ttl_minutes, telegram_id],
            )

    def is_session_valid(self, telegram_id: int) -> bool:
        row = self.db.fetchone(
            "SELECT 1 FROM AUTH_SESSIONS "
            "WHERE TELEGRAM_ID = ? AND (EXPIRES_AT IS NULL OR EXPIRES_AT > CURRENT_TIMESTAMP)",
            (telegram_id,),
        )
        return bool(row)

    # ---------- invite codes ----------
    def create_invite_code(
            self,
            *,
            code_hash: str,
            status: str = "active",
            max_uses: int = 1,
            created_by: Optional[int] = None,
            ttl_minutes: Optional[int] = None,
        ) -> None:
            with self.db.transaction() as con:
                cur = con.cursor()

                if ttl_minutes is None:
                    cur.execute(
                        "INSERT INTO AUTH_INVITE_CODES (CODE_HASH, STATUS, MAX_USES, USES, CREATED_BY) "
                        "VALUES (?, ?, ?, 0, ?)",
                        [code_hash, status, max_uses, created_by],
                    )
                else:
                    cur.execute(
                        "INSERT INTO AUTH_INVITE_CODES (CODE_HASH, STATUS, MAX_USES, USES, CREATED_BY, EXPIRES_AT) "
                        "VALUES (?, ?, ?, 0, ?, DATEADD(? MINUTE TO CURRENT_TIMESTAMP))",
                        [code_hash, status, max_uses, created_by, ttl_minutes],
                    )
    def consume_invite_code(self, telegram_id: int, code_plain: str) -> ConsumeCodeResult:
        """
        Атомарно "поглощает" invite code:
        - находит по CODE_HASH
        - проверяет status/expiry/лимиты
        - увеличивает USES
        - выставляет USED_BY/USED_AT
        - переводит status в 'used' если достигнут max_uses
        """
        code_hash = self.hash_code(code_plain)

        with self.db.transaction() as con:
            cur = con.cursor()

            # В Firebird "WITH LOCK" — самый простой способ блокировки строки.
            cur.execute(
                "SELECT ID, STATUS, EXPIRES_AT, MAX_USES, USES "
                "FROM AUTH_INVITE_CODES "
                "WHERE CODE_HASH = ? "
                "WITH LOCK",
                [code_hash],
            )
            row = cur.fetchone()
            if not row:
                return ConsumeCodeResult(False, "code_not_found")

            invite_id, status, expires_at, max_uses, uses = row
            status_s = str(status).strip().lower()

            if status_s in {"revoked"}:
                return ConsumeCodeResult(False, "code_revoked")
            if status_s in {"used"}:
                return ConsumeCodeResult(False, "code_used")
            if status_s in {"expired"}:
                return ConsumeCodeResult(False, "code_expired")

            if expires_at is not None:
                # expires_at приходит как datetime
                if isinstance(expires_at, datetime):
                    if expires_at <= datetime.now(expires_at.tzinfo) if expires_at.tzinfo else expires_at <= datetime.now():
                        # можно обновить статус на expired, но необязательно
                        cur.execute(
                            "UPDATE AUTH_INVITE_CODES SET STATUS='expired' WHERE ID=?",
                            [invite_id],
                        )
                        return ConsumeCodeResult(False, "code_expired")

            uses_i = int(uses)
            max_uses_i = int(max_uses)
            if uses_i >= max_uses_i:
                cur.execute("UPDATE AUTH_INVITE_CODES SET STATUS='used' WHERE ID=?", [invite_id])
                return ConsumeCodeResult(False, "code_used")

            new_uses = uses_i + 1
            new_status = "used" if new_uses >= max_uses_i else "active"

            cur.execute(
                "UPDATE AUTH_INVITE_CODES "
                "SET USES = ?, STATUS = ?, USED_BY = ?, USED_AT = CURRENT_TIMESTAMP "
                "WHERE ID = ?",
                [new_uses, new_status, telegram_id, invite_id],
            )

        return ConsumeCodeResult(True, "ok")