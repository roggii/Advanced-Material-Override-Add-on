# SPDX-License-Identifier: GPL-3.0-or-later
# Advanced Material Override Addon
# Author: Nana Beniako
# Year: 2024
# License: GPL-3.0-or-later

bl_info = {
    "name": "Advanced Material Override",
    "blender": (4, 0, 0),
    "category": "Material",
    "version": (1, 0, 0),
    "author": "Nana Beniako",
    "description": "Dynamic material override with exclude list in material properties panel",
    "location": "Properties > Material Properties",
    "support": "COMMUNITY"
}

import bpy
import json
import mathutils

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
            if item.material:
                layout.label(text=item.material.name, icon='MATERIAL')
            else:
                layout.label(text="None", icon='MATERIAL')
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            if item.material:
                layout.label(text=item.material.name, icon='MATERIAL')
            else:
                layout.label(text="None", icon='MATERIAL')

def get_mesh_data(obj):
    """Extract mesh data from an object in world coordinates."""
    world_matrix = obj.matrix_world
    vertices = [world_matrix @ v.co for v in obj.data.vertices]
    return tuple(sorted((round(v.x, 5), round(v.y, 5), round(v.z, 5)) for v in vertices))

def get_all_objects(scene):
    all_objects = list(scene.objects)
    for obj in scene.objects:
        if obj.instance_collection:
            all_objects.extend(obj.instance_collection.objects)
    return all_objects

def store_original_materials(objects):
    for obj in objects:
        if obj.type in {'MESH', 'CURVE'}:
            materials = [slot.material.name if slot.material else None for slot in obj.material_slots]
            obj["_original_materials"] = json.dumps(materials)
            for slot in obj.material_slots:
                if slot.material:
                    slot.material.use_fake_user = True
            print(f"Stored original materials for {obj.name}: {materials}")

            # Handle geometry nodes materials
            geom_node_materials = {}
            for modifier in obj.modifiers:
                if modifier.type == 'NODES' and modifier.node_group:
                    node_group = modifier.node_group
                    for node in node_group.nodes:
                        if node.type == 'SET_MATERIAL':
                            material = node.inputs['Material'].default_value
                            if material:
                                geom_node_materials[node.name] = material.name
                                material.use_fake_user = True
            if geom_node_materials:
                obj["_original_geom_node_materials"] = json.dumps(geom_node_materials)

def apply_override_material(objects, override_material, exclude_materials):
    for obj in objects:
        if obj.type in {'MESH', 'CURVE'}:
            for slot in obj.material_slots:
                if slot.material not in exclude_materials and slot.material != override_material:
                    slot.material = override_material
            print(f"Applied override material to {obj.name}")

            # Handle geometry nodes materials
            if "_original_geom_node_materials" in obj:
                geom_node_materials = json.loads(obj["_original_geom_node_materials"])
                for modifier in obj.modifiers:
                    if modifier.type == 'NODES' and modifier.node_group:
                        node_group = modifier.node_group
                        for node in node_group.nodes:
                            if node.type == 'SET_MATERIAL':
                                original_mat_name = geom_node_materials.get(node.name)
                                if original_mat_name and bpy.data.materials.get(original_mat_name) not in exclude_materials:
                                    node.inputs['Material'].default_value = override_material
                                    print(f"Applied override material to Set Material node {node.name} in {obj.name}")

