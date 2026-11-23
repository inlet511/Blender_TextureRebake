"""Texture Rebake: explicit image inputs, isolated Cycles selected-to-active baking."""
bl_info = {
    'name': 'Texture Rebake / 旧贴图转新 UV', 'author': 'Ken / Codex',
    'version': (1, 3, 1), 'blender': (4, 2, 0),
    'location': 'View3D > Sidebar > Rebake', 'category': 'Material',
    'description': 'Bake source textures to an edited mesh; tangent normals and ORM',
}

import bpy
import json
import re
import traceback
from datetime import datetime
from pathlib import Path
import numpy as np
from bpy.props import (PointerProperty, StringProperty, EnumProperty,
                       IntProperty, FloatProperty, BoolProperty, FloatVectorProperty)
from bpy.app.handlers import persistent


CHANNELS = [(c, c, '') for c in 'RGBA'] + [('RGB', 'RGB', '使用全部颜色通道；AO、粗糙度、金属度按亮度转为灰度')]
TEXTURE_KEYS = ('basecolor', 'normal', 'roughness', 'ao', 'metallic')
NORMALS = [('DIRECTX', 'DirectX (-Y / Unreal)', ''), ('OPENGL', 'OpenGL (+Y / Blender)', '')]


def mesh_poll(self, obj):
    return obj.type == 'MESH'


_overlay_handle = None
_overlay_cache = {}


def redraw_cage(self=None, context=None):
    _overlay_cache.clear()
    wm = bpy.context.window_manager
    if wm:
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D': area.tag_redraw()


@persistent
def invalidate_cage(*args):
    # Includes modifier dependencies, parent transforms, undo and file loading.
    _overlay_cache.clear()


def extrude_cage(mesh, distance):
    coords = [v.co + v.normal * distance for v in mesh.vertices]
    for v, co in zip(mesh.vertices, coords): v.co = co
    mesh.update()


