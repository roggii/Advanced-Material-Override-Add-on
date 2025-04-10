def detect_probable_override() -> bool:
    """Detect if the current scene likely has an active material override that wasn't properly saved."""
    
    # Check if we have explicit override state saved
    scene = bpy.context.scene
    if "override_active" in scene and scene["override_active"]:
        return True
        
    # No explicit state, check for patterns consistent with an override
    objects_with_materials = [obj for obj in scene.objects if obj.type in {'MESH', 'CURVE'} and len(obj.material_slots) > 0]
    if not objects_with_materials:
        return False
        
    # Count how many objects have each material
    material_usage = {}
    for obj in objects_with_materials:
        for slot in obj.material_slots:
            if slot.material:
                if slot.material.name not in material_usage:
                    material_usage[slot.material.name] = 0
                material_usage[slot.material.name] += 1
    
    # If no materials found, no override
    if not material_usage:
        return False
        
    # Find most common material
    most_common_material = max(material_usage.items(), key=lambda x: x[1])
    material_name, usage_count = most_common_material
    
    # Check for materials with fake users (possible stored originals)
    materials_with_fake_users = [mat for mat in bpy.data.materials 
                                 if mat.use_fake_user and mat.name != material_name]
    
    # Heuristics for probable override:
    # 1. One material is used significantly more than average (potential override material)
    avg_usage = sum(material_usage.values()) / len(material_usage)
    # 2. Many materials have fake users but aren't actively used (stored originals)
    # 3. There are custom properties on objects that might be related to override
    objects_with_custom_props = [obj for obj in objects_with_materials 
                                if "_original_materials" in obj or "_had_no_materials" in obj]
    
    # Check if this matches the pattern of an override
    if (usage_count > avg_usage * 2 and  # One material is used much more than others
        (len(materials_with_fake_users) > 3 or  # Multiple unused materials with fake users
         len(objects_with_custom_props) > 0)):  # Objects have override-related custom properties
        
        # Get the potential override material
        potential_override = bpy.data.materials.get(material_name)
        if potential_override:
            # Set as the override material
            scene.advanced_material_override_settings.override_material = potential_override
            return True
    
    return False# SPDX-License-Identifier: GPL-3.0-or-later
# Advanced Material Override Addon
# Author: Nana Beniako
# Year: 2024
# License: GPL-3.0-or-later

bl_info = {
    "name": "Advanced Material Override",
    "blender": (4, 0, 0),
    "category": "Material",
    "version": (1, 1, 0),
    "author": "Nana Beniako",
    "description": "Dynamic material override with exclude list in material properties panel",
    "location": "Properties > Material Properties",
    "support": "COMMUNITY"
}

import bpy
import json
from typing import Set, List, Dict, Any, Optional, Tuple

# Global variables
override_active = False

# -----------------------------------------------------------------------------
# Property Groups
# -----------------------------------------------------------------------------

class MaterialExcludeItem(bpy.types.PropertyGroup):
    """Material to be excluded from override"""
    material: bpy.props.PointerProperty(type=bpy.types.Material, name="Material")

class MaterialOverrideSettings(bpy.types.PropertyGroup):
    """Settings for material override"""
    override_material: bpy.props.PointerProperty(
        type=bpy.types.Material, 
        name="Override Material",
        description="Material to use for overriding"
    )
    exclude_materials: bpy.props.CollectionProperty(
        type=MaterialExcludeItem, 
        name="Exclude Materials",
        description="Materials to exclude from override"
    )
    exclude_materials_index: bpy.props.IntProperty(
        name="Exclude Materials Index", 
        default=0,
        description="Index of the selected exclude material"
    )
    selected_material: bpy.props.PointerProperty(
        type=bpy.types.Material, 
        name="Select Material to Exclude",
        description="Select a material to add to the exclude list"
    )
    keep_generic_material: bpy.props.BoolProperty(
        name="Keep Generic Material",
        description="Keep the Generic material on objects after cancelling override",
        default=False
    )

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def get_mesh_data(obj) -> Tuple:
    """Extract mesh data from an object in world coordinates."""
    world_matrix = obj.matrix_world
    vertices = [world_matrix @ v.co for v in obj.data.vertices]
    return tuple(sorted((round(v.x, 5), round(v.y, 5), round(v.z, 5)) for v in vertices))

def get_all_objects(scene) -> List:
    """Get all objects including those in instanced collections."""
    all_objects = list(scene.objects)
    for obj in scene.objects:
        if obj.instance_collection:
            all_objects.extend(obj.instance_collection.objects)
    return all_objects

