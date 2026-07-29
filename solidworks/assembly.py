"""
SolidWorks Assembly Tools
Create assemblies, insert components, add mates, and query assembly state.

COM notes (verified via live probe, SW2025):
  - AddComponent5 silently returns None unless the part document is already
    open in memory — so insert_component opens it (silently) first, then
    re-activates the assembly.
  - AddComponent5 positions the component so its BOUNDING-BOX CENTER lands at
    the drop point, not its origin. The Transform2 setter is not available
    late-bound, so precise placement is done with mates (the standard CAD
    workflow). insert_component returns the actual resulting origin position.
  - Mate entity selection: qualified names ("Front Plane@comp-1@Assem1", no
    file extension on the assembly title) work for planes; coordinate picks
    (SelectByID2 with empty name, mark=1) work for faces/edges in assembly
    space.
  - AddMate5 err byref returns 1 on success.
  - Mates are enumerated via the MateGroup feature's sub-features; IMate2
    exposes Type, Alignment, and MateEntity(i).ReferenceComponent.
"""

import json
import logging
from pathlib import Path
import pythoncom
import win32com.client
from mcp.types import Tool
from . import selection_helpers as sel
from .state_tracker import normalize_doc_key
from .com_utils import com_prop as _prop

logger = logging.getLogger(__name__)

# swMateType_e
MATE_TYPES = {
    "COINCIDENT": 0,
    "CONCENTRIC": 1,
    "PERPENDICULAR": 2,
    "PARALLEL": 3,
    "TANGENT": 4,
    "DISTANCE": 5,
    "ANGLE": 6,
    "GEAR": 10,
    "LOCK": 16,
}
MATE_TYPE_NAMES = {v: k.lower() for k, v in MATE_TYPES.items()}

# swMateAlign_e
ALIGNMENTS = {
    "ALIGNED": 0,
    "ANTI_ALIGNED": 1,
    "CLOSEST": 2,
}

# swSelectType_e values seen in mate entities
SELECT_TYPE_NAMES = {
    1: "edge",
    2: "face",
    3: "vertex",
    4: "plane",
    5: "axis",
}

# swComponentSuppressionState_e: 0/1 suppressed-ish, 2/3 resolved
_SUPPRESSED_STATES = (0, 1)

STANDARD_PLANES = {
    "FRONT": "Front Plane",
    "TOP": "Top Plane",
    "RIGHT": "Right Plane",
}


