import os
import sys

import bpy
from mathutils import Matrix, Vector


SOFA_OBJECT_NAMES = (
    "Array Sofa 2L",
    "Almofada",
    "Almofada.001",
    "Almofada.002",
)
TABLE_COLLECTION_NAME = "big table"
SOFA_COLLECTION_NAME = "Director Modern Sofa"
TABLE_TARGET_COLLECTION_NAME = "Director Modern Coffee Table"


def _arguments():
    if "--" not in sys.argv:
        raise RuntimeError("缺少输出路径和桌子源文件路径")
    args = sys.argv[sys.argv.index("--") + 1 :]
    if len(args) < 2:
        raise RuntimeError("用法：输出.blend 桌子源文件.blend")
    return os.path.abspath(args[0]), os.path.abspath(args[1])


def _world_bounds(objects):
    points = []
    for obj in objects:
        if obj is None or obj.type != "MESH":
            continue
        points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    if not points:
        raise RuntimeError("资产没有可用的网格边界")
    return (
        Vector(
            (
                min(point.x for point in points),
                min(point.y for point in points),
                min(point.z for point in points),
            )
        ),
        Vector(
            (
                max(point.x for point in points),
                max(point.y for point in points),
                max(point.z for point in points),
            )
        ),
    )


def _unlink_and_link(obj, collection):
    for owner in list(obj.users_collection):
        owner.objects.unlink(obj)
    collection.objects.link(obj)


def _normalize(objects, target_collection, scale=1.0):
    minimum, maximum = _world_bounds(objects)
    origin = Vector(
        (
            (minimum.x + maximum.x) * 0.5,
            (minimum.y + maximum.y) * 0.5,
            minimum.z,
        )
    )
    transform = Matrix.Scale(float(scale), 4) @ Matrix.Translation(-origin)
    for obj in objects:
        world = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = transform @ world
        _unlink_and_link(obj, target_collection)
    return _world_bounds(objects)


def _add_template_root(name, kind, collection, objects, source_url, author):
    root = bpy.data.objects.new(name, None)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = 0.36
    root.show_name = True
    root.hide_render = True
    collection.objects.link(root)
    root["gpt_director_asset_template_root"] = True
    root["gpt_director_furniture_kind"] = kind
    root["gpt_director_asset_source"] = "BlendSwap"
    root["gpt_director_asset_source_url"] = source_url
    root["gpt_director_asset_author"] = author
    root["gpt_director_asset_license"] = "CC0"
    for obj in objects:
        matrix = obj.matrix_world.copy()
        obj.parent = root
        obj.matrix_parent_inverse = root.matrix_world.inverted()
        obj.matrix_world = matrix
        obj["gpt_director_furniture_kind"] = kind
        obj["gpt_director_asset_source"] = "BlendSwap"
        obj["gpt_director_asset_license"] = "CC0"
    return root


def _remove_unused_data():
    groups = (
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.curves,
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.textures,
        bpy.data.images,
    )
    for group in groups:
        for item in list(group):
            if item.users == 0:
                group.remove(item)


output_path, table_source_path = _arguments()
if not os.path.exists(table_source_path):
    raise RuntimeError("桌子源文件不存在：" + table_source_path)

sofa_objects = []
for name in SOFA_OBJECT_NAMES:
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "MESH":
        raise RuntimeError("沙发源文件缺少对象：" + name)
    sofa_objects.append(obj)

with bpy.data.libraries.load(table_source_path, link=False) as (data_from, data_to):
    if TABLE_COLLECTION_NAME not in data_from.collections:
        raise RuntimeError("桌子源文件缺少集合：" + TABLE_COLLECTION_NAME)
    data_to.collections = [TABLE_COLLECTION_NAME]

table_source_collection = data_to.collections[0]
if table_source_collection is None:
    raise RuntimeError("无法载入桌子集合：" + TABLE_COLLECTION_NAME)
bpy.context.scene.collection.children.link(table_source_collection)
table_objects = [obj for obj in table_source_collection.all_objects if obj.type == "MESH"]
if len(table_objects) != 2:
    raise RuntimeError("桌子集合对象数量异常：" + str(len(table_objects)))

keep_objects = set(sofa_objects + table_objects)
for obj in list(bpy.data.objects):
    if obj not in keep_objects:
        bpy.data.objects.remove(obj, do_unlink=True)

sofa_collection = bpy.data.collections.new(SOFA_COLLECTION_NAME)
table_collection = bpy.data.collections.new(TABLE_TARGET_COLLECTION_NAME)
bpy.context.scene.collection.children.link(sofa_collection)
bpy.context.scene.collection.children.link(table_collection)

sofa_bounds = _normalize(sofa_objects, sofa_collection, scale=1.0)
table_bounds = _normalize(table_objects, table_collection, scale=0.40)

sofa_names = (
    "Director Modern Sofa Body",
    "Director Modern Sofa Cushion A",
    "Director Modern Sofa Cushion B",
    "Director Modern Sofa Cushion C",
)
for obj, name in zip(sofa_objects, sofa_names):
    obj.name = name
    if obj.data:
        obj.data.name = name + " Mesh"

table_objects.sort(key=lambda obj: float(obj.dimensions.z), reverse=True)
table_objects[0].name = "Director Modern Coffee Table Base"
table_objects[1].name = "Director Modern Coffee Table Top"
for obj in table_objects:
    if obj.data:
        obj.data.name = obj.name + " Mesh"

sofa_root = _add_template_root(
    "Director Modern Sofa Template Root",
    "sofa",
    sofa_collection,
    sofa_objects,
    "https://blendswap.com/blend/26538",
    "LauroVictorDesign",
)
table_root = _add_template_root(
    "Director Modern Coffee Table Template Root",
    "table",
    table_collection,
    table_objects,
    "https://blendswap.com/blend/27096",
    "Neobox",
)

sofa_collection["gpt_director_furniture_kind"] = "sofa"
table_collection["gpt_director_furniture_kind"] = "table"
sofa_collection["gpt_director_asset_license"] = "CC0"
table_collection["gpt_director_asset_license"] = "CC0"

for collection in list(bpy.data.collections):
    if collection not in {sofa_collection, table_collection}:
        bpy.data.collections.remove(collection)

_remove_unused_data()
scene = bpy.context.scene
scene.name = "Director Modern Furniture Pack"
scene.frame_start = 1
scene.frame_end = 96
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene["gpt_director_asset_pack"] = "modern_furniture_pack_293"
scene["gpt_director_asset_license"] = "CC0"
scene["gpt_director_blender_compatibility"] = "2.93+"

try:
    bpy.ops.file.pack_all()
except Exception:
    pass

os.makedirs(os.path.dirname(output_path), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=output_path, compress=True)
print(
    "DIRECTOR_FURNITURE_CONVERTED",
    output_path,
    "sofa_size",
    [round(float(sofa_bounds[1][i] - sofa_bounds[0][i]), 4) for i in range(3)],
    "table_size",
    [round(float(table_bounds[1][i] - table_bounds[0][i]), 4) for i in range(3)],
    "objects",
    len(bpy.data.objects),
    "materials",
    len(bpy.data.materials),
    "images",
    len(bpy.data.images),
)
