"""Project-local SQLite runtime adapter for canonical conversation storage.

Only the canonical conversation store uses APSW. Existing rebuildable SQLite
projections continue using Python's stdlib ``sqlite3`` module and therefore do
not open the same database file through two SQLite libraries.
"""

from __future__ import annotations

import sqlite3 as _dbapi_errors
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import apsw

DRIVER_NAME = "apsw"
sqlite_version = apsw.sqlitelibversion()
sqlite_version_info = tuple(int(part) for part in sqlite_version.split(".")[:3])

# Keep the storage boundary's existing DB-API-shaped exception contract while
# retaining the APSW exception as ``__cause__`` for diagnostics.
Error = _dbapi_errors.Error
DatabaseError = _dbapi_errors.DatabaseError
IntegrityError = _dbapi_errors.IntegrityError
OperationalError = _dbapi_errors.OperationalError


class Row(Mapping[str, Any]):
    """Small sqlite3.Row-compatible view over one APSW result row."""

    def __init__(self, names: Sequence[str], values: Sequence[Any]) -> None:
        self._names = tuple(str(name) for name in names)
        self._values = tuple(values)
        self._positions = {name: index for index, name in enumerate(self._names)}

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._positions[key]]

    def __iter__(self) -> Iterator[str]:
        return iter(self._names)

    def __len__(self) -> int:
        return len(self._values)


class Cursor:
    """Expose the fetch helpers used by the conversation repository."""

    def __init__(self, cursor: apsw.Cursor) -> None:
        self._cursor = cursor
        try:
            description = cursor.get_description()
        except apsw.ExecutionCompleteError:
            description = ()
        self._names = tuple(str(column[0]) for column in description)

    def fetchone(self) -> Row | None:
        try:
            values = next(self._cursor)
        except StopIteration:
            return None
        except apsw.Error as exc:
            raise _translated_error(exc) from exc
        return Row(self._names, values)

    def fetchall(self) -> list[Row]:
        try:
            return [Row(self._names, values) for values in self._cursor]
        except apsw.Error as exc:
            raise _translated_error(exc) from exc

    def __iter__(self) -> Iterator[Row]:
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row


class Connection:
    """Minimal DB-API-shaped wrapper around the bundled APSW connection."""

    def __init__(
        self,
        database: str,
        *,
        timeout: float = 5,
        uri: bool = False,
    ) -> None:
        flags = apsw.SQLITE_OPEN_READWRITE | apsw.SQLITE_OPEN_CREATE
        if uri:
            flags = apsw.SQLITE_OPEN_READONLY | apsw.SQLITE_OPEN_URI
        try:
            self._connection = apsw.Connection(database, flags=flags)
            self._connection.set_busy_timeout(max(1, int(float(timeout) * 1000)))
        except apsw.Error as exc:
            raise _translated_error(exc) from exc
        self._row_factory: type[Row] = Row

    @property
    def row_factory(self) -> type[Row]:
        return self._row_factory

    @row_factory.setter
    def row_factory(self, factory: type[Row]) -> None:
        if factory is not Row:
            raise TypeError("The conversation SQLite runtime only supports Row results.")
        self._row_factory = factory

    def execute(
        self,
        sql: str,
        parameters: Sequence[Any] | Mapping[str, Any] = (),
    ) -> Cursor:
        try:
            return Cursor(self._connection.execute(sql, parameters))
        except apsw.Error as exc:
            raise _translated_error(exc) from exc

    def commit(self) -> None:
        self.execute("COMMIT")

    def rollback(self) -> None:
        self.execute("ROLLBACK")

    def close(self) -> None:
        try:
            self._connection.close()
        except apsw.Error as exc:
            raise _translated_error(exc) from exc


def connect(
    database: str,
    *,
    timeout: float = 5,
    isolation_level: None = None,
    uri: bool = False,
) -> Connection:
    """Open one bundled-SQLite connection with explicit transaction control."""

    if isolation_level is not None:
        raise ValueError("Conversation SQLite requires explicit transactions.")
    return Connection(database, timeout=timeout, uri=uri)


def _translated_error(exc: apsw.Error) -> Error:
    if isinstance(exc, apsw.ConstraintError):
        return IntegrityError(str(exc))
    if isinstance(exc, (apsw.BusyError, apsw.LockedError, apsw.ReadOnlyError)):
        return OperationalError(str(exc))
    return DatabaseError(str(exc))
