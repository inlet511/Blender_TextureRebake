"""Run with Blender --background --factory-startup --python-exit-code 1 --python <this file>."""
import bpy
import importlib.util
import json
import struct
import zlib
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('texture_rebake', ROOT/'texture_rebake.py')
addon = importlib.util.module_from_spec(spec); spec.loader.exec_module(addon); addon.register()
OUT = ROOT/'test_output'
OUT.mkdir(exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)


def png_chunk(kind, data):
    return struct.pack('>I', len(data))+kind+data+struct.pack('>I', zlib.crc32(kind+data))


def read_png8_rgb(path):
    """Read actual PNG codes independently of Blender's image/color management."""
    data = Path(path).read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    offset = 8; compressed = bytearray()
    while offset < len(data):
        length = struct.unpack_from('>I', data, offset)[0]
        kind = data[offset+4:offset+8]; chunk = data[offset+8:offset+8+length]
        if kind == b'IHDR':
            width, height, depth, color_type, compression, filtering, interlace = struct.unpack('>IIBBBBB', chunk)
            assert depth == 8 and color_type in (2, 6) and interlace == 0
        elif kind == b'IDAT': compressed.extend(chunk)
        offset += length+12
    channels = 3 if color_type == 2 else 4
    stride = width*channels
    raw = zlib.decompress(compressed)
    result = np.empty((height, stride), dtype=np.uint8)
    previous = bytearray(stride)
    for y in range(height):
        start = y*(stride+1); filter_type = raw[start]
        row = bytearray(raw[start+1:start+1+stride])
        for i in range(stride):
            left = row[i-channels] if i >= channels else 0
            up = previous[i]; upper_left = previous[i-channels] if i >= channels else 0
            if filter_type == 0: predictor = 0
            elif filter_type == 1: predictor = left
            elif filter_type == 2: predictor = up
            elif filter_type == 3: predictor = (left+up)//2
            elif filter_type == 4:
                p = left+up-upper_left
                distances = (abs(p-left), abs(p-up), abs(p-upper_left))
                predictor = (left, up, upper_left)[distances.index(min(distances))]
            else: raise AssertionError(f'Unknown PNG filter {filter_type}')
            row[i] = (row[i]+predictor) & 255
        result[y] = np.frombuffer(row, dtype=np.uint8)
        previous = row
    return result.reshape(height, width, channels)[:, :, :3]


def image(name, rgba):
    # Independent straight RGBA PNG fixture: Blender's float image saver may
    # unpremultiply synthetic alpha, which would change the intended channel values.
    def chunk(kind, data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
    pixel = bytes(round(v*255) for v in rgba)
    data = (b'\x00'+pixel*16)*16
    png = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',16,16,8,6,0,0,0))
    png += chunk(b'IDAT',zlib.compress(data))+chunk(b'IEND',b'')
    path = OUT/(name+'.png'); path.write_bytes(png); return str(path)


def plane(name, rotated=False, z=0):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0,0,z),(1,0,z),(1,1,z),(0,1,z)], [], [(0,1,2,3)])
    uv = mesh.uv_layers.new(name='UVMap')
    for loop, (x,y) in zip(uv.data, [(0,0),(1,0),(1,1),(0,1)]):
        loop.uv = (1-y,x) if rotated else (x,y)
    obj = bpy.data.objects.new(name, mesh); bpy.context.collection.objects.link(obj); return obj


def sample(report, label):
    im = bpy.data.images.load(report['files'][label], check_existing=False)
    im.colorspace_settings.name = 'Non-Color'
    values = addon.pixels(im).reshape(256,256,4)[32:-32,32:-32,:3].mean(axis=(0,1))
    bpy.data.images.remove(im); return values


s = bpy.context.scene.texture_rebake
s.source = plane('Source'); s.target = plane('Target', True)
s.basecolor = image('color', [.2,.4,.6,1])
s.normal = image('normal_dx', [.7,.3,.91231,1])
s.roughness = image('rough', [.25,.25,.25,1])
s.output_dir = str(OUT); s.resolution = '256'; s.margin = 4; s.preview = False
scene = bpy.context.scene; scene.render.engine = 'BLENDER_EEVEE'
original_mesh = s.target.data; original_materials = list(s.target.data.materials)
before = (len(bpy.data.scenes),len(bpy.data.objects),len(bpy.data.meshes),len(bpy.data.materials))
report = addon.bake_textures(bpy.context, s)
for path in report['files'].values():
    assert Path(path).read_bytes()[24] == 8, 'UE texture PNG must be 8-bit per channel'