def revert_original_materials(objects):
    for obj in objects:
        if obj.type in {'MESH', 'CURVE'} and "_original_materials" in obj:
            original_materials = json.loads(obj["_original_materials"])
            for i, mat_name in enumerate(original_materials):
                if mat_name:
                    obj.material_slots[i].material = bpy.data.materials.get(mat_name)
                    if obj.material_slots[i].material:
                        obj.material_slots[i].material.use_fake_user = False
            print(f"Reverted materials for {obj.name} to {original_materials}")
            del obj["_original_materials"]

            # Handle geometry nodes materials
            if "_original_geom_node_materials" in obj:
                original_geom_node_materials = json.loads(obj["_original_geom_node_materials"])
                for modifier in obj.modifiers:
                    if modifier.type == 'NODES' and modifier.node_group:
                        node_group = modifier.node_group
                        for node in node_group.nodes:
                            if node.type == 'SET_MATERIAL':
                                original_mat_name = original_geom_node_materials.get(node.name)
                                if original_mat_name:
                                    node.inputs['Material'].default_value = bpy.data.materials.get(original_mat_name)
                                    print(f"Reverted Set Material node {node.name} in {obj.name} to {original_mat_name}")
                del obj["_original_geom_node_materials"]

def pre_render_handler(scene):
    all_objects = get_all_objects(scene)
    store_original_materials(all_objects)
    apply_override_material(all_objects, scene.advanced_material_override_settings.override_material, {item.material for item in scene.advanced_material_override_settings.exclude_materials})

def post_render_handler(scene):
    all_objects = get_all_objects(scene)
    revert_original_materials(all_objects)

def load_post_handler(dummy):
    bpy.app.timers.register(delayed_store_original_materials)
    print("Load handler triggered: original materials will be stored after loading, override disabled")

def delayed_store_original_materials():
    scene = bpy.context.scene
    all_objects = get_all_objects(scene)
    store_original_materials(all_objects)
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

def tag_objects_with_generic_material(objects):
    generic_material = bpy.data.materials.get("Generic")
    if not generic_material:
        return

    for obj in objects:
        if obj.type in {'MESH', 'CURVE'}:
            if len(obj.material_slots) == 0:
                obj.data.materials.append(generic_material)
                print(f"Assigned Generic material to {obj.name} due to no material slots")
            else:
                for slot in obj.material_slots:
                    if slot.material is None:
                        slot.material = generic_material
                        print(f"Assigned Generic material to empty slot in {obj.name}")

def copy_instanced_collections_to_new_collection():
    scene = bpy.context.scene
    new_collection = bpy.data.collections.get("Instance Definitions")
    
    if not new_collection:
        new_collection = bpy.data.collections.new("Instance Definitions")
        scene.collection.children.link(new_collection)
    
    # Hide the "Instance Definitions" collection
    new_collection.hide_viewport = True
    new_collection.hide_render = True
    new_collection.hide_select = True

    settings = scene.advanced_material_override_settings
    override_material = settings.override_material

    all_objects = []

    for obj in scene.objects:
        if obj.instance_collection:
            instance_collection_copy = obj.instance_collection.copy()
            new_collection.children.link(instance_collection_copy)

            # Use temp override context to perform operations in the background
            override_context = bpy.context.copy()
            override_context['selected_objects'] = instance_collection_copy.objects
            override_context['active_object'] = None

            with bpy.context.temp_override(**override_context):
                bpy.ops.object.select_all(action='DESELECT')
                for instance_obj in instance_collection_copy.objects:
                    if instance_obj.type in {'MESH', 'CURVE'}:  # Include mesh and curve objects
                        instance_obj.select_set(True)
                bpy.ops.object.make_local(type='ALL')

            # Store original materials right after making instances real
            store_original_materials(instance_collection_copy.objects)

            all_objects.extend([instance_obj for instance_obj in instance_collection_copy.objects if instance_obj.type in {'MESH', 'CURVE'}])

    return all_objects

class OBJECT_OT_apply_material_override(bpy.types.Operator):
    """Apply Material Override"""
    bl_idname = "object.apply_material_override"
    bl_label = "Apply Material Override"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        settings = context.scene.advanced_material_override_settings
        return not override_active and settings.override_material is not None

    def execute(self, context):
        global override_active
        scene = context.scene
        instanced_objects = copy_instanced_collections_to_new_collection()
        all_objects = get_all_objects(scene) + instanced_objects
        tag_objects_with_generic_material(all_objects)  # Tag objects with Generic material
        store_original_materials(all_objects)
        override_active = True
        apply_override_material(all_objects, scene.advanced_material_override_settings.override_material, {item.material for item in scene.advanced_material_override_settings.exclude_materials})
        context.view_layer.update()
        print("Override applied")
        return {'FINISHED'}

