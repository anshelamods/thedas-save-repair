"""Save-corruption boundaries and transaction tests for the focused repair."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
(Path(__file__).resolve().parent / "output").mkdir(exist_ok=True)
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from dai_gender_repair import (HEROES, SIGNATURE, RepairError, apply, backup_directory,
                               digest, header, move_legacy_backups, parse, read_save, repair, rotate, undo)


def fixture(shift=0, genders=(0, 1), inconsistent=True):
    yes, no, ints = [], [], []
    for (enum, male, female), gender in zip(HEROES.values(), genders):
        # Mimic the studio bug: correct enum, opposite boolean predicates.
        boolean_gender = 1 - gender if inconsistent else gender
        yes.append(male if boolean_gender == 0 else female)
        no.append(female if boolean_gender == 0 else male)
        ints.append(enum + struct.pack('>i', gender))
    yes.append(b'A' * 16)
    no.append(b'B' * 16)
    ints.append(b'C' * 16 + b'\xff\xff\xff\xfd')
    groups = yes, no, ints, [b'D' * 16 + b'\x7f\xa1\x23\x45']  # preserve NaN payload
    table = b''.join(struct.pack('>H', len(g)) + b''.join(g) for g in groups)
    # Encode just the plot payload. The global inverse must preserve boundary bits.
    payload = rotate(b'\x89opaque-before\xfe' + SIGNATURE + table + b'\xc3opaque-after\x97', -shift)
    meta = struct.pack('>IH', 0x92796772, 4) + b'Test'
    hd = b'FBHEADER\x00\x01' + struct.pack('>I', 1) + meta
    return (b'FBCHUNKS\x01\x00' + struct.pack('<II', 4 + len(hd), 4 + len(payload)) +
            struct.pack('<I', zlib.crc32(hd, 0x12345678)) + hd +
            struct.pack('<I', zlib.crc32(payload, 0x12345678)) + payload)


class RepairTests(unittest.TestCase):
    def setUp(self):
        local = tempfile.TemporaryDirectory(dir=Path(__file__).parent / 'output')
        self.addCleanup(local.cleanup)
        env = patch.dict('os.environ', {'LOCALAPPDATA': local.name})
        env.start()
        self.addCleanup(env.stop)

    def test_all_bit_shifts_and_gender_combinations_preserve_opaque_bytes(self):
        for shift in range(8):
            for warden in range(2):
                for hawke in range(2):
                    with self.subTest(shift=shift, warden=warden, hawke=hawke):
                        raw = fixture(shift, (warden, hawke))
                        before = parse(raw)
                        result = repair(before, dict(warden=warden, hawke=hawke))
                        after = parse(result)
                        self.assertEqual(len(raw), len(result))
                        self.assertEqual(after.gender('warden'), (warden, warden == 0, warden == 1))
                        self.assertEqual(after.gender('hawke'), (hawke, hawke == 0, hawke == 1))
                        self.assertEqual(before.groups[3], after.groups[3])
                        self.assertEqual(raw[:before.data_start], result[:before.data_start])
                        # Independently derive the exact permissible encoded bit mask.
                        original_bits = int.from_bytes(raw, 'big')
                        repaired_bits = int.from_bytes(result, 'big')
                        byte_mask = bytearray(len(raw))
                        byte_mask[before.start:before.end] = b'\xff' * (before.end - before.start)
                        mask = bytearray(rotate(bytes(byte_mask), -before.shift))
                        mask[before.data_start:before.data_start + 4] = b'\xff' * 4
                        self.assertEqual((original_bits ^ repaired_bits) & ~int.from_bytes(mask, 'big'), 0)
                        self.assertEqual(repair(after, dict(warden=warden, hawke=hawke)), result)

    def test_partial_repair_does_not_touch_other_hero(self):
        before = parse(fixture(7))
        after = parse(repair(before, {'warden': 0}))
        self.assertEqual(before.gender('hawke'), after.gender('hawke'))
        self.assertEqual(after.gender('warden'), (0, True, False))

    def test_both_predicates_false_and_true(self):
        for true_value in (False, True):
            save = parse(fixture(3))
            male, female = HEROES['warden'][1:]
            order = save.groups[0] + save.groups[1]
            truth = {r: r in save.groups[0] for r in order}
            truth[male] = truth[female] = true_value
            groups = [[r for r in order if truth[r]], [r for r in order if not truth[r]], *save.groups[2:]]
            table = b''.join(struct.pack('>H', len(g)) + b''.join(g) for g in groups)
            raw = bytearray(rotate(save.decoded[:save.start] + table + save.decoded[save.end:], -save.shift))
            struct.pack_into('<I', raw, save.data_start, zlib.crc32(raw[save.data_start + 4:], 0x12345678))
            self.assertEqual(parse(repair(parse(bytes(raw)), {'warden': 0})).gender('warden'), (0, True, False))

    def test_corrupt_header_data_and_truncation_refused(self):
        original = fixture()
        for pos in (0, 10, 18, 40, len(original) - 1):
            bad = bytearray(original)
            bad[pos] ^= 1
            with self.subTest(pos=pos), self.assertRaises(RepairError):
                parse(bytes(bad))
        for size in (0, 15, 35, len(original) - 1):
            with self.assertRaises(RepairError):
                parse(original[:size])

    def test_missing_duplicate_and_wrong_enum_refused(self):
        save = parse(fixture())
        enum, male, female = HEROES['warden']
        for old, new in ((male, b'Z' * 16), (male, female),
                         (enum + b'\0\0\0\0', enum + b'\0\0\0\x02')):
            raw = bytearray(save.raw.replace(old, new))
            struct.pack_into('<I', raw, save.data_start, zlib.crc32(raw[save.data_start + 4:], 0x12345678))
            with self.assertRaises(RepairError):
                parse(bytes(raw))

    def test_ambiguous_tables_refused(self):
        save = parse(fixture())
        raw = bytearray(save.raw + SIGNATURE + save.decoded[save.start:save.end])
        struct.pack_into('<I', raw, 14, len(raw) - save.data_start)
        struct.pack_into('<I', raw, save.data_start, zlib.crc32(raw[save.data_start + 4:], 0x12345678))
        with self.assertRaisesRegex(RepairError, 'Multiple'):
            parse(bytes(raw))

    def test_invalid_choices(self):
        save = parse(fixture())
        for choices in ({}, {'inquisitor': 1}, {'warden': -1}, {'warden': True}):
            with self.assertRaises(RepairError):
                repair(save, choices)

    def test_backup_undo_and_newer_progress_protection(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / 'output') as folder:
            path = Path(folder) / 'test.DAS'
            original = fixture(4)
            path.write_bytes(original)
            backup, result_hash = apply(path, read_save(path), dict(warden=0, hawke=1))
            self.assertEqual(backup.read_bytes(), original)
            self.assertFalse(backup.is_relative_to(path.parent))
            self.assertEqual(list(path.parent.iterdir()), [path])
            repaired = path.read_bytes()
            redo_backup = undo(path, backup, result_hash)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(redo_backup.read_bytes(), repaired)
            with self.assertRaisesRegex(RepairError, 'changed'):
                undo(path, backup, result_hash)
            with self.assertRaisesRegex(RepairError, 'changed'):
                apply(path, parse(repaired), {'warden': 1})

    def test_failed_replace_preserves_original_and_backup(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / 'output') as folder:
            path = Path(folder) / 'test.DAS'
            original = fixture()
            path.write_bytes(original)
            with patch('dai_gender_repair.os.replace', side_effect=PermissionError('locked')):
                with self.assertRaises(PermissionError):
                    apply(path, parse(original), {'warden': 0})
            self.assertEqual(path.read_bytes(), original)
            backups = list(backup_directory(path).glob('*.bak'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)
            self.assertFalse(list(Path(folder).glob('*.tmp')))

    def test_backup_failure_does_not_replace_save(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / 'output') as folder:
            path = Path(folder) / 'test.DAS'
            original = fixture()
            path.write_bytes(original)
            with patch('dai_gender_repair._write_backup', side_effect=PermissionError('backup unavailable')):
                with self.assertRaises(PermissionError):
                    apply(path, parse(original), {'warden': 0})
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_move_old_backups_preserves_bytes_and_active_saves(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / 'output') as folder:
            path = Path(folder) / 'test.DAS'
            original = fixture()
            path.write_bytes(original)
            old = path.with_name(path.name + '.gender-backup-0123456789ab.bak')
            old.write_bytes(original)
            other = path.with_name('other.DAS.gender-backup-0123456789ab.bak')
            other.write_bytes(original)
            active = path.with_name('another.DAS')
            active.write_bytes(original)
            moved = move_legacy_backups(path)
            self.assertEqual(len(moved), 1)
            self.assertEqual(moved[0][0], old.resolve())
            self.assertEqual(moved[0][1].read_bytes(), original)
            self.assertFalse(moved[0][1].is_relative_to(path.parent))
            self.assertFalse(old.exists())
            for untouched in (path, other, active):
                self.assertEqual(untouched.read_bytes(), original)
            self.assertEqual(move_legacy_backups(path), [])

    def test_failed_migration_keeps_old_backup(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / 'output') as folder:
            path = Path(folder) / 'test.DAS'
            original = fixture()
            path.write_bytes(original)
            old = path.with_name(path.name + '.gender-backup-0123456789ab.bak')
            old.write_bytes(original)
            with patch('dai_gender_repair._write_backup', side_effect=PermissionError('unwritable')):
                with self.assertRaises(PermissionError):
                    move_legacy_backups(path)
            self.assertEqual(old.read_bytes(), original)
            self.assertEqual(path.read_bytes(), original)

    def test_backup_folders_are_separate_for_same_filename_in_different_locations(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / 'output') as folder:
            a = Path(folder) / 'one' / 'same.DAS'
            b = Path(folder) / 'two' / 'same.DAS'
            self.assertNotEqual(backup_directory(a), backup_directory(b))

    def test_refuses_backup_location_within_save_folder(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / 'output') as folder:
            path = Path(folder) / 'test.DAS'
            path.write_bytes(fixture())
            with patch.dict('os.environ', {'LOCALAPPDATA': folder}):
                with self.assertRaisesRegex(RepairError, 'outside'):
                    apply(path, read_save(path), {'warden': 0})

    def test_no_op_writes_nothing(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / 'output') as folder:
            path = Path(folder) / 'test.DAS'
            raw = fixture(inconsistent=False)
            path.write_bytes(raw)
            with self.assertRaisesRegex(RepairError, 'already'):
                apply(path, parse(raw), dict(warden=0, hawke=1))
            self.assertEqual(list(Path(folder).iterdir()), [path])


if __name__ == '__main__':
    unittest.main()
