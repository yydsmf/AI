import os
import sys

import bpy


def _output_path():
    if "--" not in sys.argv:
        raise RuntimeError("缺少输出文件路径")
    args = sys.argv[sys.argv.index("--") + 1 :]
    if not args:
        raise RuntimeError("缺少输出文件路径")
    return os.path.abspath(args[0])


def _simple_material(name, base_color, metallic=0.0, roughness=0.48):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.inputs["Base Color"].default_value = base_color
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    material.node_tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return material


output_path = _output_path()
armature = bpy.data.objects.get("Armadura Hombre")
body = bpy.data.objects.get("Muñeco")
if armature is None or armature.type != "ARMATURE":
    raise RuntimeError("没有找到原始人偶骨骼 Armadura Hombre")
if body is None or body.type != "MESH":
    raise RuntimeError("没有找到原始人偶网格 Muñeco")

required_objects = {armature, body}
required_objects.update(armature.children)
for pose_bone in armature.pose.bones:
    if pose_bone.custom_shape:
        required_objects.add(pose_bone.custom_shape)
    for constraint in pose_bone.constraints:
        target = getattr(constraint, "target", None)
        if target:
            required_objects.add(target)

animation_data = armature.animation_data
if animation_data and animation_data.drivers:
    for fcurve in animation_data.drivers:
        for variable in fcurve.driver.variables:
            for target in variable.targets:
                if isinstance(target.id, bpy.types.Object):
                    required_objects.add(target.id)

for obj in list(bpy.data.objects):
    if obj not in required_objects:
        bpy.data.objects.remove(obj, do_unlink=True)

for collection in list(bpy.data.collections):
    if collection.name not in {"Armadura - Muñeco", "集合 2", "集合 6"}:
        bpy.data.collections.remove(collection)

main_collection = bpy.data.collections.get("Armadura - Muñeco")
if main_collection is None:
    main_collection = bpy.data.collections.new("Director Mannequin")
    bpy.context.scene.collection.children.link(main_collection)
main_collection.name = "Director Mannequin"

widgets_collection = bpy.data.collections.get("集合 6")
if widgets_collection is None:
    widgets_collection = bpy.data.collections.new("Director Mannequin Widgets")
    bpy.context.scene.collection.children.link(widgets_collection)
widgets_collection.name = "Director Mannequin Widgets"
widgets_collection.hide_render = True
widgets_collection.hide_viewport = True

ui_collection = bpy.data.collections.get("集合 2")
if ui_collection:
    ui_collection.name = "Director Mannequin Rig UI"
    ui_collection.hide_render = True

armature.name = "Director Mannequin Rig"
armature.data.name = "Director Mannequin Rig"
armature.show_in_front = True
body.name = "Director Mannequin Body"
body.data.name = "Director Mannequin Body"

for pose_bone in armature.pose.bones:
    pose_bone.matrix_basis.identity()
spine = armature.pose.bones.get("spine")
if spine is not None:
    for constraint in list(spine.constraints):
        if (
            constraint.type == "COPY_ROTATION"
            and getattr(constraint, "target", None) is armature
            and getattr(constraint, "subtarget", "") == "chest"
        ):
            spine.constraints.remove(constraint)
bpy.context.view_layer.update()

body_material = _simple_material(
    "Director Mannequin Body Material",
    (0.08, 0.38, 0.84, 1.0),
    metallic=0.05,
    roughness=0.42,
)
joint_material = _simple_material(
    "Director Mannequin Joint Material",
    (0.035, 0.045, 0.06, 1.0),
    metallic=0.32,
    roughness=0.30,
)
if len(body.data.materials) < 1:
    body.data.materials.append(body_material)
else:
    body.data.materials[0] = body_material
if len(body.data.materials) < 2:
    body.data.materials.append(joint_material)
else:
    body.data.materials[1] = joint_material

for obj in required_objects:
    if obj is body or obj is armature:
        continue
    obj.hide_render = True

for image in list(bpy.data.images):
    bpy.data.images.remove(image)
for material in list(bpy.data.materials):
    if material not in {body_material, joint_material} and material.users == 0:
        bpy.data.materials.remove(material)

scene = bpy.context.scene
scene.name = "Director Mannequin Template"
scene.frame_start = 1
scene.frame_end = 96
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 1280
scene.render.resolution_y = 720

armature["gpt_director_asset_source"] = "BlendSwap"
armature["gpt_director_asset_source_url"] = "https://blendswap.com/blend/13034"
armature["gpt_director_asset_author"] = "jgilhutton / Juan Ignacio"
armature["gpt_director_asset_license"] = "CC-BY"
armature["gpt_director_asset_name"] = "Wooden mannequin - Rigged"
body["gpt_director_recolor_material"] = body_material.name

os.makedirs(os.path.dirname(output_path), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=output_path, compress=True)
print(
    "DIRECTOR_MANNEQUIN_CONVERTED",
    output_path,
    "objects",
    len(bpy.data.objects),
    "bones",
    len(armature.data.bones),
)
