from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from .contracts import EstateKey, OperationalCategory


def normalize_alias(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


@dataclass(frozen=True)
class EstateRecord:
    estate: str
    key: EstateKey
    category: OperationalCategory
    identity_status: str
    source_kind: str
    source_locator: str
    crop_output_directory: str


class EstateRegistry:
    def __init__(self, records: list[EstateRecord], aliases: dict[str, str]) -> None:
        if len(records) != len({record.estate for record in records}):
            raise ValueError("Duplicate canonical estate name")
        if len(records) != len({record.key for record in records}):
            raise ValueError("Duplicate plantation/estate key")
        self._by_name = {record.estate: record for record in records}
        self._by_key = {record.key: record for record in records}
        self._aliases = aliases

    @classmethod
    def load(cls, manifest_path: Path | str, aliases_path: Path | str) -> "EstateRegistry":
        with Path(manifest_path).open(newline="", encoding="utf-8-sig") as handle:
            manifest = [row for row in csv.DictReader(handle) if row.get("enabled", "").upper() == "TRUE"]
        records = [
            EstateRecord(
                estate=row["estate"],
                key=EstateKey(int(row["plantation_id"]), int(row["estate_id"])),
                category=OperationalCategory(row["operational_category"]),
                identity_status=row["identity_status"],
                source_kind=row["source_kind"],
                source_locator=row["source_locator"],
                crop_output_directory=row["crop_output_directory"],
            )
            for row in manifest
        ]
        canonical_names = {record.estate for record in records}
        aliases: dict[str, str] = {normalize_alias(name): name for name in canonical_names}
        with Path(aliases_path).open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                canonical = row["canonical_estate"]
                if canonical not in canonical_names:
                    raise ValueError(f"Alias targets unknown estate: {canonical}")
                key = normalize_alias(row["alias"])
                existing = aliases.get(key)
                if existing and existing != canonical:
                    raise ValueError(f"Ambiguous alias {row['alias']}: {existing} / {canonical}")
                aliases[key] = canonical
        return cls(records, aliases)

    def __len__(self) -> int:
        return len(self._by_name)

    @property
    def records(self) -> tuple[EstateRecord, ...]:
        return tuple(sorted(self._by_name.values(), key=lambda item: item.estate))

    def resolve(self, value: str) -> EstateRecord:
        canonical = self._aliases.get(normalize_alias(value))
        if not canonical:
            raise KeyError(f"Unknown estate alias: {value}")
        return self._by_name[canonical]

    def by_key(self, plantation_id: int, estate_id: int) -> EstateRecord:
        return self._by_key[EstateKey(plantation_id, estate_id)]

    def assert_estate_access(self, assigned_estate: str, requested_estate: str) -> EstateRecord:
        assigned = self.resolve(assigned_estate)
        requested = self.resolve(requested_estate)
        if assigned.key != requested.key:
            raise PermissionError("Cross-estate access is not permitted")
        return requested