def cage_geometry(context, settings):
    """Transient evaluated mesh only; never adds an object or mesh datablock."""
    evaluated = settings.target.evaluated_get(context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        mesh.transform(evaluated.matrix_world); mesh.update()
        extrude_cage(mesh, settings.extrusion)
        mesh.calc_loop_triangles()
        return ([v.co[:] for v in mesh.vertices],
                [e.vertices[:] for e in mesh.edges],
                [t.vertices[:] for t in mesh.loop_triangles])
    finally:
        evaluated.to_mesh_clear()


def draw_cage():
    context = bpy.context
    s = getattr(context.scene, 'texture_rebake', None)
    if not s or not s.show_cage or not s.target or not context.region_data:
        return
    if (s.target.name not in context.view_layer.objects
            or not s.target.visible_get(viewport=context.space_data)):
        return
    import gpu
    from gpu_extras.batch import batch_for_shader
    key = (context.scene.as_pointer(), context.view_layer.as_pointer(),
           s.target.as_pointer(), s.extrusion)
    if key not in _overlay_cache:
        coords, edges, triangles = cage_geometry(context, s)
        if not coords: return
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        wire_shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        _overlay_cache.clear()
        _overlay_cache[key] = (shader, wire_shader,
            batch_for_shader(shader, 'TRIS', {'pos': coords}, indices=triangles),
            batch_for_shader(wire_shader, 'LINES', {'pos': coords}, indices=edges))
    shader, wire_shader, surface, wire = _overlay_cache[key]
    state = (gpu.state.blend_get(), gpu.state.depth_test_get(), gpu.state.depth_mask_get())
    try:
        gpu.state.blend_set('ALPHA')
        # Respect scene depth: high-poly parts protruding through the cage remain visible.
        gpu.state.depth_test_set('LESS_EQUAL'); gpu.state.depth_mask_set(False)
        if s.cage_display == 'SOLID':
            shader.bind(); shader.uniform_float('color', (*s.cage_color, s.cage_opacity))
            surface.draw(shader)
        wire_shader.bind()
        wire_shader.uniform_float('viewportSize', gpu.state.viewport_get()[2:])
        wire_shader.uniform_float('lineWidth', 1.2)
        wire_shader.uniform_float('color', (*s.cage_color, 0.85))
        wire.draw(wire_shader)
    finally:
        gpu.state.blend_set(state[0]); gpu.state.depth_test_set(state[1]); gpu.state.depth_mask_set(state[2])


class TR_Settings(bpy.types.PropertyGroup):
    source: PointerProperty(name='原模型', type=bpy.types.Object, poll=mesh_poll)
    target: PointerProperty(name='新模型', type=bpy.types.Object, poll=mesh_poll, update=redraw_cage)
    source_uv: StringProperty(name='原模型 UV', description='留空使用第一个 UV 层')
    target_uv: StringProperty(name='新模型 UV', description='留空使用第一个 UV 层')
    basecolor: StringProperty(name='BaseColor', subtype='FILE_PATH')
    normal: StringProperty(name='Normal', subtype='FILE_PATH')
    roughness: StringProperty(name='Roughness', subtype='FILE_PATH')
    ao: StringProperty(name='AO（空=白）', subtype='FILE_PATH')
    metallic: StringProperty(name='Metallic', subtype='FILE_PATH')
    basecolor_channel: EnumProperty(name='BaseColor 通道', items=CHANNELS, default='RGB')
    ao_channel: EnumProperty(name='AO 通道', items=CHANNELS, default='RGB')
    rough_channel: EnumProperty(name='粗糙度通道', items=CHANNELS, default='RGB')
    metal_channel: EnumProperty(name='金属度通道', items=CHANNELS, default='RGB')
    rough_default: FloatProperty(name='缺失 Roughness 默认值', default=0.5, min=0, max=1)
    metal_default: FloatProperty(name='缺失 Metallic 默认值', default=0.0, min=0, max=1,
                                description='未提供金属度贴图时使用；0 为非金属，1 为金属')
    normal_input: EnumProperty(name='输入法线格式', items=NORMALS, default='DIRECTX')
    normal_output: EnumProperty(name='输出法线格式', items=NORMALS, default='DIRECTX')
    resolution: EnumProperty(name='分辨率', items=[(str(n), str(n), '') for n in (256, 512, 1024, 2048, 4096, 8192)], default='2048')
    margin: IntProperty(name='扩边像素', default=16, min=0, max=256)
    extrusion: FloatProperty(name='Cage 外扩', default=0.01, min=0, subtype='DISTANCE', update=redraw_cage, description='世界空间距离；预览和实际投射同步更新')
    ray_distance: FloatProperty(name='最大射线距离', default=0.05, min=0, subtype='DISTANCE', description='0 为不限距离，可能投射到背面')
    show_cage: BoolProperty(name='显示 Cage', default=False, update=redraw_cage, description='仅在视口叠加显示，不创建场景对象；不影响烘焙')
    cage_display: EnumProperty(name='显示方式', items=[('WIRE', '线框', ''), ('SOLID', '半透明 + 线框', '')], default='SOLID', update=redraw_cage)
    cage_color: FloatVectorProperty(name='Cage 颜色', subtype='COLOR', size=3, min=0, max=1, default=(0.1, 0.65, 1.0), update=redraw_cage)
    cage_opacity: FloatProperty(name='不透明度', default=0.25, min=0.01, max=1, update=redraw_cage)
    output_dir: StringProperty(name='输出目录', subtype='DIR_PATH', default='//TextureRebake/')
    prefix: StringProperty(name='文件名前缀', default='T_Rebaked')
    preview: BoolProperty(name='创建预览副本', default=True, description='创建隐藏原模型的独立预览副本，不修改原对象材质')
    last_output: StringProperty(name='上次输出目录', subtype='DIR_PATH')


def uv_name(obj, name):
    if not obj or obj.type != 'MESH' or not len(obj.data.polygons):
        raise ValueError('原模型和新模型必须是非空 Mesh')
    layers = obj.data.uv_layers
    if not layers or (name and name not in layers):
        raise ValueError(f'{obj.name}: 找不到 UV 层 {name!r}')
    return name or layers[0].name


def world_mesh(obj, depsgraph):
    evaluated = obj.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
    mesh.transform(evaluated.matrix_world)
    mesh.update()
    return mesh


def validate(settings, coverage_only=False):
    src, dst = settings.source, settings.target
    if src == dst:
        raise ValueError('原模型与新模型不能是同一个对象')
    su, tu = uv_name(src, settings.source_uv), uv_name(dst, settings.target_uv)
    uv = np.array([loop.uv[:] for loop in dst.data.uv_layers[tu].data])
    if not np.isfinite(uv).all() or uv.min() < -1e-5 or uv.max() > 1.00001:
        raise ValueError('新模型 UV 必须在 0–1 内（不支持 UDIM）')
    if not any(abs(sum(uv[p.loop_indices[i], 0] * uv[p.loop_indices[(i+1) % p.loop_total], 1]
                       - uv[p.loop_indices[(i+1) % p.loop_total], 0] * uv[p.loop_indices[i], 1]
                       for i in range(p.loop_total))) > 1e-12 for p in dst.data.polygons):
        raise ValueError('新模型 UV 面积为零')
    if not coverage_only and not settings.basecolor:
        raise ValueError('请指定 BaseColor 贴图')
    for key in (() if coverage_only else TEXTURE_KEYS):
        path = getattr(settings, key)
        if path and not Path(bpy.path.abspath(path)).is_file():
            raise ValueError(f'{key}: 文件不存在: {path}')
    if not settings.output_dir:
        raise ValueError('请选择输出目录')
    if not bpy.data.filepath and settings.output_dir.startswith('//'):
        raise ValueError('当前 blend 未保存，请使用绝对输出路径')
    return su, tu


def image_node(tree, image, uv):
    tex = tree.nodes.new('ShaderNodeTexImage'); tex.image = image
    tree.links.new(uv.outputs['UV'], tex.inputs['Vector'])
    return tex


def flip_green(tree, color):
    sep = tree.nodes.new('ShaderNodeSeparateColor')
    tree.links.new(color, sep.inputs['Color'])
    inv = tree.nodes.new('ShaderNodeMath'); inv.operation = 'SUBTRACT'
    inv.inputs[0].default_value = 1
    tree.links.new(sep.outputs['Green'], inv.inputs[1])
    combine = tree.nodes.new('ShaderNodeCombineColor')
    tree.links.new(sep.outputs['Red'], combine.inputs['Red'])
    tree.links.new(inv.outputs[0], combine.inputs['Green'])
    tree.links.new(sep.outputs['Blue'], combine.inputs['Blue'])
    return combine.outputs['Color']


def channel_socket(tree, tex, channel, grayscale=False):
    if channel == 'RGB':
        if not grayscale: return tex.outputs['Color']
        bw = tree.nodes.new('ShaderNodeRGBToBW')
        tree.links.new(tex.outputs['Color'], bw.inputs['Color'])
        return bw.outputs['Val']
    if channel == 'A':
        return tex.outputs['Alpha']
    split = tree.nodes.new('ShaderNodeSeparateColor')
    tree.links.new(tex.outputs['Color'], split.inputs['Color'])
    return split.outputs[{'R': 'Red', 'G': 'Green', 'B': 'Blue'}[channel]]


def build_source_material(settings, images, uv_name_, kind):
    mat = bpy.data.materials.new('_TR_' + kind); mat.use_nodes = True
    tree = mat.node_tree; tree.nodes.clear()
    uv = tree.nodes.new('ShaderNodeUVMap'); uv.uv_map = uv_name_
    output = tree.nodes.new('ShaderNodeOutputMaterial')
    if kind == 'NORMAL':
        bsdf = tree.nodes.new('ShaderNodeBsdfPrincipled')
        if images.get('normal'):
            tex = image_node(tree, images['normal'], uv)
            color = tex.outputs['Color']
            if settings.normal_input == 'DIRECTX':
                color = flip_green(tree, color)
            normal = tree.nodes.new('ShaderNodeNormalMap'); normal.uv_map = uv_name_
            tree.links.new(color, normal.inputs['Color'])
            tree.links.new(normal.outputs['Normal'], bsdf.inputs['Normal'])
        tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    else:
        emit = tree.nodes.new('ShaderNodeEmission')
        tree.links.new(emit.outputs[0], output.inputs['Surface'])
        if kind == 'BASECOLOR':
            tex = image_node(tree, images['basecolor'], uv)
            tree.links.new(channel_socket(tree, tex, settings.basecolor_channel), emit.inputs['Color'])
        elif kind == 'ORM':
            combine = tree.nodes.new('ShaderNodeCombineColor')
            for key, dest, channel, default in (
                ('ao', 'Red', settings.ao_channel, 1.0),
                ('roughness', 'Green', settings.rough_channel, settings.rough_default),
                ('metallic', 'Blue', settings.metal_channel, settings.metal_default),
            ):
                combine.inputs[dest].default_value = default
                if images.get(key):
                    tex = image_node(tree, images[key], uv)
                    socket = channel_socket(tree, tex, channel, grayscale=True)
                else:
                    continue
                tree.links.new(socket, combine.inputs[dest])
            tree.links.new(combine.outputs['Color'], emit.inputs['Color'])
        else:
            emit.inputs['Color'].default_value = (1, 1, 1, 1)
    return mat


def pixels(image):
    data = np.empty(len(image.pixels), dtype=np.float32)
    image.pixels.foreach_get(data)
    return data.reshape(-1, 4)


def save_png8(image, path, color=False):
    """Save an explicit 8-bit texture, without scene view/exposure transforms.

    Cycles float buffers contain scene-linear colors. Blender Image.save() on
    such buffers otherwise chooses 16-bit PNG, which is not the same UE import
    path as a regular 8-bit sRGB diffuse. Encode sRGB once, then store bytes.
    Non-color maps retain their numeric values (no gamma conversion).
    """
    data = pixels(image)
    if color:
        rgb = data[:, :3]
        rgb[:] = np.where(rgb <= 0.0031308, rgb * 12.92,
                          1.055 * np.maximum(rgb, 0) ** (1 / 2.4) - 0.055)
    np.clip(data, 0, 1, out=data)
    data[:, 3] = 1.0
    encoded = bpy.data.images.new('_TR_PNG8', width=image.size[0], height=image.size[1],
                                 alpha=False, float_buffer=False)
    try:
        encoded.colorspace_settings.name = 'sRGB' if color else 'Non-Color'
        encoded.use_view_as_render = False
        encoded.pixels.foreach_set(data.ravel())
        encoded.filepath_raw = str(path); encoded.file_format = 'PNG'; encoded.save()
    finally:
        bpy.data.images.remove(encoded)


def create_preview(context, settings, images, target_uv, normal_output=None):
    """Separate mesh and material; source target datablocks remain untouched."""
    mat = bpy.data.materials.new(settings.target.name + '_RebakePreview'); mat.use_nodes = True
    # Default node names are translated when "Translate New Data" is enabled.
    # Create nodes explicitly and retain references instead of looking up UI names.
    tree = mat.node_tree; tree.nodes.clear()
    bsdf = tree.nodes.new('ShaderNodeBsdfPrincipled')
    output = tree.nodes.new('ShaderNodeOutputMaterial')
    tree.links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
    uv = tree.nodes.new('ShaderNodeUVMap'); uv.uv_map = target_uv
    bc = image_node(tree, images['BaseColor'], uv)
    tree.links.new(bc.outputs['Color'], bsdf.inputs['Base Color'])
    orm = image_node(tree, images['ORM'], uv)
    tree.links.new(channel_socket(tree, orm, 'G'), bsdf.inputs['Roughness'])
    tree.links.new(channel_socket(tree, orm, 'B'), bsdf.inputs['Metallic'])
    n = image_node(tree, images['Normal'], uv); color = n.outputs['Color']
    if (normal_output or settings.normal_output) == 'DIRECTX':
        color = flip_green(tree, color)
    normal = tree.nodes.new('ShaderNodeNormalMap'); normal.uv_map = target_uv
    tree.links.new(color, normal.inputs['Color'])
    tree.links.new(normal.outputs['Normal'], bsdf.inputs['Normal'])
    obj = settings.target.copy(); obj.data = settings.target.data.copy()
    obj.name = settings.target.name + '_RebakePreview'
    context.collection.objects.link(obj)
    obj.data.materials.clear(); obj.data.materials.append(mat)
    for p in obj.data.polygons: p.material_index = 0
    for other in (settings.source, settings.target):
        other.hide_set(True); other.hide_render = True
    obj.hide_set(False); obj.hide_viewport = False; obj.hide_render = False
    for other in context.selected_objects: other.select_set(False)
    obj.select_set(True); context.view_layer.objects.active = obj
    return obj


def preview_from_output(context, settings, directory):
    """Recover an existing successful bake without rerunning Cycles."""
    run = Path(bpy.path.abspath(directory))
    report = json.loads((run / 'report.json').read_text(encoding='utf-8'))
    if report.get('status') != 'complete':
        raise ValueError('所选目录中的烘焙尚未成功完成')
    if report.get('coverage_only'):
        raise ValueError('此目录只有投射检查图，请选择完整烘焙目录')
    if not settings.source or not settings.target:
        raise ValueError('请先在面板选择原模型和新模型')
    if settings.target.name != report['target']:
        raise ValueError('请选择本次报告对应的新模型：' + report['target'])
    target_uv = uv_name(settings.target, report['target_uv'])
    images = {}
    for label in ('BaseColor', 'Normal', 'ORM'):
        path = Path(report['files'][label])
        if not path.is_file(): path = run / path.name
        if not path.is_file(): raise ValueError('找不到烘焙贴图：' + str(path))
        image = bpy.data.images.load(str(path), check_existing=True)
        image.colorspace_settings.name = 'sRGB' if label == 'BaseColor' else 'Non-Color'
        images[label] = image
    obj = create_preview(context, settings, images, target_uv, report['normal_output'])
    settings.last_output = str(run)
    return obj


def bake_textures(context, settings, progress=None, coverage_only=False):
    """Public API. Returns a JSON-serializable report; never saves input blend/FBX."""
    source_uv, target_uv = validate(settings, coverage_only=coverage_only)
    if context.mode != 'OBJECT':
        raise ValueError('请先切换到物体模式')
    root = Path(bpy.path.abspath(settings.output_dir)).resolve()
    prefix = re.sub(r'[^\w.-]+', '_', settings.prefix).strip('.') or 'T_Rebaked'
    run = root / (prefix + '_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    run.mkdir(parents=True, exist_ok=False)
    old_scene = context.window.scene if context.window else context.scene
    scene = None; meshes = []; materials = []; loaded = []; results = {}
    report = {'status': 'running', 'blender': bpy.app.version_string,
              'source': settings.source.name, 'target': settings.target.name,
              'source_uv': source_uv, 'target_uv': target_uv,
              'resolution': int(settings.resolution), 'orm_channels': 'R=AO G=Roughness B=Metallic',
              'addon_version': list(bl_info['version']), 'png_bit_depth': 8,
              'basecolor_encoding': 'sRGB; no view transform or exposure applied',
              'normal_input': settings.normal_input, 'normal_output': settings.normal_output,
              'extrusion': settings.extrusion, 'ray_distance': settings.ray_distance,
              'use_cage': True, 'cage': 'AUTO',
              'coverage_only': coverage_only,
              'inputs': {k: bpy.path.abspath(getattr(settings, k)) if getattr(settings, k) else None
                         for k in TEXTURE_KEYS},
              'input_channels': {'basecolor': settings.basecolor_channel, 'normal': 'RGB',
                                 'ao': settings.ao_channel, 'roughness': settings.rough_channel,
                                 'metallic': settings.metal_channel},
              'fallback_values': {'ao': 1.0, 'roughness': settings.rough_default,
                                  'metallic': settings.metal_default},
              'warnings': [], 'files': {}}
    try:
        images = {}
        for key in (() if coverage_only else TEXTURE_KEYS):
            if getattr(settings, key):
                im = bpy.data.images.load(bpy.path.abspath(getattr(settings, key)), check_existing=False)
                loaded.append(im); images[key] = im
                im.colorspace_settings.name = 'sRGB' if key == 'basecolor' else 'Non-Color'
                # Read RGB and A independently, including packed data textures.
                im.alpha_mode = 'CHANNEL_PACKED'
        scene = bpy.data.scenes.new('_TextureRebake')
        scene.render.engine = 'CYCLES'; scene.cycles.device = 'CPU'
        scene.cycles.samples = 1; scene.cycles.use_denoising = False
        scene.render.bake.target = 'IMAGE_TEXTURES'
        # Evaluate first, then use independent meshes. Constraints, parenting and transforms
        # are baked into world coordinates; scene visibility and materials are never edited.
        depsgraph = context.evaluated_depsgraph_get()
        objects = []
        for original, uv_ in ((settings.source, source_uv), (settings.target, target_uv)):
            mesh = world_mesh(original, depsgraph)
            meshes.append(mesh)
            obj = bpy.data.objects.new('_TR_' + original.name, mesh)
            scene.collection.objects.link(obj); objects.append(obj)
            if uv_ not in mesh.uv_layers: raise ValueError('修改器移除了选定的 UV 层')
            mesh.uv_layers.active = mesh.uv_layers[uv_]; mesh.uv_layers[uv_].active_render = True
            mesh.materials.clear()
            for p in mesh.polygons: p.material_index = 0
        src, dst = objects
        # Same evaluated world-space geometry and extrusion as the viewport overlay.
        mesh = dst.data.copy(); meshes.append(mesh)
        extrude_cage(mesh, settings.extrusion)
        cage = bpy.data.objects.new('_TR_Cage', mesh)
        scene.collection.objects.link(cage); cage.hide_render = True
        target_mat = bpy.data.materials.new('_TR_Target'); materials.append(target_mat)
        target_mat.use_nodes = True; dst.data.materials.append(target_mat)
        slot = target_mat.node_tree.nodes.new('ShaderNodeTexImage')
        target_mat.node_tree.nodes.active = slot
        if context.window: context.window.scene = scene
        layer = scene.view_layers[0]
        size = int(settings.resolution)

        def bake(kind, label, background, selected=True, margin=None):
            if progress: progress(label)
            mat = build_source_material(settings, images, source_uv if selected else target_uv, kind)
            materials.append(mat)
            src.data.materials.clear(); src.data.materials.append(mat)
            # Self-coverage uses the very same UVs but no selected-to-active projection.
            if not selected:
                dst.data.materials.clear(); dst.data.materials.append(mat)
                node = mat.node_tree.nodes.new('ShaderNodeTexImage'); mat.node_tree.nodes.active = node
            else:
                dst.data.materials.clear(); dst.data.materials.append(target_mat); node = slot
            im = bpy.data.images.new('_TR_' + label, width=size, height=size, alpha=True, float_buffer=True)
            # Bake into raw scene-linear values. An sRGB bake target can already
            # receive encoded values, including with a float buffer in Blender 5.3;
            # save_png8 must be the only stage applying the sRGB transfer curve.
            loaded.append(im); im.colorspace_settings.name = 'Non-Color'
            im.generated_color = background
            node.image = im
            src.select_set(selected, view_layer=layer); dst.select_set(True, view_layer=layer)
            layer.objects.active = dst
            with context.temp_override(scene=scene, view_layer=layer, object=dst, active_object=dst,
                                       selected_objects=[src, dst] if selected else [dst],
                                       selected_editable_objects=[src, dst] if selected else [dst]):
                result = bpy.ops.object.bake(type='NORMAL' if kind == 'NORMAL' else 'EMIT',
                    use_selected_to_active=selected, use_clear=False, use_cage=bool(cage and selected),
                    cage_object=cage.name if cage and selected else '',
                    cage_extrusion=0 if cage else settings.extrusion, max_ray_distance=settings.ray_distance,
                    margin=settings.margin if margin is None else margin, margin_type='EXTEND',
                    normal_space='TANGENT', normal_r='POS_X',
                    normal_g='NEG_Y' if settings.normal_output == 'DIRECTX' else 'POS_Y',
                    normal_b='POS_Z', uv_layer=target_uv)
                if result != {'FINISHED'}: raise RuntimeError(f'{label} 烘焙失败: {result}')
            return im

        coverage = bake('COVERAGE', 'Coverage', (0,0,0,1), margin=0)
        uv_mask = bake('COVERAGE', 'UVMask', (0,0,0,1), selected=False, margin=0)
        valid = pixels(uv_mask)[:, 0] > 0.5
        hit = pixels(coverage)[:, 0] > 0.5
        count = int(valid.sum())
        if not count: raise ValueError('新 UV 在当前分辨率下无有效像素')
        misses = int((valid & ~hit).sum()); report['uv_pixels'] = count
        report['unmapped_pixels'] = misses; report['coverage_percent'] = round(100*(1-misses/count), 4)
        if misses:
            report['warnings'].append(f'{misses} 个 UV 内像素未命中原模型；请检查切口/对齐/射线距离和 Coverage 图')
        coverage_path = run / (prefix + '_Coverage.png')
        save_png8(coverage, coverage_path)
        report['files']['Coverage'] = str(coverage_path)
        diagnostic = pixels(uv_mask)
        diagnostic[:, :3] = 0
        diagnostic[valid & hit, :3] = 1
        diagnostic[valid & ~hit, :3] = (1, 0, 0)
        uv_mask.pixels.foreach_set(diagnostic.ravel())
        miss_path = run / (prefix + '_Misses.png')
        save_png8(uv_mask, miss_path)
        report['files']['Misses'] = str(miss_path)
        if misses == count: raise ValueError('所有投射均未命中，请检查模型世界坐标是否重合；详见 Misses 图')
        if not settings.normal and not coverage_only:
            report['warnings'].append('未提供法线贴图：仅烘焙原模型几何法线')
        for kind, label, bg in (() if coverage_only else (
            ('BASECOLOR', 'BaseColor', (0,0,0,1)),
            ('ORM', 'ORM', (1,settings.rough_default,settings.metal_default,1)),
            ('NORMAL', 'Normal', (0.5,0.5,1,1)),
        )):
            im = bake(kind, label, bg)
            path = run / (prefix + '_' + label + '.png')
            save_png8(im, path, color=kind == 'BASECOLOR')
            # Reload actual PNGs for preview, releasing the float bake buffers afterwards.
            saved = bpy.data.images.load(str(path), check_existing=False)
            saved.colorspace_settings.name = 'sRGB' if kind == 'BASECOLOR' else 'Non-Color'
            saved.use_view_as_render = False
            results[label] = saved; report['files'][label] = str(path)
            slot.image = None; bpy.data.images.remove(im); loaded.remove(im)
        report['status'] = 'complete'
    except Exception as exc:
        report['status'] = 'failed'; report['error'] = str(exc)
        raise
    finally:
        if context.window: context.window.scene = old_scene
        if scene:
            for obj in list(scene.objects): bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.scenes.remove(scene)
        for mesh in meshes:
            if mesh.users == 0: bpy.data.meshes.remove(mesh)
        for mat in materials:
            if mat.users == 0: bpy.data.materials.remove(mat)
        for im in loaded:
            if im.users == 0: bpy.data.images.remove(im)
        (run / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    settings.last_output = str(run)
    if settings.preview and not coverage_only:
        try:
            create_preview(context, settings, results, target_uv)
            report['preview_status'] = 'complete'
        except Exception as exc:
            traceback.print_exc()
            report['preview_status'] = 'failed'; report['preview_error'] = str(exc)
            report['warnings'].append('贴图烘焙已完成，但创建预览失败；可从结果文件夹重建预览：' + str(exc))
    else:
        report['preview_status'] = 'disabled'
    (run / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


class TR_OT_bake(bpy.types.Operator):
    bl_idname = 'texture_rebake.bake'; bl_label = '烘焙到新 UV'; bl_description = '生成 BaseColor / Normal / ORM 和投射检查图'

    def execute(self, context):
        wm = context.window_manager; wm.progress_begin(0, 5); step = [0]
        def progress(label):
            step[0] += 1; wm.progress_update(step[0]); print('Texture Rebake:', label, flush=True)
        try:
            report = bake_textures(context, context.scene.texture_rebake, progress)
            if report['warnings']: self.report({'WARNING'}, '；'.join(report['warnings']))
            else: self.report({'INFO'}, '烘焙完成：' + context.scene.texture_rebake.last_output)
            return {'FINISHED'}
        except Exception as exc:
            traceback.print_exc(); self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        finally: wm.progress_end()


class TR_OT_coverage(bpy.types.Operator):
    bl_idname = 'texture_rebake.check_coverage'; bl_label = '仅检查投射（Coverage / Misses）'
    bl_description = '按当前分辨率仅烘焙覆盖图；Misses 图红色为 UV 内漏投，白色为命中，黑色为 UV 外'

    def execute(self, context):
        try:
            report = bake_textures(context, context.scene.texture_rebake, coverage_only=True)
            self.report({'WARNING'} if report['unmapped_pixels'] else {'INFO'},
                        f"投射覆盖率 {report['coverage_percent']}%；漏投 {report['unmapped_pixels']} 像素，详见输出目录 Misses 图")
            return {'FINISHED'}
        except Exception as exc:
            traceback.print_exc(); self.report({'ERROR'}, str(exc)); return {'CANCELLED'}


class TR_OT_preview(bpy.types.Operator):
    bl_idname = 'texture_rebake.preview'; bl_label = '从结果文件夹创建预览（不重烘焙）'
    bl_description = '选择包含 report.json 的已烘焙目录，使用已有贴图创建预览'
    bl_options = {'REGISTER', 'UNDO'}
    directory: StringProperty(subtype='DIR_PATH')

    def invoke(self, context, event):
        s = context.scene.texture_rebake
        self.directory = bpy.path.abspath(s.last_output or s.output_dir)
        context.window_manager.fileselect_add(self); return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            preview_from_output(context, context.scene.texture_rebake, self.directory)
            self.report({'INFO'}, '已用现有贴图创建预览，无需重新烘焙')
            return {'FINISHED'}
        except Exception as exc:
            traceback.print_exc(); self.report({'ERROR'}, str(exc)); return {'CANCELLED'}


class TR_PT_panel(bpy.types.Panel):
    bl_label = '旧贴图 → 新 UV'; bl_idname = 'TR_PT_panel'
    bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = 'Rebake'

    def draw(self, context):
        layout = self.layout; s = context.scene.texture_rebake
        col = layout.column(align=True)
        for key in ('source','target'): col.prop(s, key)
        for key, obj in (('source_uv',s.source), ('target_uv',s.target)):
            if obj: col.prop_search(s, key, obj.data, 'uv_layers')
        box = layout.box(); box.label(text='原模型纹理 / 读取通道')
        for key, channel in (('basecolor','basecolor_channel'), ('normal',None),
                             ('ao','ao_channel'), ('roughness','rough_channel'), ('metallic','metal_channel')):
            row = box.row(align=True); row.prop(s, key)
            if channel: row.prop(s, channel, text='')
            else: row.label(text='RGB')
        box.prop(s, 'rough_default')
        box.prop(s, 'metal_default')
        for key in ('normal_input','normal_output','resolution','margin'):
            layout.prop(s, key)
        box = layout.box(); box.label(text='投射 / Cage')
        box.prop(s, 'extrusion')
        box.prop(s, 'ray_distance')
        box.prop(s, 'show_cage')
        if s.show_cage:
            box.prop(s, 'cage_display'); box.prop(s, 'cage_color')
            if s.cage_display == 'SOLID': box.prop(s, 'cage_opacity')
        box.operator('texture_rebake.check_coverage', icon='VIEWZOOM')
        for key in ('output_dir','prefix','preview'): layout.prop(s, key)
        layout.operator('texture_rebake.bake', icon='RENDER_STILL')
        layout.operator('texture_rebake.preview', icon='MATERIAL')
        if s.last_output: layout.label(text='已输出至：' + s.last_output)


CLASSES = (TR_Settings, TR_OT_bake, TR_OT_coverage, TR_OT_preview, TR_PT_panel)


def register():
    global _overlay_handle
    for cls in CLASSES: bpy.utils.register_class(cls)
    bpy.types.Scene.texture_rebake = PointerProperty(type=TR_Settings)
    for handlers in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.load_post,
                     bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        handlers.append(invalidate_cage)
    if not bpy.app.background:
        _overlay_handle = bpy.types.SpaceView3D.draw_handler_add(draw_cage, (), 'WINDOW', 'POST_VIEW')


def unregister():
    global _overlay_handle
    if _overlay_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_overlay_handle, 'WINDOW'); _overlay_handle = None
    for handlers in (bpy.app.handlers.depsgraph_update_post, bpy.app.handlers.load_post,
                     bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        if invalidate_cage in handlers: handlers.remove(invalidate_cage)
    redraw_cage()
    del bpy.types.Scene.texture_rebake
    for cls in reversed(CLASSES): bpy.utils.unregister_class(cls)


if __name__ == '__main__': register()
