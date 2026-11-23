"""Build an installable Blender add-on ZIP using only Python's standard library."""
import ast
import hashlib
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent


def build():
    source = ROOT / 'texture_rebake.py'
    code = source.read_bytes()
    tree = ast.parse(code, filename=str(source))
    info = next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'bl_info' for t in node.targets))
    version = '.'.join(map(str, info['version']))
    files = {
        'texture_rebake/__init__.py': code,
        'texture_rebake/README.md': (ROOT / 'README.md').read_bytes(),
        'texture_rebake/CHANGELOG.md': (ROOT / 'CHANGELOG.md').read_bytes(),
    }
    out = ROOT / 'dist'
    out.mkdir(exist_ok=True)
    archive = out / f'TextureRebake-{version}.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(entry, data)
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None, 'Corrupt ZIP'
        assert set(package.namelist()) == set(files), 'Unexpected package contents'
        assert package.read('texture_rebake/__init__.py') == code
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(f'Built: {archive} ({archive.stat().st_size:,} bytes)')
    print(f'SHA256: {digest}')
    return archive


if __name__ == '__main__':
    build()