class OBJECT_OT_cancel_material_override(bpy.types.Operator):
    """Cancel Material Override and Restore Original Materials"""
    bl_idname = "object.cancel_material_override"
    bl_label = "Cancel Material Override"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return override_active or any("_original_materials" in obj for obj in context.scene.objects if obj.type in {'MESH', 'CURVE'})

    def execute(self, context):
        global override_active
        scene = context.scene
        all_objects = get_all_objects(scene)
        revert_original_materials(all_objects)

        # Delete the "Instance Definitions" collection
        instance_definitions_collection = bpy.data.collections.get("Instance Definitions")
        if instance_definitions_collection:
            bpy.data.collections.remove(instance_definitions_collection)
            print("Deleted 'Instance Definitions' collection")

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
            # Check if the material is already in the exclude list
            for item in settings.exclude_materials:
                if item.material == settings.selected_material:
                    self.report({'WARNING'}, "Material is already in the exclude list")
                    return {'CANCELLED'}
            item = settings.exclude_materials.add()
            item.material = settings.selected_material
            settings.selected_material = None
            update_override_button(context)
        return {'FINISHED'}

class MATERIAL_OT_list_action(bpy.types.Operator):
    """Remove selected material from exclude list"""
    bl_idname = "material.list_action"
    bl_label = "Remove Selected Material from Exclude List"
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

class MATERIAL_OT_sort_exclude_materials(bpy.types.Operator):
    """Sort excluded materials alphabetically"""
    bl_idname = "material.sort_exclude_materials"
    bl_label = "Sort Excluded Materials"

    def execute(self, context):
        settings = context.scene.advanced_material_override_settings
        exclude_materials_list = sorted(settings.exclude_materials, key=lambda item: (item.material.name if item.material else ""))

        # Clear and re-add items to sort
        items = [(item.material, item.name) for item in exclude_materials_list]
        settings.exclude_materials.clear()
        for material, name in items:
            item = settings.exclude_materials.add()
            item.material = material

        print("Sorted exclude materials:", [item.material.name if item.material else "None" for item in settings.exclude_materials])
        return {'FINISHED'}

class MATERIAL_OT_clear_exclude_list(bpy.types.Operator):
    """Clear all materials from the exclude list"""
    bl_idname = "material.clear_exclude_list"
    bl_label = "Clear Exclude List"

    def execute(self, context):
        settings = context.scene.advanced_material_override_settings
        settings.exclude_materials.clear()
        print("Exclude list cleared")
        return {'FINISHED'}

class OBJECT_OT_purge_duplicate_geometry(bpy.types.Operator):
    """Purge Duplicate Geometry Objects"""
    bl_idname = "object.purge_duplicate_geometry"
    bl_label = "Purge Duplicate Geometry"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Dictionary to store objects by their mesh data and location
        object_data_dict = {}

        # Iterate through all objects in the scene
        for obj in list(bpy.context.scene.objects):
            # Ensure the object is a mesh
            if obj.type == 'MESH':
                mesh_data = get_mesh_data(obj)
                location = tuple(round(coord, 5) for coord in obj.location)
                
                # Combine mesh data and location as a key
                key = (mesh_data, location)
                
                if key in object_data_dict:
                    # If an object with the same mesh data and location exists, delete the duplicate
                    print(f"Removing duplicate object: {obj.name}")
                    bpy.data.objects.remove(obj, do_unlink=True)
                else:
                    # Otherwise, store this object in the dictionary
                    object_data_dict[key] = obj

        print("Duplicate geometry purge completed.")
        return {'FINISHED'}

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
        col.operator("material.sort_exclude_materials", icon='SORTALPHA', text="")
        col.operator("material.clear_exclude_list", icon='X', text="")

        layout.prop(settings, "selected_material", text="Select Material to Exclude")

        row = layout.row()
        row.enabled = not override_active
        row.operator("material.add_exclude_material", text="Add to Exclude List")
        row.operator("object.apply_material_override", text="Apply Override")

        cancel_row = layout.row()
        cancel_row.enabled = OBJECT_OT_cancel_material_override.poll(context)
        cancel_row.operator("object.cancel_material_override", text="Cancel Override")

        layout.separator()

        row = layout.row()
        row.operator("object.delete_empty_material_slots", text="Purge Unused Material Slots")

        row = layout.row()
        row.operator("object.purge_duplicate_geometry", text="Purge Duplicate Geometry")

