"""Focused PC DAI save repair. Standard library only; no Java runtime.

Plot layout independently implemented from inspection of the supplied editor's
storage format. Unknown records and all payload outside the plot table survive.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import os
import struct
import tempfile
import uuid
import zlib

VERSION = '0.1.2-preview'
SIGNATURE = b'BioMetrics_PlotStartMarker'
MAX_SIZE = 32 * 1024 * 1024
# Raw save IDs, matching the supplied grouped mapping (not textual GUID order).
HEROES = {
    'warden': tuple(bytes.fromhex(s) for s in (
        '1E2016206BC8DD458D5714A975310380',
        '8071993155EB3C4882D16A51DCAB012D',
        '1B0E450966B7DD44AE67AF9ADB6101FC')),
    'hawke': tuple(bytes.fromhex(s) for s in (
        '150A1535BB00F44E895664FE65CC03FD',
        '5F3878CE91F269469FF14AB2C90A014E',
        '884A4EDEC1D1FF4A8F022869769601F8')),
}


class RepairError(ValueError):
    pass


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def rotate(raw: bytes, right: int) -> bytes:
    """Circular bit shift, retaining bits on both sides of the plot block."""
    if not raw:
        return raw
    right %= len(raw) * 8
    if not right:
        return raw
    bits = len(raw) * 8
    value = int.from_bytes(raw, 'big')
    return ((value >> right | value << (bits - right)) & ((1 << bits) - 1)).to_bytes(len(raw), 'big')


def header(raw: bytes) -> tuple[int, dict[int, str]]:
    if len(raw) < 36 or len(raw) > MAX_SIZE or raw[:10] != b'FBCHUNKS\x01\x00':
        raise RepairError('Choose a PC Inquisition .DAS save (up to 32 MB). DAO and DA2 saves are different formats.')
    size, data_size = struct.unpack_from('<II', raw, 10)
    end = 18 + size
    if size < 18 or data_size < 4 or end + data_size != len(raw) or raw[22:32] != b'FBHEADER\x00\x01':
        raise RepairError('The save header or file length is incomplete or unsupported.')
    for crc_at, start, stop in ((18, 22, end), (end, end + 4, len(raw))):
        stored = struct.unpack_from('<I', raw, crc_at)[0]
        if stored != zlib.crc32(raw[start:stop], 0x12345678):
            raise RepairError('The save checksum does not match. Use an unmodified, complete save from the game.')
    pos = 36
    items = {}
    count = struct.unpack_from('>I', raw, 32)[0]
    if count > (end - pos) // 6:
        raise RepairError('The save header item count is invalid.')
    for _ in range(count):
        if pos + 6 > end:
            raise RepairError('The save header is truncated.')
        key, length = struct.unpack_from('>IH', raw, pos)
        pos += 6
        if pos + length > end or key in items:
            raise RepairError('The save header contains truncated or duplicate entries.')
        items[key] = raw[pos:pos + length].decode('utf-8', errors='replace')
        pos += length
    return end, items


@dataclass
class Save:
    raw: bytes
    shift: int
    decoded: bytes
    start: int
    end: int
    groups: list[list[bytes]]
    data_start: int
    metadata: dict[int, str]

    def gender(self, hero: str) -> tuple[int, bool, bool]:
        enum, male, female = HEROES[hero]
        values = {row[:16]: struct.unpack('>i', row[16:])[0] for row in self.groups[2]}
        yes = set(self.groups[0])
        return values[enum], male in yes, female in yes

    @property
    def label(self) -> str:
        return ' · '.join(filter(None, (self.metadata.get(0x92796772, 'Unknown character'),
                                       self.metadata.get(0x2F852FB8))))


def _table(decoded: bytes, start: int) -> tuple[int, list[list[bytes]]]:
    pos = start
    groups = []
    seen = set()
    for width in (16, 16, 20, 20):
        if pos + 2 > len(decoded):
            raise RepairError('The plot table is truncated.')
        count = struct.unpack_from('>H', decoded, pos)[0]
        pos += 2
        if pos + count * width > len(decoded):
            raise RepairError('The plot table count extends beyond the file.')
        rows = [decoded[p:p + width] for p in range(pos, pos + count * width, width)]
        for row in rows:
            if row[:16] in seen:
                raise RepairError('The plot table contains duplicate or conflicting IDs.')
            seen.add(row[:16])
        groups.append(rows)
        pos += count * width
    bool_ids = set(groups[0] + groups[1])
    ints = {r[:16]: struct.unpack('>i', r[16:])[0] for r in groups[2]}
    for enum, male, female in HEROES.values():
        if male not in bool_ids or female not in bool_ids or ints.get(enum) not in (0, 1):
            raise RepairError('This save does not contain all six supported hero gender flags. No flags will be guessed or added.')
    return pos, groups


def parse(raw: bytes) -> Save:
    data_start, metadata = header(raw)
    found = []
    errors = []
    for shift in range(8):
        decoded = rotate(raw, shift)
        pos = decoded.find(SIGNATURE, data_start + 4)
        while pos >= 0:
            start = pos + len(SIGNATURE)
            try:
                end, groups = _table(decoded, start)
                found.append(Save(raw, shift, decoded, start, end, groups, data_start, metadata))
            except RepairError as exc:
                errors.append(str(exc))
            pos = decoded.find(SIGNATURE, start)
    if len(found) != 1:
        raise RepairError('Multiple supported plot tables were found; refusing an ambiguous repair.' if found else
                          (errors[0] if errors else 'No supported Inquisition plot table was found.'))
    return found[0]


def read_save(path: Path) -> Save:
    if path.stat().st_size > MAX_SIZE:
        raise RepairError('Choose a save no larger than 32 MB.')
    with path.open('rb') as handle:
        raw = handle.read(MAX_SIZE + 1)
    return parse(raw)


def repair(save: Save, choices: dict[str, int]) -> bytes:
    if not choices or any(k not in HEROES or type(v) is not int or v not in (0, 1) for k, v in choices.items()):
        raise RepairError('Select Male or Female for at least one supported hero.')
    bools = {r: True for r in save.groups[0]}
    bools.update({r: False for r in save.groups[1]})
    replacements = {}
    changed = False
    for hero, gender in choices.items():
        enum, male, female = HEROES[hero]
        changed |= save.gender(hero) != (gender, gender == 0, gender == 1)
        bools[male], bools[female] = gender == 0, gender == 1
        replacements[enum] = struct.pack('>i', gender)
    if not changed:
        return save.raw
    order = save.groups[0] + save.groups[1]
    groups = [[r for r in order if bools[r]], [r for r in order if not bools[r]],
              [r[:16] + replacements.get(r[:16], r[16:]) for r in save.groups[2]], save.groups[3]]
    table = b''.join(struct.pack('>H', len(g)) + b''.join(g) for g in groups)
    if len(table) != save.end - save.start:
        raise RepairError('The repair would change the plot table size.')
    decoded = save.decoded[:save.start] + table + save.decoded[save.end:]
    output = bytearray(rotate(decoded, -save.shift))
    struct.pack_into('<I', output, save.data_start,
                     zlib.crc32(output[save.data_start + 4:], 0x12345678))
    result = bytes(output)
    check = parse(result)
    # Verify all unowned plot values, including opaque float/NaN bit patterns.
    allowed = {key for hero in choices for key in HEROES[hero]}
    def untouched(s):
        return [{r[:16]: (value if i < 2 else r[16:]) for r in group if r[:16] not in allowed}
                for i, group in enumerate(s.groups) for value in [i == 0]]
    # Boolean records can move between groups only for the selected heroes.
    if untouched(check) != untouched(save):
        raise RepairError('Unrelated plot values changed during verification.')
    for hero, gender in choices.items():
        if check.gender(hero) != (gender, gender == 0, gender == 1):
            raise RepairError('The repaired gender flags did not verify.')
    # Check every bit outside the edited table and the outer data checksum.
    expected = bytearray(save.decoded)
    actual = bytearray(check.decoded)
    expected[save.start:save.end] = actual[save.start:save.end]
    # Compare in encoded form to avoid checksum bytes crossing bit boundaries.
    expected_raw = bytearray(rotate(bytes(expected), -save.shift))
    expected_raw[save.data_start:save.data_start + 4] = result[save.data_start:save.data_start + 4]
    if bytes(expected_raw) != result or len(result) != len(save.raw):
        raise RepairError('Unexpected changes outside the gender plot table.')
    return result


def backup_directory(path: Path) -> Path:
    """Keep loadable backup bytes outside the game's save discovery tree."""
    source = path.resolve()
    local = os.environ.get('LOCALAPPDATA')
    base = Path(local) if local else Path.home() / 'AppData' / 'Local'
    slot = digest(os.path.normcase(str(source)).encode('utf-8'))[:24]
    destination = (base / 'ThedasWorldstateStudio' / 'SaveBackups' / slot).resolve()
    if destination.is_relative_to(source.parent):
        raise RepairError('The backup location must be outside the save folder. No save was changed.')
    return destination


