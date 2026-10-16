import json

import bpy


def _driver_count(id_block):
    animation_data = getattr(id_block, "animation_data", None)
    drivers = getattr(animation_data, "drivers", None) if animation_data else None
    return len(drivers) if drivers else 0


objects = []
for obj in bpy.data.objects:
    objects.append(
        {
            "name": obj.name,
            "type": obj.type,
            "parent": obj.parent.name if obj.parent else "",
            "visible": not bool(obj.hide_viewport),
            "hide_render": bool(obj.hide_render),
            "collections": [collection.name for collection in obj.users_collection],
            "location": [round(float(value), 4) for value in obj.location],
            "dimensions": [round(float(value), 4) for value in obj.dimensions],
            "drivers": _driver_count(obj),
        }
    )

armatures = []
for obj in bpy.data.objects:
    if obj.type != "ARMATURE":
        continue
    pose_bones = []
    constraint_types = {}
    custom_shape_count = 0
    for bone in obj.pose.bones:
        constraints = [constraint.type for constraint in bone.constraints]
        for constraint_type in constraints:
            constraint_types[constraint_type] = constraint_types.get(constraint_type, 0) + 1
        if bone.custom_shape:
            custom_shape_count += 1
        pose_bones.append(
            {
                "name": bone.name,
                "constraints": constraints,
                "custom_shape": bone.custom_shape.name if bone.custom_shape else "",
            }
        )
    armatures.append(
        {
            "name": obj.name,
            "bones": len(obj.data.bones),
            "pose_bones": pose_bones,
            "constraint_types": constraint_types,
            "custom_shape_count": custom_shape_count,
            "drivers": _driver_count(obj),
        }
    )

images = []
for image in bpy.data.images:
    images.append(
        {
            "name": image.name,
            "source": image.source,
            "filepath": image.filepath,
            "packed": bool(image.packed_file),
        }
    )

summary = {
    "blender_version": bpy.app.version_string,
    "scene": bpy.context.scene.name if bpy.context.scene else "",
    "objects": objects,
    "object_count": len(objects),
    "mesh_count": sum(1 for obj in bpy.data.objects if obj.type == "MESH"),
    "armatures": armatures,
    "armature_count": len(armatures),
    "materials": [material.name for material in bpy.data.materials],
    "images": images,
    "actions": [
        {
            "name": action.name,
            "fcurves": len(action.fcurves),
            "frame_range": [float(action.frame_range[0]), float(action.frame_range[1])],
        }
        for action in bpy.data.actions
    ],
    "collections": [collection.name for collection in bpy.data.collections],
}

print("MANNEQUIN_INSPECTION_JSON=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