def create_generic_material() -> None:
    """Create a generic material if it doesn't exist already."""
    if "Generic" not in bpy.data.materials:
        generic_material = bpy.data.materials.new(name="Generic")
        generic_material.use_nodes = True
        
        # Use a subtle light gray to make it identifiable but not distracting
        generic_material.diffuse_color = (0.8, 0.8, 0.8, 1.0)  # Light gray
        
        # Set up default principled BSDF values
        nodes = generic_material.node_tree.nodes
        principled = nodes.get('Principled BSDF')
        if principled:
            principled.inputs['Base Color'].default_value = (0.8, 0.8, 0.8, 1.0)  # Light gray
            principled.inputs['Roughness'].default_value = 0.5  # Default roughness
            principled.inputs['Metallic'].default_value = 0.0  # Non-metallic
            
            # Check if the 'Specular' input exists before trying to set it
            # Some Blender versions might have different input names
            if 'Specular' in principled.inputs:
                principled.inputs['Specular'].default_value = 0.5  # Default specular
            elif 'Specular IOR Level' in principled.inputs:
                principled.inputs['Specular IOR Level'].default_value = 0.5  # For Blender 4.0
                
        print("Generic material created")

def tag_objects_with_generic_material(objects: List) -> None:
    """Assign Generic material to objects with no materials or empty slots."""
    generic_material = bpy.data.materials.get("Generic")
    if not generic_material:
        create_generic_material()
        generic_material = bpy.data.materials.get("Generic")
    
    if not generic_material:
        print("Error: Could not create or get Generic material")
        return

    for obj in objects:
        if obj.type not in {'MESH', 'CURVE'}:
            continue
        
        # Track if object had no materials originally
        had_no_materials = len(obj.material_slots) == 0
        if had_no_materials:
            obj["_had_no_materials"] = True
            obj.data.materials.append(generic_material)
        else:
            # Handle empty slots
            for i, slot in enumerate(obj.material_slots):
                if slot.material is None:
                    obj["_empty_slot_" + str(i)] = True
                    slot.material = generic_material

def update_override_button(context) -> None:
    """Force redraw of the panel."""
    context.area.tag_redraw()

# -----------------------------------------------------------------------------
# Material Management Functions
# -----------------------------------------------------------------------------

def store_original_materials(objects: List) -> None:
    """Store original materials in the object's custom properties."""
    for obj in objects:
        if obj.type not in {'MESH', 'CURVE'}:
            continue
            
        # Store regular materials
        materials = [slot.material.name if slot.material else None for slot in obj.material_slots]
        obj["_original_materials"] = json.dumps(materials)
        
        for slot in obj.material_slots:
            if slot.material:
                slot.material.use_fake_user = True
        
        # Store geometry nodes materials
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

def apply_override_material(objects: List, override_material, exclude_materials: Set) -> None:
    """Apply the override material to all objects except excluded materials."""
    if not override_material:
        return
        
    for obj in objects:
        if obj.type not in {'MESH', 'CURVE'}:
            continue
            
        # Apply to regular material slots
        for slot in obj.material_slots:
            if slot.material not in exclude_materials and slot.material != override_material:
                slot.material = override_material
        
        # Apply to geometry nodes
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

def revert_original_materials(objects: List, keep_generic: bool = False) -> None:
    """Restore original materials from stored custom properties."""
    generic_material = bpy.data.materials.get("Generic")
    
    for obj in objects:
        if obj.type not in {'MESH', 'CURVE'} or "_original_materials" not in obj:
            continue
            
        # Restore regular materials
        original_materials = json.loads(obj["_original_materials"])
        for i, mat_name in enumerate(original_materials):
            if i < len(obj.material_slots):
                if mat_name:
                    mat = bpy.data.materials.get(mat_name)
                    if mat:
                        obj.material_slots[i].material = mat
                        mat.use_fake_user = False
                # If it was originally None and we don't want to keep generic
                elif not keep_generic and "_empty_slot_" + str(i) in obj:
                    obj.material_slots[i].material = None
                    del obj["_empty_slot_" + str(i)]
        
        del obj["_original_materials"]
        
        # Handle objects that originally had no materials
        if "_had_no_materials" in obj and not keep_generic:
            # Remove all materials from the object
            obj.data.materials.clear()
            del obj["_had_no_materials"]
        
        # Restore geometry nodes materials
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
            
            del obj["_original_geom_node_materials"]

