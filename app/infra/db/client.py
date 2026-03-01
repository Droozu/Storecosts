from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Optional, Sequence

from firebird.driver import connect


@dataclass(frozen=True)
class RedDatabaseClient:
    host: str
    port: int
    database: str
    user: str
    password: str
    charset: str = "UTF8"


    def _dsn(self) -> str:
        return f"{self.host}/{self.port}:{self.database}"
    

    @contextmanager
    def connect(self):
        con = connect(
            self._dsn(),
            user=self.user,
            password=self.password,
            charset=self.charset,
        )
        try:
            yield con
        finally:
            con.close()

    @contextmanager
    def transaction(self):
        """
        Firebird начинает транзакцию при первом execute.
        Здесь мы гарантируем commit/rollback.
        """
        with self.connect() as con:
            try:
                yield con
                con.commit()
            except Exception:
                con.rollback()
                raise

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Optional[tuple]:
        with self.connect() as con:
            cur = con.cursor()
            cur.execute(sql, list(params))
            return cur.fetchone()

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[tuple]:
        with self.connect() as con:
            cur = con.cursor()
            cur.execute(sql, list(params))
            return cur.fetchall()