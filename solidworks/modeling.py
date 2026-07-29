"""
SolidWorks Modeling Tools
Handles 3D feature creation like extrusions, revolves, etc.
"""

import json
import logging
import pythoncom
import win32com.client
from mcp.types import Tool
from typing import Any
from .com_utils import com_prop, exit_active_sketch

logger = logging.getLogger(__name__)

MATERIAL_DATABASE = "SOLIDWORKS Materials"


class ModelingTools:
    """3D modeling feature operations"""
    
    def __init__(self, connection, tracker=None):
        self.connection = connection
        self.tracker = tracker
    
    def _json_result(self, result, **extra):
        d = {"result": result}
        d.update(extra)
        return json.dumps(d)

    def get_tool_definitions(self) -> list[Tool]:
        """Define all modeling tools"""
        return [
            Tool(
                name="solidworks_new_part",
                description="Create a new blank part document. Use this to start a completely new design.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
            Tool(
                name="solidworks_create_extrusion",
                description="Extrude the current sketch to create a 3D feature",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "depth": {
                            "type": "number",
                            "description": "Extrusion depth (mm)"
                        },
                        "reverse": {
                            "type": "boolean",
                            "default": False,
                            "description": "Reverse direction"
                        },
                        "endCondition": {
                            "type": "string",
                            "enum": ["BLIND", "THROUGH_ALL"],
                            "description": "End condition. BLIND (default): extrude to depth. THROUGH_ALL: through entire body.",
                            "default": "BLIND"
                        },
                        "merge": {
                            "type": "boolean",
                            "default": True,
                            "description": "Merge with existing bodies (default true). Set false to create a SEPARATE body for multi-body workflows (then use combine_bodies)."
                        }
                    },
                    "required": ["depth"]
                }
            ),
            Tool(
                name="solidworks_combine_bodies",
                description="Combine the solid bodies of a multi-body part: ADD (union all), SUBTRACT (remove other bodies from the main body), or COMMON (keep only the shared/intersecting volume). Create separate bodies first with create_extrusion merge=false. Body indices follow creation order (0 = first body).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["ADD", "SUBTRACT", "COMMON"],
                            "description": "Boolean operation"
                        },
                        "mainBodyIndex": {
                            "type": "integer",
                            "description": "SUBTRACT only: index of the body to keep (others are subtracted from it). Default 0."
                        }
                    },
                    "required": ["operation"]
                }
            ),
            Tool(
                name="solidworks_create_cut_extrusion",
                description="Cut-extrude the current sketch to remove material from an existing 3D body",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "depth": {
                            "type": "number",
                            "description": "Cut depth (mm)"
                        },
                        "reverse": {
                            "type": "boolean",
                            "default": False,
                            "description": "Reverse cut direction"
                        },
                        "endCondition": {
                            "type": "string",
                            "enum": ["BLIND", "THROUGH_ALL"],
                            "description": "End condition. BLIND (default): cut to depth. THROUGH_ALL: cut through entire body.",
                            "default": "BLIND"
                        }
                    },
                    "required": ["depth"]
                }
            ),
            Tool(
                name="solidworks_set_material",
                description="Assign a material to the active part (sets density for mass calculations). Common SOLIDWORKS Materials names: '6061 Alloy', '1060 Alloy', 'Alloy Steel', 'Plain Carbon Steel', 'AISI 1020', 'Cast Alloy Steel', 'Brass', 'Copper', 'ABS', 'Gray Cast Iron', 'AISI 304'. Required before answering mass questions — without a material, mass uses the default 1000 kg/m^3.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "material": {
                            "type": "string",
                            "description": "Material name exactly as it appears in the SOLIDWORKS Materials database (e.g. '6061 Alloy')"
                        },
                        "configuration": {
                            "type": "string",
                            "description": "Optional configuration name (default: active configuration)"
                        }
                    },
                    "required": ["material"]
                }
            ),
            Tool(
                name="solidworks_set_parameter",
                description="Set a model dimension by its parameter name (e.g. 'D1@Boss-Extrude1' for an extrusion depth, 'D1@Sketch1' for a sketch dimension, 'D1@Cut-Extrude1' for a cut depth). The model is rebuilt. Use this for 'modify the part' questions — changing a feature's driving dimension parametrically updates all downstream features.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "parameter": {
                            "type": "string",
                            "description": "Full parameter name: <DimName>@<FeatureOrSketchName> (e.g. 'D1@Boss-Extrude1')"
                        },
                        "value": {
                            "type": "number",
                            "description": "New value (mm for lengths, degrees for angles)"
                        },
                        "unit": {
                            "type": "string",
                            "enum": ["mm", "deg"],
                            "description": "Unit of value (default mm)"
                        }
                    },
                    "required": ["parameter", "value"]
                }
            ),
            Tool(
                name="solidworks_get_mass_properties",
                description="Evaluate and return mass properties of the active part: mass (kg and grams), volume, surface area, center of mass, and moments of inertia. Assign a material first (set_material) for accurate mass. Pass coordinateSystem to get the center of mass relative to a created coordinate system instead of the model origin.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "coordinateSystem": {
                            "type": "string",
                            "description": "Optional: name or ref ID of a coordinate system feature (e.g. 'Coordinate System1' or 'ref:Coordinate System1'). Center of mass is reported relative to it."
                        }
                    }
                }
            ),
            Tool(
                name="solidworks_suppress_feature",
                description="Suppress or unsuppress a feature by name or ID (feat:...). Suppressed features are excluded from the model and its mass properties until unsuppressed — the standard 'remove this feature' operation for modification questions.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "feature": {"type": "string", "description": "Feature name or feat: ID (e.g. 'Fillet1', 'feat:Cut-Extrude1')"},
                        "suppress": {"type": "boolean", "description": "true = suppress, false = unsuppress"}
                    },
                    "required": ["feature", "suppress"]
                }
            ),
            Tool(
                name="solidworks_delete_feature",
                description="Permanently delete a feature by name or ID (feat:...), including its child features. Prefer suppress_feature when the change might need to be reverted.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "feature": {"type": "string", "description": "Feature name or feat: ID"}
                    },
                    "required": ["feature"]
                }
            ),
            Tool(
                name="solidworks_list_features",
                description="List all features in the feature tree of the active part. Returns feature names and types. Useful for discovering feature names needed by pattern, mirror, and other operations.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
            Tool(
                name="solidworks_list_parameters",
                description="List every driving dimension (parameter) in the active document with its full name (e.g. 'D1@Sketch1', 'D1@Boss-Extrude1'), current value, unit, and owning feature. Use these names with set_parameter / set_config_parameter / equations — never guess dimension names.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "feature": {"type": "string", "description": "Optional feature name or feat: ID to list only that feature's parameters"}
                    }
                }
            )
        ]
    
    def _get_latest_sketch_name(self, doc) -> str:
        """Walk the feature tree in reverse to find the most recent sketch feature"""
        try:
            feature_count = doc.FeatureManager.GetFeatureCount(True)
            features = doc.FeatureManager.GetFeatures(True)
            if features:
                for feature in reversed(features):
                    if feature.GetTypeName2 == "ProfileFeature":
                        name = feature.Name
                        logger.info(f"Latest sketch found in feature tree: {name}")
                        return name
        except Exception as e:
            logger.warning(f"Could not enumerate features to find latest sketch: {e}")
        logger.warning("No sketch found in feature tree, falling back to Sketch1")
        return "Sketch1"

    def execute(self, tool_name: str, args: dict, sketching_tools=None) -> str:
        """Execute a modeling tool"""
        self.connection.ensure_connection()
        
        if tool_name == "solidworks_new_part":
            return self.new_part(sketching_tools)
        elif tool_name == "solidworks_create_extrusion":
            return self.create_extrusion(args, sketching_tools)
        elif tool_name == "solidworks_create_cut_extrusion":
            return self.create_cut_extrusion(args, sketching_tools)
        elif tool_name == "solidworks_set_material":
            return self.set_material(args)
        elif tool_name == "solidworks_set_parameter":
            return self.set_parameter(args)
        elif tool_name == "solidworks_combine_bodies":
            return self.combine_bodies(args)
        elif tool_name == "solidworks_suppress_feature":
            return self.suppress_feature(args)
        elif tool_name == "solidworks_delete_feature":
            return self.delete_feature(args)
        elif tool_name == "solidworks_get_mass_properties":
            return self.get_mass_properties(args)
        elif tool_name == "solidworks_list_features":
            return self.list_features()
        elif tool_name == "solidworks_list_parameters":
            return self.list_parameters(args)
        else:
            raise Exception(f"Unknown modeling tool: {tool_name}")
    
    def new_part(self, sketching_tools) -> str:
        """Explicitly create a new part document"""
        doc = self.connection.create_new_part()
        
        # Reset sketch counter if we have access to sketching tools
        if sketching_tools:
            sketching_tools.sketch_counter = 0
            sketching_tools.current_sketch_name = None
        
        # Start a fresh state scope for this document (other open docs keep theirs)
        if self.tracker:
            try:
                title = doc.GetTitle
            except Exception:
                title = "Part"
            self.tracker.new_document(title, "part")

        logger.info("New part document created")
        return self._json_result("✓ New part document created and ready", type="new_part")
    
    def create_extrusion(self, args: dict, sketching_tools) -> str:
        """Create extrusion from current sketch"""
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")
        
        # Exit sketch mode (tracker-aware: closes the sketch in the tracker
        # with the read-back name so scope.active_sketch doesn't go stale)
        exited_name = exit_active_sketch(doc, self.tracker)

        # Determine sketch name: read-back is authoritative, then the
        # sketching tools' notion, then the newest sketch in the tree
        if exited_name:
            sketch_name = exited_name
        elif sketching_tools and sketching_tools.current_sketch_name:
            sketch_name = sketching_tools.current_sketch_name
        else:
            sketch_name = self._get_latest_sketch_name(doc)

        # Select the sketch
        sketch_feature = doc.FeatureByName(sketch_name)
        if not sketch_feature:
            raise Exception(f"Could not find sketch: {sketch_name}")

        doc.ClearSelection2(True)
        sketch_feature.Select2(False, 0)

        # Convert mm to meters
        depth = args["depth"] / 1000.0
        reverse = args.get("reverse", False)
        end_condition = args.get("endCondition", "BLIND")
        end_type = {"BLIND": 0, "THROUGH_ALL": 1}.get(end_condition, 0)
        merge = args.get("merge", True)

        # Create extrusion with all 23 required parameters
        feature = doc.FeatureManager.FeatureExtrusion2(
            True,      # Sd (same direction)
            reverse,   # Flip direction
            False,     # Dir
            end_type,  # T1 (end condition type - 0 = Blind, 1 = Through All)
            0,         # T2
            depth,     # D1 (depth in meters)
            0.0,       # D2
            False,     # DDir
            False,     # Dang
            False,     # OffsetReverse1
            False,     # OffsetReverse2
            0.0,       # Dang1 (draft angle 1)
            0.0,       # Dang2 (draft angle 2)
            False,     # T1UseLen
            False,     # T2UseLen
            False,     # T3UseLen
            False,     # T4UseLen
            merge,     # Merge result (False => separate body, for multi-body work)
            True,      # T2UseLen2
            True,      # T3UseLen2
            0,         # MergeSmooth
            0,         # StartCond
            False      # ContourType
        )
        
        if not feature:
            raise Exception("Failed to create extrusion")

        feature_name = feature.Name
        doc.ViewZoomtofit2()

        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(
                sw_name=feature_name, feature_type="extrusion",
                source_sketch=f"sketch:{sketch_name}" if sketch_name else None,
                parameters={"depth": args["depth"], "endCondition": end_condition}
            )

        logger.info(f"Extrusion '{feature_name}' created: {args['depth']}mm ({end_condition})")
        return self._json_result(f"✓ Extrusion '{feature_name}' {args['depth']}mm created ({end_condition})", id=feature_id, type="extrusion")

    def create_cut_extrusion(self, args: dict, sketching_tools) -> str:
        """Create cut-extrusion (removes material) from current sketch"""
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        # Exit sketch mode if a sketch is being edited (tracker-aware) —
        # create_cut_extrusion previously never exited, leaving
        # scope.active_sketch stale and skipping name correction
        exited_name = exit_active_sketch(doc, self.tracker)

        # Force rebuild to ensure geometry is fully computed (especially
        # after fillet/chamfer/shell operations that modify the body)
        doc.ForceRebuild3(True)

        # Determine sketch name: read-back is authoritative
        if exited_name:
            sketch_name = exited_name
        elif sketching_tools and sketching_tools.current_sketch_name:
            sketch_name = sketching_tools.current_sketch_name
        else:
            sketch_name = self._get_latest_sketch_name(doc)

        sketch_feature = doc.FeatureByName(sketch_name)
        if not sketch_feature:
            raise Exception(f"Could not find sketch: {sketch_name}")

        # Convert mm to meters
        depth = args["depth"] / 1000.0
        reverse = args.get("reverse", False)
        end_condition = args.get("endCondition", "BLIND")
        end_type = {"BLIND": 0, "THROUGH_ALL": 1}.get(end_condition, 0)

        # FeatureCut4 semantics (probed live on SW2025):
        #   Flip = flip SIDE TO CUT (True removes material OUTSIDE the profile —
        #          almost never wanted; keep False)
        #   Dir  = cut direction. A wrong direction reliably returns None (e.g.
        #          sketches on a boundary plane whose normal points out of the
        #          body), so on None we retry once with Dir flipped.
        def _try_cut(dir_flag):
            doc.ClearSelection2(True)
            sketch_feature.Select2(False, 0)
            return doc.FeatureManager.FeatureCut4(
                True,      # Sd
                False,     # Flip (side to cut)
                dir_flag,  # Dir (cut direction)
                end_type,  # T1 (0=Blind, 1=Through All)
                0,         # T2
                depth,     # D1
                0.0,       # D2
                False,     # Dchk1
                False,     # Dchk2
                False,     # Ddir1
                False,     # Ddir2
                0.0,       # Dang1
                0.0,       # Dang2
                False,     # OffsetReverse1
                False,     # OffsetReverse2
                False,     # TranslateSurface1
                False,     # TranslateSurface2
                False,     # NormalCut
                False,     # UseFeatScope
                True,      # UseAutoSelect
                False,     # AssemblyFeatureScope
                True,      # AutoSelectComponents
                False,     # PropagateFeatureToParts
                0,         # T0
                0.0,       # StartOffset
                False,     # FlipStartOffset
                False      # OptimizeGeometry
            )

        flipped_note = ""
        feature = _try_cut(reverse)
        if not feature:
            feature = _try_cut(not reverse)
            if feature:
                flipped_note = " (cut direction auto-flipped into the body)"
                logger.info("Cut-extrusion direction auto-flipped after initial failure")

        if not feature:
            raise Exception(
                "Failed to create cut-extrusion in either direction. Ensure the "
                "sketch profile is closed and overlaps the solid body."
            )

        feature_name = feature.Name
        doc.ViewZoomtofit2()

        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(
                sw_name=feature_name, feature_type="cut_extrusion",
                source_sketch=f"sketch:{sketch_name}" if sketch_name else None,
                parameters={"depth": args["depth"], "endCondition": end_condition}
            )

        logger.info(f"Cut-extrusion '{feature_name}' created: {args['depth']}mm ({end_condition}){flipped_note}")
        return self._json_result(f"✓ Cut-extrusion '{feature_name}' {args['depth']}mm created ({end_condition}){flipped_note}", id=feature_id, type="cut_extrusion")

    def set_material(self, args: dict) -> str:
        """Assign a material from the SOLIDWORKS Materials database to the active part."""
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        material = args["material"].strip()
        config = args.get("configuration", "") or ""

        doc.SetMaterialPropertyName2(config, MATERIAL_DATABASE, material)
        doc.ForceRebuild3(True)

        # Read back to confirm the name matched an actual database entry
        db = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
        applied = doc.GetMaterialPropertyName2(config, db)
        if not applied or applied.strip().lower() != material.lower():
            raise Exception(
                f"Material '{material}' was not applied (document reports {applied!r}). "
                f"Use the exact name from the SOLIDWORKS Materials database, "
                f"e.g. '6061 Alloy', 'Plain Carbon Steel', 'Alloy Steel', 'AISI 1020', 'Brass', 'ABS'."
            )

        logger.info(f"Material set: {applied}")
        return self._json_result(
            f"✓ Material '{applied}' assigned. Mass properties now use its density.",
            material=applied,
            type="material",
        )

    def set_parameter(self, args: dict) -> str:
        """Set a model dimension by full parameter name and rebuild.
        Same verified mechanism as assembly mate editing: IModelDoc2.Parameter
        returns the IDimension; SetSystemValue3 drives it."""
        import math
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        param_name = args["parameter"].strip()
        unit = args.get("unit", "mm")
        if unit == "deg":
            value_sys = math.radians(args["value"])
            display = f"{args['value']}°"
        else:
            value_sys = args["value"] / 1000.0
            display = f"{args['value']}mm"

        dim = doc.Parameter(param_name)
        if dim is None:
            raise Exception(
                f"Parameter not found: {param_name!r}. Format is <DimName>@<FeatureName> "
                f"(e.g. 'D1@Boss-Extrude1'); use list_features for feature names."
            )
        old_value = dim.SystemValue
        dim.SetSystemValue3(value_sys, 2, "")
        from .com_utils import verify_rebuild
        rebuilt_ok, problems = verify_rebuild(doc)

        old_display = (f"{math.degrees(old_value):.2f}°" if unit == "deg"
                       else f"{old_value * 1000:.2f}mm")
        logger.info(f"Parameter {param_name}: {old_display} -> {display}"
                    + (f" (rebuild problems: {problems})" if problems else ""))
        if not rebuilt_ok:
            return self._json_result(
                f"⚠ {param_name} changed from {old_display} to {display}, but "
                f"the REBUILD REPORTS ERRORS: {'; '.join(problems[:4])}. "
                f"A downstream feature no longer works with this value — "
                f"inspect it (list_features/get_state) or revert the change.",
                parameter=param_name,
                newValue=args["value"],
                unit=unit,
                rebuildErrors=problems[:8],
                type="parameter",
            )
        return self._json_result(
            f"✓ {param_name} changed from {old_display} to {display}. Model rebuilt.",
            parameter=param_name,
            newValue=args["value"],
            unit=unit,
            type="parameter",
        )

    def combine_bodies(self, args: dict) -> str:
        """Boolean-combine the bodies of a multi-body part.
        swBodyOperationType_e probed live on SW2025 (reverse of common docs!):
        15901 = COMMON/intersect, 15902 = SUBTRACT, 15903 = ADD/union."""
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        operation = args["operation"].upper()
        op_map = {"ADD": 15903, "SUBTRACT": 15902, "COMMON": 15901}
        if operation not in op_map:
            raise Exception("operation must be ADD, SUBTRACT, or COMMON")

        doc.ForceRebuild3(True)
        bodies = doc.GetBodies2(0, True)
        if not bodies or len(bodies) < 2:
            raise Exception(
                f"combine_bodies needs at least 2 solid bodies (found "
                f"{len(bodies) if bodies else 0}). Create separate bodies with "
                f"create_extrusion merge=false."
            )

        doc.ClearSelection2(True)
        if operation == "SUBTRACT":
            main_idx = args.get("mainBodyIndex", 0)
            if not (0 <= main_idx < len(bodies)):
                raise Exception(f"mainBodyIndex {main_idx} out of range (0..{len(bodies)-1})")
            main = bodies[main_idx]
            others = [b for i, b in enumerate(bodies) if i != main_idx]
            arr = win32com.client.VARIANT(
                pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, others)
            feature = doc.FeatureManager.InsertCombineFeature(op_map[operation], main, arr)
        else:
            # ADD / COMMON: main body must be null; all bodies in the array
            main = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
            arr = win32com.client.VARIANT(
                pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, list(bodies))
            feature = doc.FeatureManager.InsertCombineFeature(op_map[operation], main, arr)

        if not feature:
            raise Exception(
                f"Combine {operation} failed. For COMMON the bodies must overlap; "
                f"for SUBTRACT the other bodies must intersect the main body."
            )
        doc.ForceRebuild3(True)

        feature_name = feature.Name
        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(
                feature_name, "combine", parameters={"operation": operation})
        remaining = doc.GetBodies2(0, True)
        logger.info(f"Combine {operation}: {feature_name}")
        return self._json_result(
            f"✓ Bodies combined ({operation}) into '{feature_name}'. "
            f"{len(remaining) if remaining else 0} body(ies) remain.",
            id=feature_id, operation=operation, type="combine",
        )

    def _resolve_feature_name(self, name_or_id: str) -> str:
        if name_or_id.startswith("feat:"):
            if self.tracker:
                resolved = self.tracker.get_sw_name(name_or_id)
                if resolved:
                    return resolved
            return name_or_id[len("feat:"):]
        return name_or_id

    def suppress_feature(self, args: dict) -> str:
        """Suppress/unsuppress a feature (verified live: SetSuppression2(0/1, 2, ''))."""
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")
        name = self._resolve_feature_name(args["feature"].strip())
        suppress = bool(args["suppress"])
        feat = doc.FeatureByName(name)
        if not feat:
            raise Exception(f"Feature not found: {name} (see list_features)")
        # swFeatureSuppressionAction_e: 0 = suppress, 1 = unsuppress; 2 = all configs
        ok = feat.SetSuppression2(0 if suppress else 1, 2, "")
        doc.ForceRebuild3(True)
        if not ok:
            raise Exception(f"Could not {'suppress' if suppress else 'unsuppress'} {name}")
        verb = "suppressed" if suppress else "unsuppressed"
        logger.info(f"Feature {name} {verb}")
        return self._json_result(
            f"✓ Feature '{name}' {verb}. Mass properties updated.",
            feature=name, suppressed=suppress, type="suppression",
        )

    def delete_feature(self, args: dict) -> str:
        """Delete a feature (and children) permanently."""
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")
        name = self._resolve_feature_name(args["feature"].strip())
        feat = doc.FeatureByName(name)
        if not feat:
            # Distinguish "already gone" from "never existed" so cleanup can
            # be idempotent: a tracked name missing from the tree was deleted
            # (or absorbed) earlier — drop the stale record and succeed.
            if self.tracker and self.tracker.get_id_by_sw_name(name):
                removed_ids = self.tracker.remove_feature(name)
                logger.info(f"delete_feature: '{name}' already gone; "
                            f"untracked {removed_ids}")
                return self._json_result(
                    f"✓ Feature '{name}' was already gone from the feature "
                    f"tree (deleted or absorbed earlier) — nothing to delete; "
                    f"stale tracking removed.",
                    feature=name, removedIds=removed_ids, type="deletion",
                    alreadyDeleted=True,
                )
            raise Exception(
                f"Feature not found: {name} — no feature by that name exists "
                f"in this document (check list_features for exact names)"
            )
        doc.ClearSelection2(True)
        feat.Select2(False, 0)
        # swDelete_Children = 1: delete dependents too, avoiding blocking prompts
        ok = doc.Extension.DeleteSelection2(1)
        doc.ForceRebuild3(True)
        if not ok:
            raise Exception(f"Could not delete feature {name}")
        # Drop the tracker records too — get_state used to keep listing
        # deleted features (and their sketches) as ghosts
        removed_ids = []
        if self.tracker:
            removed_ids = self.tracker.remove_feature(name)
        logger.info(f"Feature {name} deleted"
                    + (f"; untracked {removed_ids}" if removed_ids else ""))
        return self._json_result(
            f"✓ Feature '{name}' deleted (including dependent children).",
            feature=name, removedIds=removed_ids, type="deletion",
        )

    def _resolve_coordinate_system_transform(self, doc, name_or_id: str):
        """Get the IMathTransform of a coordinate system feature by name or ref ID."""
        name = name_or_id
        if self.tracker and name_or_id.startswith("ref:"):
            name = self.tracker.resolve_name(name_or_id)
        feat = doc.FeatureByName(name)
        if not feat:
            raise Exception(f"Coordinate system feature not found: {name}")
        defn = com_prop(feat, "GetDefinition")
        return com_prop(defn, "Transform"), name

    def get_mass_properties(self, args: dict = None) -> str:
        """Evaluate mass properties of the active part, optionally relative to a
        coordinate system feature."""
        args = args or {}
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        # Rebuild to ensure geometry is up to date
        doc.ForceRebuild3(True)

        cs_ref = args.get("coordinateSystem")
        if cs_ref:
            # IMassProperty supports evaluation relative to an arbitrary transform
            xform, cs_name = self._resolve_coordinate_system_transform(doc, cs_ref)
            mp = com_prop(doc.Extension, "CreateMassProperty")
            if not mp.SetCoordinateSystem(xform):
                raise Exception(f"Could not apply coordinate system: {cs_name}")
            mass_kg = mp.Mass
            volume_mm3 = mp.Volume * 1e9
            surface_area_mm2 = mp.SurfaceArea * 1e6
            com = mp.CenterOfMass
            com_x, com_y, com_z = com[0] * 1000.0, com[1] * 1000.0, com[2] * 1000.0

            result = f"Mass Properties (relative to {cs_name}):\n"
            result += f"  Mass: {mass_kg:.6f} kg ({mass_kg * 1000:.2f} grams)\n"
            result += f"  Volume: {volume_mm3:.2f} mm^3\n"
            result += f"  Surface Area: {surface_area_mm2:.2f} mm^2\n"
            result += f"  Center of Mass: ({com_x:.2f}, {com_y:.2f}, {com_z:.2f}) mm"

            logger.info(f"Mass properties rel {cs_name}: mass={mass_kg:.6f}kg")
            return self._json_result(
                result, type="mass_properties",
                coordinateSystem=cs_name,
                mass_kg=round(mass_kg, 6), mass_g=round(mass_kg * 1000, 2),
                volume_mm3=round(volume_mm3, 2),
                surfaceArea_mm2=round(surface_area_mm2, 2),
                centerOfMass_mm={"x": round(com_x, 3), "y": round(com_y, 3), "z": round(com_z, 3)},
            )

        # GetMassProperties is a property (not method) returning a 12-element tuple:
        #   [0-2] Center of mass (x, y, z) in meters
        #   [3]   Volume in m^3
        #   [4]   Surface area in m^2
        #   [5]   Mass in kg
        #   [6-8] Principal moments of inertia (Ixx, Iyy, Izz) in kg*m^2
        #   [9-11] Products of inertia (Ixy, Ixz, Iyz) in kg*m^2
        props = doc.GetMassProperties
        if not props or len(props) < 12:
            raise Exception("Failed to get mass properties (no solid body or no material assigned)")

        # Convert from SI to mm-based units
        com_x = props[0] * 1000.0
        com_y = props[1] * 1000.0
        com_z = props[2] * 1000.0
        volume_mm3 = props[3] * 1e9        # m^3 -> mm^3
        surface_area_mm2 = props[4] * 1e6  # m^2 -> mm^2
        mass_kg = props[5]

        # Moments of inertia: kg*m^2 -> kg*mm^2
        ixx = props[6] * 1e6
        iyy = props[7] * 1e6
        izz = props[8] * 1e6
        ixy = props[9] * 1e6
        ixz = props[10] * 1e6
        iyz = props[11] * 1e6

        result = "Mass Properties:\n"
        result += f"  Mass: {mass_kg:.6f} kg ({mass_kg * 1000:.2f} grams)\n"
        result += f"  Volume: {volume_mm3:.2f} mm^3\n"
        result += f"  Surface Area: {surface_area_mm2:.2f} mm^2\n"
        result += f"  Center of Mass: ({com_x:.2f}, {com_y:.2f}, {com_z:.2f}) mm\n"
        result += f"  Moments of Inertia (kg*mm^2):\n"
        result += f"    Ixx={ixx:.4f}  Iyy={iyy:.4f}  Izz={izz:.4f}\n"
        result += f"    Ixy={ixy:.4f}  Ixz={ixz:.4f}  Iyz={iyz:.4f}"

        logger.info(f"Mass properties: mass={mass_kg:.6f}kg, volume={volume_mm3:.2f}mm^3")
        return self._json_result(
            result, type="mass_properties",
            mass_kg=round(mass_kg, 6), mass_g=round(mass_kg * 1000, 2),
            volume_mm3=round(volume_mm3, 2),
            surfaceArea_mm2=round(surface_area_mm2, 2),
            centerOfMass_mm={"x": round(com_x, 3), "y": round(com_y, 3), "z": round(com_z, 3)},
        )

    def list_features(self) -> str:
        """List all features in the feature tree"""
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        features = doc.FeatureManager.GetFeatures(True)
        if not features:
            return self._json_result("No features found in the feature tree.",
                                     type="feature_list")

        result = "Feature Tree:\n"
        for feature in features:
            name = feature.Name
            type_name = feature.GetTypeName2
            # Skip origin-level items for cleaner output
            if type_name in ("OriginProfileFeature", "MaterialFolder", "SensorFolder"):
                continue
            tracked_info = ""
            if self.tracker:
                tid = self.tracker.get_id_by_sw_name(name)
                if tid:
                    tracked_info = f" [id={tid}]"
            result += f"  {name} ({type_name}){tracked_info}\n"

        logger.info(f"Listed {len(features)} features")
        return self._json_result(result, type="feature_list")

    def list_parameters(self, args: dict = None) -> str:
        """Enumerate every driving dimension with its addressable name.
        set_parameter targets were previously guessed from creation order —
        this makes the model machine-addressable (parametric modifications,
        equations, per-config dims all key on these names)."""
        import math
        from .com_utils import com_prop
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        only_feature = None
        if args and args.get("feature"):
            only_feature = self._resolve_feature_name(args["feature"])

        doc_name = None
        try:
            doc_name = doc.GetTitle
        except Exception:
            pass

        # Enumerate by probing doc.Parameter("D<i>@<owner>") per feature —
        # IFeature.GetFirstDisplayDimension is Member-not-found via late-bound
        # COM (probed live 2026-07-11); doc.Parameter is the same verified
        # mechanism set_parameter drives. Default D<i> names only; a manually
        # renamed dimension must be addressed by its known name.
        skip_types = {"OriginProfileFeature", "MaterialFolder", "SensorFolder",
                      "DocsFolder", "DetailCabinet", "CommentsFolder",
                      "FavoriteFolder", "HistoryFolder", "SelectionSetFolder",
                      "RefPlane", "OriginFeature", "MateGroup"}
        params = []
        features = doc.FeatureManager.GetFeatures(True) or []
        for feature in features:
            try:
                fname = feature.Name
                if feature.GetTypeName2 in skip_types:
                    continue
                if only_feature and fname != only_feature:
                    continue
                misses = 0
                for i in range(1, 31):
                    try:
                        dim = doc.Parameter(f"D{i}@{fname}")
                    except Exception:
                        dim = None
                    if dim is None:
                        misses += 1
                        if misses >= 5:  # tolerate deleted-dim gaps
                            break
                        continue
                    misses = 0
                    entry = {"parameter": f"D{i}@{fname}", "feature": fname}
                    try:
                        sysval = dim.SystemValue
                        type_code = com_prop(dim, "GetType")
                        # swDimensionParamTypeDoubleAngular reads in radians;
                        # everything else linear (meters)
                        if type_code == 2:
                            entry.update(value=round(math.degrees(sysval), 3),
                                         unit="deg")
                        else:
                            entry.update(value=round(sysval * 1000.0, 3),
                                         unit="mm")
                    except Exception as e:
                        logger.debug(f"dim value read failed {entry}: {e}")
                    params.append(entry)
            except Exception:
                continue

        logger.info(f"Listed {len(params)} parameters"
                    + (f" for {only_feature}" if only_feature else ""))
        return json.dumps({
            "result": f"✓ {len(params)} driving dimension(s)"
                      + (f" in {only_feature}" if only_feature else
                         f" in {doc_name or 'active document'}"),
            "parameters": params,
            "type": "parameter_list",
        })