assert report['png_bit_depth'] == 8
assert report['coverage_percent'] == 100, report
assert np.allclose(sample(report,'ORM'), [1,.25,0], atol=.008), sample(report,'ORM')
# Both input and output DirectX, rotated target UV: expected tangent XY = (-.4,+.4).
assert np.allclose(sample(report,'Normal'), [.3,.3,.9123], atol=.012), sample(report,'Normal')
assert np.allclose(sample(report,'BaseColor'), [.2,.4,.6], atol=.012), sample(report,'BaseColor')
assert bpy.context.scene == scene and scene.render.engine == 'BLENDER_EEVEE'
assert s.target.data == original_mesh and list(s.target.data.materials) == original_materials
assert before == (len(bpy.data.scenes),len(bpy.data.objects),len(bpy.data.meshes),len(bpy.data.materials))
cases = ['missing AO/metal defaults', 'rotated tangent normal DirectX', 'sRGB roundtrip', 'scene isolation', 'explicit 8-bit PNG output']
# Independent 8-bit source ramp, baked through rotated UVs under different
# display settings. Compare PNG bytes, not Blender's interpretation on reload.
ramp_path = OUT/'source_ramp.png'
row = b''.join(bytes((v, v, v)) for v in range(256))
ramp_path.write_bytes(b'\x89PNG\r\n\x1a\n'
    + png_chunk(b'IHDR', struct.pack('>IIBBBBB', 256, 256, 8, 2, 0, 0, 0))
    + png_chunk(b'IDAT', zlib.compress((b'\x00'+row)*256)) + png_chunk(b'IEND', b''))
original_input = s.basecolor
original_view = scene.view_settings.view_transform
for view, exposure, gamma in (('Standard', 0, 1), ('AgX', 4, 1.8)):
    scene.view_settings.view_transform = view
    scene.view_settings.exposure = exposure; scene.view_settings.gamma = gamma
    s.basecolor = str(ramp_path)
    ramp_report = addon.bake_textures(bpy.context, s)
    actual = read_png8_rgb(ramp_report['files']['BaseColor']).astype(int)
    # PNG rows run top-to-bottom; destination V equals source U after rotation.
    expected = np.broadcast_to(np.arange(255, -1, -1)[:, None, None], actual.shape)
    assert np.abs(actual-expected).max() <= 1, (view, np.abs(actual-expected).max())
s.basecolor = original_input
scene.view_settings.view_transform = original_view
scene.view_settings.exposure = 0; scene.view_settings.gamma = 1
cases += ['all 256 sRGB codes through Cycles and rotated UVs',
          'bake PNG bytes independent of Standard/AgX, exposure and gamma']
# Asymmetric color quadrants independently check source UV -> rotated destination UV.
im = bpy.data.images.new('quadrants', width=64, height=64, float_buffer=True)
im.colorspace_settings.name = 'Non-Color'
grid = np.ones((64,64,4),dtype=np.float32)
grid[:32,:32,:3] = [1,0,0]; grid[:32,32:,:3] = [0,1,0]
grid[32:,:32,:3] = [0,0,1]; grid[32:,32:,:3] = [1,1,0]
im.pixels.foreach_set(grid.ravel()); im.filepath_raw = str(OUT/'quadrants.png'); im.file_format = 'PNG'; im.save()
s.basecolor = im.filepath_raw; bpy.data.images.remove(im)
packed = image('packed', [.2,.4,.8,.6])
s.ao = packed; s.ao_channel = 'B'
s.roughness = packed; s.rough_channel = 'G'
s.metallic = packed; s.metal_channel = 'A'
s.metal_default = .9  # A supplied metallic map must override the fallback.
s.normal_output = 'OPENGL'
report = addon.bake_textures(bpy.context, s)
im = bpy.data.images.load(report['files']['BaseColor'],check_existing=False)
grid = addon.pixels(im).reshape(256,256,4)
for row,col,expected in [(64,64,[0,0,1]),(64,192,[1,0,0]),(192,64,[1,1,0]),(192,192,[0,1,0])]:
    assert np.allclose(grid[row,col,:3],expected,atol=.01), (row,col,grid[row,col,:3])