def copy_instanced_collections_to_new_collection() -> List:
    """Create real instances from collection instances for material override."""
    scene = bpy.context.scene
    
    # Create or get the instance definitions collection
    new_collection = bpy.data.collections.get("Instance Definitions")
    if not new_collection:
        new_collection = bpy.data.collections.new("Instance Definitions")
        scene.collection.children.link(new_collection)
    
    # Hide the collection
    new_collection.hide_viewport = True
    new_collection.hide_render = True
    new_collection.hide_select = True

    all_objects = []

    for obj in scene.objects:
        if not obj.instance_collection:
            continue
            
        # Copy the collection and its objects
        instance_collection_copy = obj.instance_collection.copy()
        new_collection.children.link(instance_collection_copy)

        # Make objects local
        override_context = bpy.context.copy()
        override_context['selected_objects'] = instance_collection_copy.objects
        override_context['active_object'] = None

        with bpy.context.temp_override(**override_context):
            bpy.ops.object.select_all(action='DESELECT')
            for instance_obj in instance_collection_copy.objects:
                if instance_obj.type in {'MESH', 'CURVE'}:
                    instance_obj.select_set(True)
            bpy.ops.object.make_local(type='ALL')

        # Store original materials
        store_original_materials(instance_collection_copy.objects)
        all_objects.extend([obj for obj in instance_collection_copy.objects if obj.type in {'MESH', 'CURVE'}])

    return all_objects

def clear_addon_data() -> None:
    """Reset all addon data to default state."""
    global override_active
    override_active = False
    
    scene = bpy.context.scene
    settings = scene.advanced_material_override_settings
    settings.override_material = None
    settings.exclude_materials.clear()
    settings.exclude_materials_index = 0
    settings.selected_material = None

# -----------------------------------------------------------------------------
# Event Handlers
# -----------------------------------------------------------------------------

def pre_render_handler(scene) -> None:
    """Store original materials and apply override before rendering."""
    all_objects = get_all_objects(scene)
    
    # Make sure all objects have materials
    tag_objects_with_generic_material(all_objects)
    
    store_original_materials(all_objects)
    
    settings = scene.advanced_material_override_settings
    exclude_materials = {item.material for item in settings.exclude_materials}
    apply_override_material(all_objects, settings.override_material, exclude_materials)

def post_render_handler(scene) -> None:
    """Restore original materials after rendering."""
    all_objects = get_all_objects(scene)
    settings = scene.advanced_material_override_settings
    revert_original_materials(all_objects, settings.keep_generic_material)

def save_override_state() -> None:
    """Save the current override state to the scene."""
    scene = bpy.context.scene
    scene["override_active"] = override_active
    if override_active:
        # Save material settings for restoration
        settings = scene.advanced_material_override_settings
        scene["override_material"] = settings.override_material.name if settings.override_material else ""
        scene["keep_generic_material"] = settings.keep_generic_material
        # Save exclude materials
        exclude_materials = []
        for item in settings.exclude_materials:
            if item.material:
                exclude_materials.append(item.material.name)
        scene["exclude_materials"] = json.dumps(exclude_materials)

def load_post_handler(dummy) -> None:
    """Register a timer to handle post-load initialization."""
    bpy.app.timers.register(delayed_load_handler)

def delayed_load_handler() -> None:
    """Check for interrupted override session and handle initialization."""
    global override_active
    
    scene = bpy.context.scene
    
    # First check for explicit override flags
    has_override = "override_active" in scene and scene["override_active"]
    
    # If no explicit override, try to detect it
    if not has_override:
        has_override = detect_probable_override()
    
    if has_override:
        # There was an active override session during last exit
        print("Detected override session. UI updated to enable cancellation.")
        all_objects = get_all_objects(scene)
        
        # Set override_active to True to enable the cancel button
        override_active = True
        
        # Restore settings from saved state if explicit override was saved
        settings = scene.advanced_material_override_settings
        if "override_material" in scene and scene["override_material"]:
            mat_name = scene["override_material"]
            if mat_name in bpy.data.materials:
                settings.override_material = bpy.data.materials.get(mat_name)
        
        if "keep_generic_material" in scene:
            settings.keep_generic_material = scene["keep_generic_material"]
            
        if "exclude_materials" in scene:
            try:
                exclude_materials = json.loads(scene["exclude_materials"])
                # Clear existing exclude list
                settings.exclude_materials.clear()
                # Add saved excluded materials
                for mat_name in exclude_materials:
                    if mat_name in bpy.data.materials:
                        item = settings.exclude_materials.add()
                        item.material = bpy.data.materials.get(mat_name)
            except:
                pass
        
        # Create a notification in the UI
        def show_override_message():
            bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
            window = bpy.context.window_manager.windows[0]
            bpy.ops.wm.popup_menu(window=window, title="Material Override Detected", 
                                  message="An active material override was detected. Use 'Cancel Override' to restore original materials.")
            return None
        
        # Schedule notification after UI is fully loaded
        bpy.app.timers.register(show_override_message, first_interval=1.0)
    else:
        # No interrupted override session - normal startup
        override_active = False
        all_objects = get_all_objects(scene)
        store_original_materials(all_objects)
    
    # Force UI refresh
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()
    
    return None  # Return None to stop the timer

