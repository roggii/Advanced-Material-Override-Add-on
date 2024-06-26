# SPDX-License-Identifier: GPL-3.0-or-later
# Advanced Material Override Addon
# Author: Nana Beniako
# Year: 2024
# License: GPL-3.0-or-later

bl_info = {
    "name": "Advanced Material Override",
    "blender": (3, 0, 0),
    "category": "Material",
    "version": (1, 0, 0),
    "author": "Nana Beniako",
    "description": "Dynamic material override with exclude list in Properties panel",
    "location": "Properties > Material Properties",
    "support": "COMMUNITY"
}

import bpy
import json

# Flag to track override status
override_active = False

class MaterialExcludeItem(bpy.types.PropertyGroup):
    material: bpy.props.PointerProperty(type=bpy.types.Material, name="Material")

class MaterialOverrideSettings(bpy.types.PropertyGroup):
    override_material: bpy.props.PointerProperty(type=bpy.types.Material, name="Override Material")
    exclude_materials: bpy.props.CollectionProperty(type=MaterialExcludeItem, name="Exclude Materials")
    exclude_materials_index: bpy.props.IntProperty(name="Exclude Materials Index", default=0)
    selected_material: bpy.props.PointerProperty(type=bpy.types.Material, name="Select Material to Exclude")

class MATERIAL_UL_override_exclude(bpy.types.UIList):
    """UI List to display excluded materials"""
    bl_idname = "MATERIAL_UL_override_exclude"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=item.material.name, icon='MATERIAL')
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text=item.material.name, icon='MATERIAL')

def get_all_objects(scene):
    all_objects = list(scene.objects)
    for obj in scene.objects:
        if obj.instance_collection:
            all_objects.extend(obj.instance_collection.objects)
    return all_objects

def store_original_materials(scene):
    all_objects = get_all_objects(scene)
    for obj in all_objects:
        if obj.type == 'MESH':
            materials = [slot.material.name if slot.material else None for slot in obj.material_slots]
            obj["_original_materials"] = json.dumps(materials)
            for slot in obj.material_slots:
                if slot.material:
                    slot.material.use_fake_user = True

    print("Original materials stored")

def apply_override_material(scene):
    settings = scene.advanced_material_override_settings
    override_material = settings.override_material

    if not override_material or not override_active:
        print("Override material not applied: override is not active or no override material set.")
        return

    exclude_materials = {item.material for item in settings.exclude_materials}

    all_objects = get_all_objects(scene)
    for obj in all_objects:
        if obj.type == 'MESH':
            for slot in obj.material_slots:
                if slot.material not in exclude_materials and slot.material != override_material:
                    slot.material = override_material

    print("Override material applied")

def revert_original_materials(scene):
    all_objects = get_all_objects(scene)
    for obj in all_objects:
        if obj.type == 'MESH' and "_original_materials" in obj:
            original_materials = json.loads(obj["_original_materials"])
            for i, mat_name in enumerate(original_materials):
                if mat_name:
                    obj.material_slots[i].material = bpy.data.materials.get(mat_name)
                    if obj.material_slots[i].material:
                        obj.material_slots[i].material.use_fake_user = False
            del obj["_original_materials"]

    print("Original materials reverted")

def pre_render_handler(scene):
    store_original_materials(scene)
    apply_override_material(scene)

def post_render_handler(scene):
    revert_original_materials(scene)

def load_post_handler(dummy):
    bpy.app.timers.register(delayed_store_original_materials)
    print("Load handler triggered: original materials will be stored after loading, override disabled")

def delayed_store_original_materials():
    scene = bpy.context.scene
    store_original_materials(scene)
    print("Delayed store: original materials stored")
    return None  # Return None to stop the timer

def clear_addon_data():
    global override_active
    override_active = False
    scene = bpy.context.scene
    settings = scene.advanced_material_override_settings
    settings.override_material = None
    settings.exclude_materials.clear()
    settings.exclude_materials_index = 0
    settings.selected_material = None
    print("Addon data cleared")

def create_generic_material():
    if "Generic" not in bpy.data.materials:
        generic_material = bpy.data.materials.new(name="Generic")
        generic_material.use_nodes = True
        print("Generic material created")
    else:
        print("Generic material already exists")

def tag_objects_with_generic_material(scene):
    generic_material = bpy.data.materials.get("Generic")
    if not generic_material:
        return

    for obj in get_all_objects(scene):
        if obj.type == 'MESH':
            if len(obj.material_slots) == 0:
                obj.data.materials.append(generic_material)
                print(f"Assigned Generic material to {obj.name}")
            else:
                if not any(slot.material for slot in obj.material_slots):
                    obj.material_slots[0].material = generic_material
                    print(f"Assigned Generic material to {obj.name}")

class OBJECT_OT_apply_advanced_material_override(bpy.types.Operator):
    """Apply Advanced Material Override"""
    bl_idname = "object.apply_advanced_material_override"
    bl_label = "Apply Advanced Material Override"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        settings = context.scene.advanced_material_override_settings
        return not override_active and settings.override_material is not None

    def execute(self, context):
        global override_active
        store_original_materials(context.scene)
        override_active = True
        apply_override_material(context.scene)
        tag_objects_with_generic_material(context.scene)  # Tag objects with Generic material
        context.view_layer.update()
        print("Override applied")
        return {'FINISHED'}

