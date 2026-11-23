"""Install/enable/disable/remove the release ZIP in an isolated Blender profile.

Set BLENDER_USER_SCRIPTS and BLENDER_USER_CONFIG inside test_output/package_install
before starting Blender with --background --factory-startup --python-exit-code 1.
"""
import hashlib
import ast
from pathlib import Path

import addon_utils
import bpy


ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = (ROOT / 'test_output' / 'package_install').resolve()
scripts = Path(bpy.utils.user_resource('SCRIPTS')).resolve()
assert scripts.is_relative_to(TEST_ROOT), f'Refusing to use real Blender profile: {scripts}'
tree = ast.parse((ROOT / 'texture_rebake.py').read_bytes())
info = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == 'bl_info' for t in n.targets))
version = '.'.join(map(str, info['version']))
archive = ROOT / 'dist' / f'TextureRebake-{version}.zip'
assert bpy.ops.preferences.addon_install(filepath=str(archive)) == {'FINISHED'}
module = addon_utils.enable('texture_rebake', default_set=True)
assert module is not None
installed = Path(module.__file__).resolve()
assert installed == scripts / 'addons' / 'texture_rebake' / '__init__.py'
assert installed.read_bytes() == (ROOT / 'texture_rebake.py').read_bytes()
assert bpy.context.scene.texture_rebake is not None
assert bpy.ops.texture_rebake.bake.get_rna_type()
assert bpy.ops.texture_rebake.check_coverage.get_rna_type()
for _ in range(2):
    addon_utils.disable('texture_rebake', default_set=True)
    assert not hasattr(bpy.types.Scene, 'texture_rebake')
    assert module.invalidate_cage not in bpy.app.handlers.depsgraph_update_post
    assert addon_utils.enable('texture_rebake', default_set=True) is not None
    assert bpy.app.handlers.depsgraph_update_post.count(module.invalidate_cage) == 1
# Blender's removal operator redraws an area even in background mode.
with bpy.context.temp_override(area=bpy.context.screen.areas[0]):
    assert bpy.ops.preferences.addon_remove(module='texture_rebake') == {'FINISHED'}
assert not installed.exists()
assert not hasattr(bpy.types.Scene, 'texture_rebake')
print('PACKAGE_TESTS_PASSED', bpy.app.version_string, archive.name,
      hashlib.sha256(archive.read_bytes()).hexdigest())