def update_override_button(context):
    context.area.tag_redraw()

class OBJECT_OT_delete_empty_material_slots(bpy.types.Operator):
    """Delete empty material slots from all mesh objects in the scene"""
    bl_idname = "object.delete_empty_material_slots"
    bl_label = "Purge Unused Material Slots"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        for obj in bpy.context.scene.objects:
            if obj.type == 'MESH':  # Only process mesh objects
                # Switch to object mode if necessary
                if bpy.context.object and bpy.context.object.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')

                for i in range(len(obj.material_slots) - 1, -1, -1):
                    if obj.material_slots[i].material is None:
                        obj.active_material_index = i
                        bpy.context.view_layer.objects.active = obj  # Set the active object
                        bpy.ops.object.material_slot_remove()  # Properly remove the material slot
                        
        print("Empty material slots removed from all mesh objects in the scene.")
        return {'FINISHED'}

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
    bpy.utils.register_class(OBJECT_OT_apply_material_override)
    bpy.utils.register_class(OBJECT_OT_cancel_material_override)
    bpy.utils.register_class(MATERIAL_OT_add_exclude_material)
    bpy.utils.register_class(MATERIAL_OT_list_action)
    bpy.utils.register_class(MATERIAL_OT_sort_exclude_materials)
    bpy.utils.register_class(MATERIAL_OT_clear_exclude_list)
    bpy.utils.register_class(MATERIAL_PT_override_panel)
    bpy.utils.register_class(OBJECT_OT_delete_empty_material_slots)
    bpy.utils.register_class(OBJECT_OT_purge_duplicate_geometry)
    bpy.utils.register_class(MATERIAL_PT_addon_preferences)

    bpy.types.Scene.advanced_material_override_settings = bpy.props.PointerProperty(type=MaterialOverrideSettings)

    bpy.app.handlers.load_post.append(load_post_handler)

    # Delayed creation of the "Generic" material to ensure Blender is fully initialized
    bpy.app.timers.register(create_generic_material)

def unregister():
    bpy.utils.unregister_class(MaterialExcludeItem)
    bpy.utils.unregister_class(MaterialOverrideSettings)
    bpy.utils.unregister_class(MATERIAL_UL_override_exclude)
    bpy.utils.unregister_class(OBJECT_OT_apply_material_override)
    bpy.utils.unregister_class(OBJECT_OT_cancel_material_override)
    bpy.utils.unregister_class(MATERIAL_OT_add_exclude_material)
    bpy.utils.unregister_class(MATERIAL_OT_list_action)
    bpy.utils.unregister_class(MATERIAL_OT_sort_exclude_materials)
    bpy.utils.unregister_class(MATERIAL_OT_clear_exclude_list)
    bpy.utils.unregister_class(MATERIAL_PT_override_panel)
    bpy.utils.unregister_class(OBJECT_OT_delete_empty_material_slots)
    bpy.utils.unregister_class(OBJECT_OT_purge_duplicate_geometry)
    bpy.utils.unregister_class(MATERIAL_PT_addon_preferences)

    del bpy.types.Scene.advanced_material_override_settings

    if load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_post_handler)

if __name__ == "__main__":
    register()