class OBJECT_OT_cancel_advanced_material_override(bpy.types.Operator):
    """Cancel Advanced Material Override and Restore Original Materials"""
    bl_idname = "object.cancel_advanced_material_override"
    bl_label = "Cancel Advanced Material Override"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return override_active or any("_original_materials" in obj for obj in context.scene.objects if obj.type == 'MESH')

    def execute(self, context):
        global override_active
        revert_original_materials(context.scene)
        tag_objects_with_generic_material(context.scene)  # Tag objects with Generic material
        context.view_layer.update()
        override_active = False
        print("Override cancelled")
        return {'FINISHED'}

class MATERIAL_OT_add_exclude_material(bpy.types.Operator):
    """Add selected material to exclude list"""
    bl_idname = "material.add_exclude_material"
    bl_label = "Add Exclude Material"

    @classmethod
    def poll(cls, context):
        return not override_active and context.scene.advanced_material_override_settings.selected_material is not None

    def execute(self, context):
        settings = context.scene.advanced_material_override_settings
        if settings.selected_material:
            item = settings.exclude_materials.add()
            item.material = settings.selected_material
            settings.selected_material = None
            update_override_button(context)
        return {'FINISHED'}

class MATERIAL_OT_list_action(bpy.types.Operator):
    """Remove materials from the exclude list"""
    bl_idname = "material.list_action"
    bl_label = "Material List Action"
    action: bpy.props.EnumProperty(items=(
        ('REMOVE', "Remove", ""),
        ('UP', "Up", ""),
        ('DOWN', "Down", ""),
    ))

    def invoke(self, context, event):
        settings = context.scene.advanced_material_override_settings
        idx = settings.exclude_materials_index

        if self.action == 'REMOVE':
            settings.exclude_materials.remove(idx)
            if settings.exclude_materials_index > 0:
                settings.exclude_materials_index -= 1

        elif self.action == 'UP' and idx > 0:
            settings.exclude_materials.move(idx, idx - 1)
            settings.exclude_materials_index -= 1

        elif self.action == 'DOWN' and idx < len(settings.exclude_materials) - 1:
            settings.exclude_materials.move(idx, idx + 1)
            settings.exclude_materials_index += 1

        update_override_button(context)
        return {"FINISHED"}

class MATERIAL_PT_override_panel(bpy.types.Panel):
    """Creates a Panel in the Material properties window"""
    bl_label = "Advanced Material Override"
    bl_idname = "MATERIAL_PT_advanced_override_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'material'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.advanced_material_override_settings

        layout.prop(settings, "override_material", text="Override Material")

        row = layout.row()
        row.template_list("MATERIAL_UL_override_exclude", "", settings, "exclude_materials", settings, "exclude_materials_index", rows=3)

        col = row.column(align=True)
        col.operator("material.list_action", icon='REMOVE', text="").action = 'REMOVE'
        col.operator("material.list_action", icon='TRIA_UP', text="").action = 'UP'
        col.operator("material.list_action", icon='TRIA_DOWN', text="").action = 'DOWN'

        layout.prop(settings, "selected_material", text="Select Material to Exclude")

        row = layout.row()
        row.enabled = not override_active
        row.operator("material.add_exclude_material", text="Add to Exclude List")
        row.operator("object.apply_advanced_material_override", text="Apply Override")

        cancel_row = layout.row()
        cancel_row.enabled = OBJECT_OT_cancel_advanced_material_override.poll(context)
        cancel_row.operator("object.cancel_advanced_material_override", text="Cancel Override")

def update_override_button(context):
    context.area.tag_redraw()

class MATERIAL_PT_addon_preferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    def draw(self, context):
        layout = self.layout
        layout.label(text="Advanced Material Override")
        layout.label(text="Author: Nana Beniako")
        layout.label(text="Version: 1.0.0")

def register():
    bpy.utils.register_class(MaterialExcludeItem)
    bpy.utils.register_class(MaterialOverrideSettings)
    bpy.utils.register_class(MATERIAL_UL_override_exclude)
    bpy.utils.register_class(OBJECT_OT_apply_advanced_material_override)
    bpy.utils.register_class(OBJECT_OT_cancel_advanced_material_override)
    bpy.utils.register_class(MATERIAL_OT_add_exclude_material)
    bpy.utils.register_class(MATERIAL_OT_list_action)
    bpy.utils.register_class(MATERIAL_PT_override_panel)
    bpy.utils.register_class(MATERIAL_PT_addon_preferences)

    bpy.types.Scene.advanced_material_override_settings = bpy.props.PointerProperty(type=MaterialOverrideSettings)

    bpy.app.handlers.load_post.append(load_post_handler)

    # Delayed creation of the "Generic" material to ensure Blender is fully initialized
    bpy.app.timers.register(create_generic_material)

def unregister():
    bpy.utils.unregister_class(MaterialExcludeItem)
    bpy.utils.unregister_class(MaterialOverrideSettings)
    bpy.utils.unregister_class(MATERIAL_UL_override_exclude)
    bpy.utils.unregister_class(OBJECT_OT_apply_advanced_material_override)
    bpy.utils.unregister_class(OBJECT_OT_cancel_advanced_material_override)
    bpy.utils.unregister_class(MATERIAL_OT_add_exclude_material)
    bpy.utils.unregister_class(MATERIAL_OT_list_action)
    bpy.utils.unregister_class(MATERIAL_PT_override_panel)
    bpy.utils.unregister_class(MATERIAL_PT_addon_preferences)

    del bpy.types.Scene.advanced_material_override_settings

    if load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_post_handler)

if __name__ == "__main__":
    register()