def app_handler_save_pre():
    """Save override state before saving the file."""
    if override_active:
        save_override_state()

def app_handler_exit():
    """Handle application exit by reverting any active overrides."""
    global override_active
    if override_active:
        # Save override state first
        save_override_state()
        
        # Try to revert materials
        try:
            scene = bpy.context.scene
            all_objects = get_all_objects(scene)
            settings = scene.advanced_material_override_settings
            revert_original_materials(all_objects, settings.keep_generic_material)
            
            # Delete the "Instance Definitions" collection
            instance_definitions_collection = bpy.data.collections.get("Instance Definitions")
            if instance_definitions_collection:
                bpy.data.collections.remove(instance_definitions_collection)
        except Exception as e:
            print(f"Error reverting materials on exit: {str(e)}")
            # We still need to save the override state for next startup

# -----------------------------------------------------------------------------
# UI Elements
# -----------------------------------------------------------------------------

class MATERIAL_UL_override_exclude(bpy.types.UIList):
    """UI List to display excluded materials"""
    bl_idname = "MATERIAL_UL_override_exclude"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(
                text=item.material.name if item.material else "None", 
                icon='MATERIAL'
            )
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(
                text=item.material.name if item.material else "None", 
                icon='MATERIAL'
            )

# -----------------------------------------------------------------------------
# Operators
# -----------------------------------------------------------------------------

class OBJECT_OT_apply_material_override(bpy.types.Operator):
    """Apply Material Override to all objects in the scene"""
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
        settings = scene.advanced_material_override_settings
        
        # Get all objects including instanced collections
        instanced_objects = copy_instanced_collections_to_new_collection()
        all_objects = get_all_objects(scene) + instanced_objects
        
        # Make sure all objects have materials
        tag_objects_with_generic_material(all_objects)
        
        # Store original materials and apply override
        store_original_materials(all_objects)
        exclude_materials = {item.material for item in settings.exclude_materials}
        apply_override_material(all_objects, settings.override_material, exclude_materials)
        
        # Update the view
        context.view_layer.update()
        override_active = True
        
        return {'FINISHED'}

class OBJECT_OT_cancel_material_override(bpy.types.Operator):
    """Cancel Material Override and Restore Original Materials"""
    bl_idname = "object.cancel_material_override"
    bl_label = "Cancel Material Override"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # Always available when override_active is True (no longer dependent on UI access)
        return override_active

    def execute(self, context):
        global override_active
        scene = context.scene
        settings = scene.advanced_material_override_settings
        
        # Revert all materials
        revert_original_materials(get_all_objects(scene), settings.keep_generic_material)
        
        # Delete the "Instance Definitions" collection
        instance_definitions_collection = bpy.data.collections.get("Instance Definitions")
        if instance_definitions_collection:
            bpy.data.collections.remove(instance_definitions_collection)
        
        # Clear any saved override state
        if "override_active" in scene:
            del scene["override_active"]
        if "override_material" in scene:
            del scene["override_material"]
        if "keep_generic_material" in scene:
            del scene["keep_generic_material"]
        if "exclude_materials" in scene:
            del scene["exclude_materials"]
        
        # Update the view
        context.view_layer.update()
        override_active = False
        
        # Force UI refresh
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
        
        return {'FINISHED'}