class AssemblyTools:
    """Assembly creation, component insertion, mating, and assembly queries."""

    def __init__(self, connection, tracker=None):
        self.connection = connection
        self.tracker = tracker

    def _json_result(self, result, **extra):
        d = {"result": result}
        d.update(extra)
        return json.dumps(d)

    def get_tool_definitions(self) -> list[Tool]:
        entity_schema = {
            "type": "object",
            "description": "Mate entity selector. Either a component plane (plane + component), or a coordinate pick on geometry (entityType + x/y/z in assembly-space mm).",
            "properties": {
                "plane": {
                    "type": "string",
                    "description": "Standard plane of a component: 'Front', 'Top', 'Right' (or a full plane name like 'Plane1'). Requires 'component'."
                },
                "component": {
                    "type": "string",
                    "description": "Component ID (comp:bracket-1) or name (bracket-1) the plane belongs to"
                },
                "entityType": {
                    "type": "string",
                    "enum": ["FACE", "EDGE", "VERTEX"],
                    "description": "Geometry type for a coordinate pick"
                },
                "x": {"type": "number", "description": "X in assembly space (mm)"},
                "y": {"type": "number", "description": "Y in assembly space (mm)"},
                "z": {"type": "number", "description": "Z in assembly space (mm)"}
            }
        }
        return [
            Tool(
                name="solidworks_new_assembly",
                description="Create a new empty assembly document. Insert saved parts with insert_component afterwards.",
                inputSchema={"type": "object", "properties": {}}
            ),
            Tool(
                name="solidworks_insert_component",
                description="Insert a saved part (or sub-assembly) into the active assembly at a drop point. NOTE: SolidWorks centers the component's bounding box at the drop point; the returned actualPosition is the component origin's resulting location. The first inserted component is automatically fixed in place. Use mates for precise positioning.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the .SLDPRT/.SLDASM file (bare filenames resolve against the workspace directory)"
                        },
                        "x": {"type": "number", "description": "Drop point X (mm), default 0"},
                        "y": {"type": "number", "description": "Drop point Y (mm), default 0"},
                        "z": {"type": "number", "description": "Drop point Z (mm), default 0"}
                    },
                    "required": ["path"]
                }
            ),
            Tool(
                name="solidworks_add_mate",
                description="Add a mate between two entities in the active assembly. Entities can be component planes (e.g. Front plane of comp:bracket-1) or coordinate-picked faces/edges in assembly space (use list_components for component positions; coordinates from get_faces of the part are in PART space and must be offset by the component position). Distance in mm, angle in degrees.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "mateType": {
                            "type": "string",
                            "enum": list(MATE_TYPES.keys()),
                            "description": "Type of mate"
                        },
                        "entity1": entity_schema,
                        "entity2": entity_schema,
                        "alignment": {
                            "type": "string",
                            "enum": list(ALIGNMENTS.keys()),
                            "description": "Mate alignment (default CLOSEST)"
                        },
                        "distance": {
                            "type": "number",
                            "description": "Distance value in mm (DISTANCE mates)"
                        },
                        "angle": {
                            "type": "number",
                            "description": "Angle value in degrees (ANGLE mates)"
                        },
                        "flip": {
                            "type": "boolean",
                            "description": "Flip dimension to the other side (default false)"
                        },
                        "gearRatioNumerator": {
                            "type": "number",
                            "description": "GEAR mates: ratio numerator (e.g. first gear's teeth or diameter)"
                        },
                        "gearRatioDenominator": {
                            "type": "number",
                            "description": "GEAR mates: ratio denominator (e.g. second gear's teeth or diameter)"
                        }
                    },
                    "required": ["mateType", "entity1", "entity2"]
                }
            ),
            Tool(
                name="solidworks_list_components",
                description="List all components in the active assembly: IDs, file paths, origin positions (mm), fixed and suppression status.",
                inputSchema={"type": "object", "properties": {}}
            ),
            Tool(
                name="solidworks_list_mates",
                description="List all mates in the active assembly with their types, alignment, and mated components.",
                inputSchema={"type": "object", "properties": {}}
            ),
            Tool(
                name="solidworks_edit_mate",
                description="Change the value of an existing DISTANCE or ANGLE mate. The assembly is rebuilt and the updated component positions are returned. Use this for 'modify the assembly' questions instead of deleting and re-creating mates.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "mate": {
                            "type": "string",
                            "description": "Mate ID (mate:Distance1) or name (Distance1)"
                        },
                        "distance": {
                            "type": "number",
                            "description": "New distance in mm (DISTANCE mates)"
                        },
                        "angle": {
                            "type": "number",
                            "description": "New angle in degrees (ANGLE mates)"
                        }
                    },
                    "required": ["mate"]
                }
            ),
            Tool(
                name="solidworks_check_interference",
                description="Detect interference (overlapping volume) between components in the active assembly. Returns each interference's volume in mm^3 and the components involved. Coincident (touching) faces are NOT counted as interference.",
                inputSchema={"type": "object", "properties": {}}
            ),
            Tool(
                name="solidworks_suppress_component",
                description="Suppress or resolve (unsuppress) a component in the active assembly. Suppressed components are excluded from mass properties and interference checks.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "component": {"type": "string", "description": "Component ID (comp:name-1) or name (name-1)"},
                        "suppress": {"type": "boolean", "description": "true = suppress, false = resolve"}
                    },
                    "required": ["component", "suppress"]
                }
            ),
            Tool(
                name="solidworks_get_assembly_mass_properties",
                description="Get mass properties (mass in kg and grams, volume, surface area, center of mass) for the entire active assembly. Pass coordinateSystem to report the center of mass relative to a coordinate system feature instead of the assembly origin.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "coordinateSystem": {
                            "type": "string",
                            "description": "Optional: name or ref ID of a coordinate system feature in the assembly"
                        }
                    }
                }
            ),
        ]

    def execute(self, tool_name: str, args: dict) -> str:
        self.connection.ensure_connection()
        dispatch = {
            "solidworks_new_assembly": lambda: self.new_assembly(),
            "solidworks_insert_component": lambda: self.insert_component(args),
            "solidworks_add_mate": lambda: self.add_mate(args),
            "solidworks_list_components": lambda: self.list_components(),
            "solidworks_list_mates": lambda: self.list_mates(),
            "solidworks_edit_mate": lambda: self.edit_mate(args),
            "solidworks_check_interference": lambda: self.check_interference(),
            "solidworks_suppress_component": lambda: self.suppress_component(args),
            "solidworks_get_assembly_mass_properties": lambda: self.get_assembly_mass_properties(args),
        }
        handler = dispatch.get(tool_name)
        if not handler:
            raise Exception(f"Unknown assembly tool: {tool_name}")
        return handler()

    # --- Helpers ---

    def _get_assembly_doc(self):
        """Return the active document if it is an assembly, else raise."""
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document — create an assembly with new_assembly first")
        doc_type = _prop(doc, "GetType")
        if int(doc_type) != 2:  # swDocASSEMBLY
            raise Exception(
                "Active document is not an assembly. "
                "Use new_assembly or activate_document to switch to one."
            )
        return doc

    def _assembly_ref_title(self, doc) -> str:
        """Assembly title without extension, as used in qualified selection names."""
        return normalize_doc_key(doc.GetTitle)

    def _resolve_component_name(self, name_or_id: str) -> str:
        if name_or_id.startswith("comp:"):
            if self.tracker:
                sw_name = self.tracker.get_sw_name(name_or_id)
                if sw_name:
                    return sw_name
            return name_or_id[len("comp:"):]
        return name_or_id

    def _component_position_mm(self, comp) -> dict:
        """Component origin translation in mm from its Transform2 matrix."""
        try:
            arr = _prop(comp, "Transform2").ArrayData
            return {
                "x": round(arr[9] * 1000.0, 3),
                "y": round(arr[10] * 1000.0, 3),
                "z": round(arr[11] * 1000.0, 3),
            }
        except Exception as e:
            logger.warning(f"Could not read component transform: {e}")
            return {}

    def _select_mate_entity(self, doc, entity: dict, append: bool) -> str:
        """Select one mate entity with mark=1. Returns a description string."""
        if entity.get("plane"):
            comp_ref = entity.get("component")
            if not comp_ref:
                raise Exception("Plane mate entity requires 'component'")
            comp_name = self._resolve_component_name(comp_ref)
            plane = entity["plane"].strip()
            plane_name = STANDARD_PLANES.get(plane.upper(), plane)
            qualified = f"{plane_name}@{comp_name}@{self._assembly_ref_title(doc)}"
            ok = doc.Extension.SelectByID2(
                qualified, "PLANE", 0, 0, 0, append, 1, sel.make_callout(), 0
            )
            if not ok:
                raise Exception(f"Could not select plane: {qualified}")
            return f"{plane_name}@{comp_name}"

        entity_type = (entity.get("entityType") or "").upper()
        if entity_type in ("FACE", "EDGE", "VERTEX"):
            for coord in ("x", "y", "z"):
                if coord not in entity:
                    raise Exception(f"Coordinate mate entity requires '{coord}' (mm)")
            x, y, z = entity["x"], entity["y"], entity["z"]
            ok = doc.Extension.SelectByID2(
                "", entity_type,
                x / 1000.0, y / 1000.0, z / 1000.0,
                append, 1, sel.make_callout(), 0
            )
            if not ok:
                raise Exception(
                    f"Could not select {entity_type} at ({x}, {y}, {z}) mm in assembly space. "
                    f"Check component positions with list_components — part-space coordinates "
                    f"must be offset by the component's position."
                )
            return f"{entity_type.lower()}@({x},{y},{z})mm"

        raise Exception(
            "Mate entity must specify either 'plane'+'component' or 'entityType'+x/y/z"
        )

    def _iter_mate_features(self, doc):
        """Yield mate sub-features from the assembly's MateGroup."""
        f = doc.FirstFeature
        while f:
            if _prop(f, "GetTypeName2") == "MateGroup":
                sub = _prop(f, "GetFirstSubFeature")
                while sub:
                    yield sub
                    sub = _prop(sub, "GetNextSubFeature")
            f = _prop(f, "GetNextFeature")

    # --- Tool implementations ---

    def new_assembly(self) -> str:
        doc = self.connection.create_new_assembly()
        title = doc.GetTitle
        if self.tracker:
            self.tracker.new_document(title, "assembly")
        return self._json_result(
            f"✓ New assembly document created: {title}",
            title=title,
            type="new_assembly",
        )

    def insert_component(self, args: dict) -> str:
        asm = self._get_assembly_doc()
        asm_title = asm.GetTitle

        raw = args["path"].strip()
        path = Path(raw)
        if not path.is_absolute():
            from .document_manager import WORKSPACE_DIR
            candidate = WORKSPACE_DIR / path
            if not candidate.suffix:
                candidate = candidate.with_suffix(".SLDPRT")
            path = candidate
        if not path.exists():
            raise Exception(f"Component file not found: {path}")

        doc_type = 2 if path.suffix.lower() == ".sldasm" else 1

        # AddComponent5 requires the component document to be open in memory.
        # OpenDoc6 activates the part, so re-activate the assembly afterwards.
        try:
            self.connection.open_document(str(path), doc_type)
        except Exception as e:
            logger.warning(f"Pre-opening component failed (may already be open): {e}")
        self.connection.activate_document(asm_title)
        asm = self.connection.get_active_doc()

        x = args.get("x", 0.0) / 1000.0
        y = args.get("y", 0.0) / 1000.0
        z = args.get("z", 0.0) / 1000.0

        comp = asm.AddComponent5(str(path), 0, "", False, "", x, y, z)
        if not comp:
            raise Exception(
                f"AddComponent5 failed for {path} — the file could not be loaded"
            )

        comp_name = comp.Name2
        fixed = bool(_prop(comp, "IsFixed"))
        position = self._component_position_mm(comp)

        comp_id = None
        if self.tracker:
            comp_id = self.tracker.register_component(
                comp_name, str(path), position=position, fixed=fixed
            )

        note = ("Component was auto-fixed (first component). "
                if fixed else
                "Component is floating — position it precisely with mates. ")
        return self._json_result(
            f"✓ Inserted component {comp_name}. {note}"
            f"Origin is at {position} (bounding-box center placed at drop point).",
            id=comp_id or f"comp:{comp_name}",
            name=comp_name,
            actualPosition=position,
            fixed=fixed,
            type="component",
        )

    def add_mate(self, args: dict) -> str:
        asm = self._get_assembly_doc()

        mate_type_name = args["mateType"].upper()
        if mate_type_name not in MATE_TYPES:
            raise Exception(f"Unknown mate type: {mate_type_name}")
        mate_type = MATE_TYPES[mate_type_name]

        alignment = ALIGNMENTS[args.get("alignment", "CLOSEST").upper()]
        flip = bool(args.get("flip", False))

        distance_mm = args.get("distance", 0.0)
        angle_deg = args.get("angle", 0.0)
        if mate_type_name == "DISTANCE" and "distance" not in args:
            raise Exception("DISTANCE mate requires 'distance' (mm)")
        if mate_type_name == "ANGLE" and "angle" not in args:
            raise Exception("ANGLE mate requires 'angle' (degrees)")

        import math
        distance_m = distance_mm / 1000.0
        angle_rad = math.radians(angle_deg)
        gear_num = args.get("gearRatioNumerator", 0.0)
        gear_den = args.get("gearRatioDenominator", 0.0)
        if mate_type_name == "GEAR" and not (gear_num and gear_den):
            raise Exception("GEAR mate requires gearRatioNumerator and gearRatioDenominator")

        asm.ClearSelection2(True)
        desc1 = self._select_mate_entity(asm, args["entity1"], append=False)
        desc2 = self._select_mate_entity(asm, args["entity2"], append=True)

        err = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        mate = asm.AddMate5(
            mate_type, alignment, flip,
            distance_m, distance_m, distance_m,
            gear_num, gear_den,
            angle_rad, angle_rad, angle_rad,
            False, False, 0, err
        )
        asm.ClearSelection2(True)

        if not mate:
            raise Exception(
                f"AddMate5 failed (error code {err.value}) for {mate_type_name} "
                f"between {desc1} and {desc2}"
            )

        mate_name = mate.Name
        value = None
        if mate_type_name == "DISTANCE":
            value = distance_mm
        elif mate_type_name == "ANGLE":
            value = angle_deg

        mate_id = None
        if self.tracker:
            mate_id = self.tracker.register_mate(
                mate_name, mate_type_name.lower(),
                entities=[desc1, desc2], value=value,
            )

        asm.ForceRebuild3(True)
        return self._json_result(
            f"✓ Added {mate_type_name.lower()} mate '{mate_name}' between {desc1} and {desc2}",
            id=mate_id or f"mate:{mate_name}",
            name=mate_name,
            mateType=mate_type_name.lower(),
            **({"value": value} if value is not None else {}),
            type="mate",
        )

    def list_components(self) -> str:
        asm = self._get_assembly_doc()
        comps = asm.GetComponents(True)  # True = top-level only

        results = []
        for c in (comps or []):
            name = c.Name2
            try:
                file_path = _prop(c, "GetPathName")
            except Exception:
                file_path = None
            try:
                suppression = int(_prop(c, "GetSuppression2"))
            except Exception:
                suppression = None
            info = {
                "id": f"comp:{name}",
                "name": name,
                "filePath": file_path,
                "position": self._component_position_mm(c),
                "fixed": bool(_prop(c, "IsFixed")),
                "suppressed": suppression in _SUPPRESSED_STATES if suppression is not None else False,
            }
            results.append(info)
            # Keep the tracker in sync (components can exist from opened assemblies)
            if self.tracker:
                self.tracker.register_component(
                    name, file_path or "", position=info["position"],
                    fixed=info["fixed"], suppressed=info["suppressed"],
                )

        return json.dumps({
            "result": f"✓ {len(results)} component(s) in assembly",
            "components": results,
        })

    def list_mates(self) -> str:
        asm = self._get_assembly_doc()

        results = []
        for sub in self._iter_mate_features(asm):
            info = {"name": sub.Name, "id": f"mate:{sub.Name}"}
            try:
                m = _prop(sub, "GetSpecificFeature2")
                type_int = int(_prop(m, "Type"))
                info["mateType"] = MATE_TYPE_NAMES.get(type_int, f"type_{type_int}")
                info["alignment"] = int(_prop(m, "Alignment"))
                entities = []
                count = int(_prop(m, "GetMateEntityCount"))
                for i in range(count):
                    ent = m.MateEntity(i)
                    comp = _prop(ent, "ReferenceComponent")
                    ref_type = int(_prop(ent, "ReferenceType2"))
                    entities.append({
                        "component": comp.Name2 if comp else None,
                        "entityType": SELECT_TYPE_NAMES.get(ref_type, f"type_{ref_type}"),
                    })
                info["entities"] = entities
            except Exception as e:
                info["error"] = f"Could not read mate details: {e}"
            results.append(info)

        return json.dumps({
            "result": f"✓ {len(results)} mate(s) in assembly",
            "mates": results,
        })

    def edit_mate(self, args: dict) -> str:
        """Change the driving value of a DISTANCE or ANGLE mate."""
        import math
        asm = self._get_assembly_doc()

        mate_ref = args["mate"]
        mate_name = mate_ref
        if mate_ref.startswith("mate:"):
            if self.tracker:
                resolved = self.tracker.get_sw_name(mate_ref)
                mate_name = resolved or mate_ref[len("mate:"):]
            else:
                mate_name = mate_ref[len("mate:"):]

        if "distance" in args:
            new_value = args["distance"] / 1000.0
            display = f"{args['distance']}mm"
        elif "angle" in args:
            new_value = math.radians(args["angle"])
            display = f"{args['angle']}°"
        else:
            raise Exception("edit_mate requires 'distance' (mm) or 'angle' (degrees)")

        # Mate dimensions are regular dimensions named D1@<MateName>
        # (verified live: SetSystemValue3 + rebuild repositions the components)
        dim = asm.Parameter(f"D1@{mate_name}")
        if dim is None:
            raise Exception(
                f"Mate '{mate_name}' has no editable dimension — only DISTANCE and "
                f"ANGLE mates have values. Check list_mates for mate names."
            )
        dim.SetSystemValue3(new_value, 2, "")
        from .com_utils import verify_rebuild
        rebuilt_ok, rebuild_problems = verify_rebuild(asm)

        if self.tracker:
            record = self.tracker.mates.get(f"mate:{mate_name}")
            if record:
                record.value = args.get("distance", args.get("angle"))

        positions = [
            {"id": f"comp:{c.Name2}", "name": c.Name2,
             "position": self._component_position_mm(c)}
            for c in (asm.GetComponents(True) or [])
        ]
        if not rebuilt_ok:
            return self._json_result(
                f"⚠ Mate '{mate_name}' set to {display}, but the REBUILD "
                f"REPORTS ERRORS: {'; '.join(rebuild_problems[:4])} — the "
                f"assembly may be over-defined or a mate now conflicts.",
                id=f"mate:{mate_name}",
                name=mate_name,
                newValue=args.get("distance", args.get("angle")),
                rebuildErrors=rebuild_problems[:8],
                components=positions,
                type="mate_edit",
            )
        return self._json_result(
            f"✓ Mate '{mate_name}' set to {display}. Components repositioned.",
            id=f"mate:{mate_name}",
            name=mate_name,
            newValue=args.get("distance", args.get("angle")),
            components=positions,
            type="mate_edit",
        )

    def check_interference(self) -> str:
        """Detect component interference (verified live: InterferenceDetectionManager)."""
        asm = self._get_assembly_doc()
        asm.ForceRebuild3(True)

        idm = _prop(asm, "InterferenceDetectionManager")
        try:
            idm.TreatCoincidenceAsInterference = False
            try:
                idm.UseTransform = True
            except Exception:
                pass
            interferences = _prop(idm, "GetInterferences")
            count = int(_prop(idm, "GetInterferenceCount"))
            results = []
            for it in (interferences or []):
                info = {"volume_mm3": round(_prop(it, "Volume") * 1e9, 2)}
                try:
                    comps = _prop(it, "Components")
                    info["components"] = [c.Name2 for c in (comps or [])]
                except Exception:
                    pass
                results.append(info)
        finally:
            try:
                idm.Done()
            except Exception:
                pass

        if count == 0:
            return self._json_result(
                "✓ No interference detected between components.",
                count=0, interferences=[],
            )
        total = sum(i["volume_mm3"] for i in results)
        return self._json_result(
            f"⚠ {count} interference(s) detected, total overlapping volume {total:.2f} mm^3. "
            f"Fix by adjusting mates (edit_mate) or positions.",
            count=count, interferences=results,
        )

    def suppress_component(self, args: dict) -> str:
        """Suppress/resolve a component (verified live: SetSuppression2, 0=suppressed, 3=resolved)."""
        asm = self._get_assembly_doc()
        comp_name = self._resolve_component_name(args["component"].strip())
        suppress = bool(args["suppress"])

        target = None
        for c in (asm.GetComponents(True) or []):
            if c.Name2 == comp_name:
                target = c
                break
        if target is None:
            raise Exception(f"Component not found: {comp_name} (see list_components)")

        target.SetSuppression2(0 if suppress else 3)
        asm.ForceRebuild3(True)

        if self.tracker:
            record = self.tracker.components.get(f"comp:{comp_name}")
            if record:
                record.suppressed = suppress

        verb = "suppressed" if suppress else "resolved"
        return self._json_result(
            f"✓ Component '{comp_name}' {verb}. Mass properties updated.",
            id=f"comp:{comp_name}", name=comp_name, suppressed=suppress,
            type="suppression",
        )

    def get_assembly_mass_properties(self, args: dict = None) -> str:
        args = args or {}
        asm = self._get_assembly_doc()
        asm.ForceRebuild3(True)

        cs_ref = args.get("coordinateSystem")
        if cs_ref:
            cs_name = cs_ref
            if self.tracker and cs_ref.startswith("ref:"):
                cs_name = self.tracker.resolve_name(cs_ref)
            feat = asm.FeatureByName(cs_name)
            if not feat:
                raise Exception(f"Coordinate system feature not found: {cs_name}")
            defn = _prop(feat, "GetDefinition")
            xform = _prop(defn, "Transform")
            mp = _prop(asm.Extension, "CreateMassProperty")
            if not mp.SetCoordinateSystem(xform):
                raise Exception(f"Could not apply coordinate system: {cs_name}")
            mass_kg = mp.Mass
            volume_mm3 = mp.Volume * 1e9
            surface_area_mm2 = mp.SurfaceArea * 1e6
            com = mp.CenterOfMass
            com_x, com_y, com_z = com[0] * 1000.0, com[1] * 1000.0, com[2] * 1000.0
            header = f"Assembly Mass Properties (relative to {cs_name}):"
        else:
            props = asm.GetMassProperties
            if not props or len(props) < 12:
                raise Exception(
                    "Failed to get assembly mass properties (no resolved components?)"
                )
            com_x, com_y, com_z = (props[0] * 1000.0, props[1] * 1000.0, props[2] * 1000.0)
            volume_mm3 = props[3] * 1e9
            surface_area_mm2 = props[4] * 1e6
            mass_kg = props[5]
            cs_name = None
            header = "Assembly Mass Properties:"

        result = f"{header}\n"
        result += f"  Mass: {mass_kg:.6f} kg ({mass_kg * 1000:.2f} grams)\n"
        result += f"  Volume: {volume_mm3:.2f} mm^3\n"
        result += f"  Surface Area: {surface_area_mm2:.2f} mm^2\n"
        result += f"  Center of Mass: ({com_x:.2f}, {com_y:.2f}, {com_z:.2f}) mm"

        return json.dumps({
            "result": result,
            **({"coordinateSystem": cs_name} if cs_name else {}),
            "mass_kg": round(mass_kg, 6),
            "mass_g": round(mass_kg * 1000, 2),
            "volume_mm3": round(volume_mm3, 2),
            "surfaceArea_mm2": round(surface_area_mm2, 2),
            "centerOfMass_mm": {
                "x": round(com_x, 3), "y": round(com_y, 3), "z": round(com_z, 3),
            },
        })