bpy.data.images.remove(im); cases += ['asymmetric source-to-target UV mapping']
assert np.allclose(sample(report,'ORM'), [.8,.4,.6], atol=.008), sample(report,'ORM')
assert np.allclose(sample(report,'Normal'), [.3,.7,.9123], atol=.012), sample(report,'Normal')
cases += ['independent B/G/A channel selection from shared texture', 'OpenGL output']
s.ao_channel = 'R'; s.rough_channel = 'RGB'; s.metal_channel = 'RGB'
s.basecolor = packed; s.basecolor_channel = 'B'
report = addon.bake_textures(bpy.context,s)
luminance = .2126*.2 + .7152*.4 + .0722*.8
assert np.allclose(sample(report,'ORM'), [.2,luminance,luminance], atol=.008), sample(report,'ORM')
assert np.allclose(sample(report,'BaseColor'), [.8,.8,.8], atol=.008), sample(report,'BaseColor')
assert report['input_channels'] == {'basecolor':'B','normal':'RGB','ao':'R','roughness':'RGB','metallic':'RGB'}
assert 'orm' not in report['inputs'] and not hasattr(s,'orm')
cases += ['R and full RGB luminance selection', 'BaseColor channel as grayscale', 'generic settings without ORM input']
s.ao = ''; s.metallic = ''; s.roughness = ''; s.normal = ''; s.rough_default = .65
s.metal_default = .35
s.basecolor_channel = 'RGB'
report = addon.bake_textures(bpy.context, s)
assert np.allclose(sample(report,'ORM'), [1,.65,.35], atol=.008)
assert np.isclose(report['fallback_values']['metallic'], .35)
assert np.allclose(sample(report,'Normal'), [.5,.5,1], atol=.008)
cases += ['roughness and configurable metallic fallback', 'metallic texture overrides fallback', 'geometry normal fallback']
# A partially detached surface must be reported as misses, not silently accepted.
s.target.data.vertices[1].co.z = .5; s.target.data.vertices[2].co.z = .5
report = addon.bake_textures(bpy.context,s)
assert 0 < report['coverage_percent'] < 100 and report['warnings'], report
im = bpy.data.images.load(report['files']['ORM'],check_existing=False)
im.colorspace_settings.name = 'Non-Color'
assert np.allclose(addon.pixels(im)[:,2],.35,atol=.008)
bpy.data.images.remove(im)
cases += ['unmapped surface detection']
s.target.location.z = 10
try:
    addon.bake_textures(bpy.context,s)
    raise AssertionError('Should reject fully detached target')
except ValueError as exc:
    assert '所有投射' in str(exc), str(exc)
assert bpy.context.scene == scene
assert before == (len(bpy.data.scenes),len(bpy.data.objects),len(bpy.data.meshes),len(bpy.data.materials))
cases += ['failure cleanup']
s.target.location.z = 0
for v in s.target.data.vertices: v.co.z = 0
s.preview = True
# Reproduce the user's Chinese UI with translated new node names.
view = bpy.context.preferences.view
view.language = 'zh_HANS'; view.use_translate_new_dataname = True
probe = bpy.data.materials.new('LocaleProbe'); probe.use_nodes = True
assert probe.node_tree.nodes.get('Principled BSDF') is None
bpy.data.materials.remove(probe)
report = addon.bake_textures(bpy.context,s)
preview = bpy.context.object
assert preview != s.target and preview.data != s.target.data
assert len(preview.data.materials) == 1 and preview.data.materials[0].use_nodes
cases += ['preview material with translated Chinese node names']
assert report['preview_status'] == 'complete'
paths = [Path(p) for p in report['files'].values()]
mtimes = [p.stat().st_mtime_ns for p in paths]
s.normal_output = 'DIRECTX'  # Recovery must use the format in the report (OpenGL).
assert bpy.ops.texture_rebake.preview(directory=s.last_output) == {'FINISHED'}
recovered = bpy.context.object
assert recovered != preview
tree = recovered.data.materials[0].node_tree
assert any(n.bl_idname == 'ShaderNodeBsdfPrincipled' for n in tree.nodes)
assert not any(n.bl_idname == 'ShaderNodeMath' for n in tree.nodes)
assert mtimes == [p.stat().st_mtime_ns for p in paths]
cases += ['recover preview without rebaking or changing textures']
# A preview failure must not turn a successful texture export into a bake failure.
for obj in (s.source,s.target): obj.hide_set(False)
original_preview = addon.create_preview
def fail_preview(*args,**kwargs): raise RuntimeError('injected preview failure')
addon.create_preview = fail_preview
try:
    report = addon.bake_textures(bpy.context,s)
finally:
    addon.create_preview = original_preview