class MATERIAL_OT_add_exclude_material(bpy.types.Operator):
    """Add selected material to exclude list"""
    bl_idname = "material.add_exclude_material"
    bl_label = "Add Exclude Material"

    @classmethod
    def poll(cls, context):
        settings = context.scene.advanced_material_override_settings
        return not override_active and settings.selected_material is not None

    def execute(self, context):
        settings = context.scene.advanced_material_override_settings
        if settings.selected_material:
            # Check if the material is already in the exclude list
            if any(item.material == settings.selected_material for item in settings.exclude_materials):
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
    
    action: bpy.props.EnumProperty(
        items=(
            ('REMOVE', "Remove", "Remove selected material from exclude list"),
            ('UP', "Up", "Move selected material up in the list"),
            ('DOWN', "Down", "Move selected material down in the list"),
        )
    )

    def invoke(self, context, event):
        settings = context.scene.advanced_material_override_settings
        idx = settings.exclude_materials_index

        if self.action == 'REMOVE':
            if idx >= 0 and idx < len(settings.exclude_materials):
                settings.exclude_materials.remove(idx)
                settings.exclude_materials_index = max(0, min(idx, len(settings.exclude_materials) - 1))

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
        
        # Sort by material name
        material_items = []
        for item in settings.exclude_materials:
            material_items.append(item.material)
        
        material_items.sort(key=lambda x: x.name if x else "")
        
        # Clear and rebuild the list
        settings.exclude_materials.clear()
        for material in material_items:
            item = settings.exclude_materials.add()
            item.material = material
        
        return {'FINISHED'}

class MATERIAL_OT_clear_exclude_list(bpy.types.Operator):
    """Clear all materials from the exclude list"""
    bl_idname = "material.clear_exclude_list"
    bl_label = "Clear Exclude List"

    def execute(self, context):
        settings = context.scene.advanced_material_override_settings
        settings.exclude_materials.clear()
        settings.exclude_materials_index = 0
        return {'FINISHED'}

class OBJECT_OT_purge_duplicate_geometry(bpy.types.Operator):
    """Remove objects with duplicate geometry"""
    bl_idname = "object.purge_duplicate_geometry"
    bl_label = "Purge Duplicate Geometry"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Dictionary to store objects by their mesh data and location
        object_data_dict = {}
        removed_count = 0

        # Iterate through all objects in the scene
        for obj in list(context.scene.objects):
            if obj.type != 'MESH':
                continue
                
            mesh_data = get_mesh_data(obj)
            location = tuple(round(coord, 5) for coord in obj.location)
            
            # Combine mesh data and location as a key
            key = (mesh_data, location)
            
            if key in object_data_dict:
                # If an object with the same mesh data and location exists, delete the duplicate
                bpy.data.objects.remove(obj, do_unlink=True)
                removed_count += 1
            else:
                # Otherwise, store this object in the dictionary
                object_data_dict[key] = obj

        self.report({'INFO'}, f"Removed {removed_count} duplicate objects")
        return {'FINISHED'}

class OBJECT_OT_delete_empty_material_slots(bpy.types.Operator):
    """Delete empty material slots from all mesh objects"""
    bl_idname = "object.delete_empty_material_slots"
    bl_label = "Purge Unused Material Slots"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Store current active object
        current_active = context.view_layer.objects.active
        current_mode = context.mode
        
        # Make sure we're in object mode
        if current_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        
        removed_count = 0
            
        for obj in context.scene.objects:
            if obj.type != 'MESH':
                continue
                
            # Set as active object
            context.view_layer.objects.active = obj
            
            # Remove empty slots from bottom to top
            for i in range(len(obj.material_slots) - 1, -1, -1):
                if obj.material_slots[i].material is None:
                    obj.active_material_index = i
                    bpy.ops.object.material_slot_remove()
                    removed_count += 1
        
        # Restore original active object
        context.view_layer.objects.active = current_active
        
        # Restore original mode if possible
        if current_active and current_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=current_mode)
            
        self.report({'INFO'}, f"Removed {removed_count} empty material slots")
        return {'FINISHED'}

# -----------------------------------------------------------------------------
# UI Panels
# -----------------------------------------------------------------------------

