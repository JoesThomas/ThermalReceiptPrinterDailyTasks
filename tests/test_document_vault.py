from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json
import zipfile
from PIL import Image
from organiser import vault


def png():
    output = BytesIO()
    Image.new('RGB', (20, 20), 'white').save(output, format='PNG')
    return output.getvalue()


class DocumentVaultTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, value in [('DIRECTORY', self.root / 'private' / 'vault'), ('KEY_FILE', self.root / 'keys' / 'vault.key')]:
            patcher = patch.object(vault, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        vault.initialise()

    def test_content_and_metadata_are_encrypted_and_key_is_separate(self):
        identifier = vault.upload(BytesIO(png()), 'private-name.png', 'Sensitive certificate')
        raw = b''.join(p.read_bytes() for p in vault.DIRECTORY.glob('*.enc'))
        self.assertNotIn(b'Sensitive certificate', raw)
        self.assertNotIn(b'private-name', raw)
        self.assertNotIn(b'PNG', raw)
        self.assertEqual(vault.KEY_FILE.stat().st_mode & 0o777, 0o600)
        self.assertEqual(vault.DIRECTORY.stat().st_mode & 0o777, 0o700)
        row, content = vault.read(identifier)
        self.assertEqual(row['title'], 'Sensitive certificate')
        self.assertEqual(Image.open(BytesIO(content)).format, 'PNG')

    def test_spoofed_extensions_active_pdf_and_traversal_are_rejected(self):
        from pypdf import PdfWriter
        bad = PdfWriter()
        bad.add_blank_page(width=100, height=100)
        bad.add_js("app.alert('test')")
        output = BytesIO()
        bad.write(output)
        for filename, raw in [('../x.png', png()), ('x.html', b'<script>x</script>'), ('x.pdf', png()), ('x.jpg', png()), ('x.pdf', output.getvalue())]:
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                vault.upload(BytesIO(raw), filename, 'Title')
        good = PdfWriter()
        good.add_blank_page(width=100, height=100)
        output = BytesIO()
        good.write(output)
        identifier = vault.upload(BytesIO(output.getvalue()), 'x.pdf', 'Passive document')
        self.assertEqual(vault.read(identifier)[0]['suffix'], 'pdf')

    def test_tampering_missing_key_and_missing_index_fail_without_replacement(self):
        identifier = vault.upload(BytesIO(png()), 'x.png', 'Title')
        path = vault.DIRECTORY / (identifier + '.enc')
        path.write_bytes(path.read_bytes()[:-2] + b'xx')
        with self.assertRaises(ValueError):
            vault.read(identifier)
        vault.KEY_FILE.unlink()
        with self.assertRaises(ValueError):
            vault.initialise()
        self.assertFalse(vault.KEY_FILE.exists())
        (vault.DIRECTORY / 'index.enc').unlink()
        with self.assertRaises(ValueError):
            vault.listing()
        self.assertTrue(path.exists())

    def test_expiration_and_deletion_do_not_claim_to_erase_downloaded_backups(self):
        today = date(2026, 10, 22)
        with patch.object(vault, 'uk_today', return_value=today):
            identifier = vault.upload(BytesIO(png()), 'x.png', 'Title', str(today+timedelta(days=1)))
            backup = vault.backup().getvalue()
        with patch.object(vault, 'uk_today', return_value=today+timedelta(days=1)):
            self.assertFalse(vault.listing())
            with self.assertRaises(ValueError):
                vault.read(identifier)
        self.assertGreater(len(backup), 0)

    def test_backup_is_encrypted_authenticated_and_restore_is_bounded(self):
        identifier = vault.upload(BytesIO(png()), 'x.png', 'Secret')
        raw = vault.backup().getvalue()
        archive = zipfile.ZipFile(BytesIO(raw))
        self.assertNotIn(vault.KEY_FILE.name, archive.namelist())
        self.assertNotIn(b'Secret', raw)
        with self.assertRaises(ValueError):
            vault.restore(raw)
        vault.remove(identifier)
        vault.restore(raw)
        self.assertEqual(vault.read(identifier)[0]['title'], 'Secret')
        output = BytesIO()
        with zipfile.ZipFile(output, 'w') as bad:
            bad.writestr('../escape', 'no')
        with self.assertRaises((ValueError, KeyError)):
            vault.restore(output.getvalue())

    def test_symlinks_and_public_key_locations_are_rejected(self):
        target = self.root / 'linked.key'
        target.symlink_to(vault.KEY_FILE)
        with patch.object(vault, 'KEY_FILE', target), self.assertRaises(ValueError):
            vault.cipher()
        with patch.object(vault, 'KEY_FILE', vault.ROOT / 'data' / 'unsafe.key'), self.assertRaises(ValueError):
            vault.initialise()

    def test_upload_and_store_quotas_are_enforced(self):
        with self.assertRaises(ValueError):
            vault.upload(BytesIO(b'x'*(vault.MAX_FILE+1)), 'x.pdf', 'Title')
        with patch.object(vault, 'MAX_DOCS', 1):
            vault.upload(BytesIO(png()), 'x.png', 'One')
            with self.assertRaises(ValueError):
                vault.upload(BytesIO(png()), 'x.png', 'Two')

    def test_image_metadata_is_removed(self):
        from PIL.PngImagePlugin import PngInfo
        output = BytesIO()
        info = PngInfo()
        info.add_text('PrivateComment', 'DO NOT KEEP THIS')
        Image.new('RGB', (20, 20)).save(output, format='PNG', pnginfo=info)
        identifier = vault.upload(BytesIO(output.getvalue()), 'x.png', 'Image')
        content = vault.read(identifier)[1]
        self.assertNotIn(b'DO NOT KEEP THIS', content)

    def test_swapping_encrypted_documents_is_detected(self):
        first = vault.upload(BytesIO(png()), 'x.png', 'One')
        second = vault.upload(BytesIO(png()), 'x.png', 'Two')
        a, b = (vault.DIRECTORY / (i + '.enc') for i in (first, second))
        one, two = a.read_bytes(), b.read_bytes()
        a.write_bytes(two)
        b.write_bytes(one)
        with self.assertRaises(ValueError):
            vault.read(first)