assert report['status'] == 'complete' and report['preview_status'] == 'failed'
assert report['preview_error'] == 'injected preview failure'
assert all(Path(p).is_file() for p in report['files'].values())
persisted = json.loads((Path(s.last_output)/'report.json').read_text(encoding='utf-8'))
assert persisted == report
cases += ['preview failure keeps bake success and records warning']
# An independent 0..255 reference sweep covers shadows, midtones and highlights.
# Saving textures must ignore display exposure/gamma and apply sRGB exactly once.
scene.view_settings.exposure = 4; scene.view_settings.gamma = 1.8
ramp = np.arange(256, dtype=np.float32)/255
linear = np.where(ramp <= .04045, ramp/12.92, ((ramp+.055)/1.055)**2.4)
buffer = np.ones((256,4),dtype=np.float32)
for color, values, name in ((True,linear,'encoding_sweep_srgb'),(False,ramp,'encoding_sweep_data')):
    buffer[:,:3] = values[:,None]
    im = bpy.data.images.new(name,width=256,height=1,float_buffer=True,alpha=True)
    im.colorspace_settings.name = 'sRGB' if color else 'Non-Color'
    im.pixels.foreach_set(buffer.ravel())
    addon.save_png8(im, OUT/(name+'.png'), color=color)
    bpy.data.images.remove(im)
    codes = read_png8_rgb(OUT/(name+'.png'))
    expected = np.broadcast_to(np.arange(256)[None, :, None], codes.shape)
    assert np.abs(codes.astype(int)-expected).max() <= 1, name
cases += ['sRGB and non-color reference sweeps independent of scene exposure']
# Preview geometry and bake share world-space extrusion, without scene data.
for obj in (s.source, s.target): obj.hide_set(False)
s.preview = False; s.extrusion = .2; s.ray_distance = 1
s.target.scale = (2, 3, 1); s.target.location = (4, 5, 0)
s.source.scale = s.target.scale; s.source.location = (4, 5, .1)
bpy.context.view_layer.update()
original_coords = [v.co.copy() for v in s.target.data.vertices]
def counts():
    return tuple(len(collection) for collection in (bpy.data.scenes,bpy.data.objects,bpy.data.meshes,bpy.data.materials))
unchanged = counts()
for shown in (True, False, True):
    s.show_cage = shown
    coords, edges, triangles = addon.cage_geometry(bpy.context, s)
    assert np.allclose(coords[0], (4,5,.2))
    assert len(edges) == 4 and len(triangles) == 2
    assert counts() == unchanged
assert all(a.co == b for a,b in zip(s.target.data.vertices,original_coords))
s.extrusion = .3
coords, _, _ = addon.cage_geometry(bpy.context, s)
assert np.allclose(coords[0], (4,5,.3))
# Evaluated modifiers must appear in the overlay without leaking meshes.
modifier = s.target.modifiers.new('preview_subdivision','SUBSURF'); modifier.levels = 1
bpy.context.view_layer.update()
coords, _, _ = addon.cage_geometry(bpy.context,s)
assert len(coords) > len(s.target.data.vertices) and counts() == unchanged
s.target.modifiers.remove(modifier); bpy.context.view_layer.update()
s.extrusion = .2
report = addon.bake_textures(bpy.context,s,coverage_only=True)
assert report['coverage_percent'] == 100 and report['cage'] == 'AUTO'
assert set(report['files']) == {'Coverage','Misses'} and counts() == unchanged
s.show_cage = False
hidden_report = addon.bake_textures(bpy.context,s,coverage_only=True)
assert hidden_report['coverage_percent'] == report['coverage_percent']
report = addon.bake_textures(bpy.context,s)
assert report['coverage_percent'] == 100 and counts() == unchanged
assert np.allclose(sample(report,'ORM'), [1,.65,.35], atol=.008)
assert np.allclose(sample(report,'Normal'), [.5,.5,1], atol=.008)
original_input = s.basecolor; s.basecolor = '/missing/source.png'
report = addon.bake_textures(bpy.context,s,coverage_only=True)
assert report['coverage_percent'] == 100
s.basecolor = original_input
# A cage below the source must miss; moving the slider controls actual rays.
s.extrusion = .01
try:
    addon.bake_textures(bpy.context,s,coverage_only=True)
    raise AssertionError('Cage below source should miss')
except ValueError as exc:
    assert '所有投射' in str(exc), str(exc)
assert counts() == unchanged and bpy.context.scene == scene
cases += ['overlay has no scene datablocks', 'world-space extrusion updates',
          'evaluated modifiers in preview', 'auto cage full bake and cleanup',
          'display toggle independent of bake', 'extrusion controls actual hits']
addon.unregister(); addon.register(); addon.unregister()
cases += ['register/unregister']
(OUT/'test_results.json').write_text(json.dumps({'status':'passed','cases':cases},indent=2),encoding='utf-8')
print('REBAKE_TESTS_PASSED',cases)