class MATERIAL_PT_override_panel(bpy.types.Panel):
    """Material override panel in material properties"""
    bl_label = "Advanced Material Override"
    bl_idname = "MATERIAL_PT_advanced_override_panel"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'material'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.advanced_material_override_settings
        
        # Add indicator for active override
        if override_active:
            box = layout.box()
            box.alert = True
            box.label(text="Material Override Active", icon='INFO')

        # Override material selection
        row = layout.row()
        row.enabled = not override_active
        row.prop(settings, "override_material", text="Override Material")

        # Exclude materials list
        box = layout.box()
        box.label(text="Materials to Exclude:")
        
        row = box.row()
        row.enabled = not override_active
        row.template_list(
            "MATERIAL_UL_override_exclude", "", 
            settings, "exclude_materials", 
            settings, "exclude_materials_index", 
            rows=3
        )

        col = row.column(align=True)
        col.enabled = not override_active
        col.operator("material.list_action", icon='REMOVE', text="").action = 'REMOVE'
        col.operator("material.sort_exclude_materials", icon='SORTALPHA', text="")
        col.operator("material.clear_exclude_list", icon='X', text="")

        # Material selection for exclusion
        row = box.row(align=True)
        row.enabled = not override_active
        row.prop(settings, "selected_material", text="")
        row.operator("material.add_exclude_material", text="Add to Exclude List")

        # Keep generic option
        row = layout.row()
        row.prop(settings, "keep_generic_material")

        # Main operations
        col = layout.column(align=True)
        col.scale_y = 1.2
        
        # Apply button - only enabled when override is not active and override material is set
        row = col.row()
        row.enabled = not override_active and settings.override_material is not None
        row.operator("object.apply_material_override", text="Apply Override", icon='MATERIAL')
        
        # Cancel button - only enabled when override is active
        row = col.row()
        row.enabled = override_active
        row.alert = True  # Make it red to indicate it's important
        row.operator("object.cancel_material_override", text="Cancel Override", icon='CANCEL')

        # Utility operations
        box = layout.box()
        box.label(text="Utilities:")
        
        col = box.column(align=True)
        col.operator("object.delete_empty_material_slots", text="Purge Empty Material Slots", icon='TRASH')
        col.operator("object.purge_duplicate_geometry", text="Purge Duplicate Geometry", icon='MESH_DATA')

class MATERIAL_PT_addon_preferences(bpy.types.AddonPreferences):
    """Addon preferences panel"""
    bl_idname = __name__

    def draw(self, context):
        layout = self.layout
        layout.label(text="Advanced Material Override")
        layout.label(text="Author: Nana Beniako")
        layout.label(text="Version: 1.1.0")
        layout.label(text="License: GPL-3.0-or-later")

# -----------------------------------------------------------------------------
# Registration
# -----------------------------------------------------------------------------

classes = (
    MaterialExcludeItem,
    MaterialOverrideSettings,
    MATERIAL_UL_override_exclude,
    OBJECT_OT_apply_material_override,
    OBJECT_OT_cancel_material_override,
    MATERIAL_OT_add_exclude_material,
    MATERIAL_OT_list_action,
    MATERIAL_OT_sort_exclude_materials,
    MATERIAL_OT_clear_exclude_list,
    MATERIAL_PT_override_panel,
    OBJECT_OT_delete_empty_material_slots,
    OBJECT_OT_purge_duplicate_geometry,
    MATERIAL_PT_addon_preferences,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    # Register properties
    bpy.types.Scene.advanced_material_override_settings = bpy.props.PointerProperty(
        type=MaterialOverrideSettings
    )

    # Register handlers
    bpy.app.handlers.load_post.append(load_post_handler)
    bpy.app.handlers.save_pre.append(app_handler_save_pre)
    
    # Add exit handler
    if hasattr(bpy.app.handlers, 'exit'):
        # For Blender 4.0+ where the exit handler exists
        bpy.app.handlers.exit.append(app_handler_exit)
    
    # Create generic material
    bpy.app.timers.register(create_generic_material)

def unregister():
    # Remove handlers
    if load_post_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_post_handler)
    
    if app_handler_save_pre in bpy.app.handlers.save_pre:
        bpy.app.handlers.save_pre.remove(app_handler_save_pre)
    
    if hasattr(bpy.app.handlers, 'exit') and app_handler_exit in bpy.app.handlers.exit:
        bpy.app.handlers.exit.remove(app_handler_exit)
    
    # Handle any active overrides before unregistering
    global override_active
    if override_active:
        try:
            scene = bpy.context.scene
            # Save state before unregistering
            save_override_state()
            # Try to revert materials
            all_objects = get_all_objects(scene)
            settings = scene.advanced_material_override_settings
            revert_original_materials(all_objects, settings.keep_generic_material)
        except Exception as e:
            print(f"Error reverting materials on unregister: {str(e)}")
    
    # Clear addon data
    clear_addon_data()
    
    # Unregister properties
    del bpy.types.Scene.advanced_material_override_settings
    
    # Unregister classes
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()