def is_backup_for(backup: Path, path: Path) -> bool:
    name = backup.name.casefold()
    return (not backup.is_symlink() and backup.suffix.casefold() == '.bak' and
            any(name.startswith(path.name.casefold() + '.' + purpose + '-backup-') for purpose in ('gender', 'tapestry')) and
            backup.parent.resolve() in (backup_directory(path), path.resolve().parent))


def _write_backup(path: Path, raw: bytes, purpose: str) -> Path:
    directory = backup_directory(path)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')
    backup = directory / (path.name + '.' + purpose + '-backup-' + timestamp + '-' + uuid.uuid4().hex[:12] + '.bak')
    with backup.open('xb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    if backup.read_bytes() != raw:
        raise RepairError('The backup did not verify; the save has not been replaced.')
    return backup


def move_legacy_backups(path: Path) -> list[tuple[Path, Path]]:
    """Move only this slot's recognized old backups, after verifying each copy."""
    path = path.resolve(strict=True)
    moved = []
    for old in sorted(path.parent.iterdir()):
        if not old.is_file() or not is_backup_for(old, path):
            continue
        original = read_save(old).raw
        purpose = 'gender' if old.name.casefold().startswith(path.name.casefold() + '.gender-') else 'tapestry'
        new = _write_backup(path, original, purpose)
        if old.read_bytes() != original:
            raise RepairError('An old backup changed while being moved. Both copies were kept: ' + str(old))
        old.unlink()
        moved.append((old, new))
    return moved


def replace_with_backup(path: Path, expected: bytes, replacement: bytes, *, purpose='gender') -> Path:
    """Optimistic conflict check, durable unique backup, same-directory replacement."""
    if purpose not in ('gender', 'tapestry'):
        raise RepairError('Unsupported save operation.')
    if path.is_symlink() or path.suffix.lower() != '.das':
        raise RepairError('Choose the .DAS save itself.')
    path = path.resolve(strict=True)
    parse(replacement)
    if path.read_bytes() != expected:
        raise RepairError('The save changed since it was opened. Close the game and reopen the save.')
    if replacement == expected:
        raise RepairError('The selected values already match this save. No file was written.')
    backup = _write_backup(path, expected, purpose)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + purpose + '-repair-', suffix='.tmp', delete=False) as handle:
            temp_name = handle.name
            handle.write(replacement)
            handle.flush()
            os.fsync(handle.fileno())
        if Path(temp_name).read_bytes() != replacement:
            raise RepairError('The temporary save did not verify; the original is unchanged.')
        if path.read_bytes() != expected:
            raise RepairError('The save changed during repair. The original was not replaced.')
        os.replace(temp_name, path)
        temp_name = None
        if path.read_bytes() != replacement:
            raise RepairError('Save readback failed. Your verified backup is at: ' + str(backup))
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
    return backup


def apply(path: Path, save: Save, choices: dict[str, int]) -> tuple[Path, str]:
    output = repair(save, choices)
    backup = replace_with_backup(path, save.raw, output)
    return backup, digest(output)


def undo(path: Path, backup: Path, repaired_hash: str) -> Path:
    current = read_save(path)
    if digest(current.raw) != repaired_hash:
        raise RepairError('This save changed after the repair. Undo stopped to avoid erasing newer progress.')
    original = read_save(backup)
    return replace_with_backup(path, current.raw, original.raw)
