"""
SolidWorks Applied Feature Tools
Fillet, Chamfer, Shell, Draft, Rib, Wrap, Intersect
"""

import json
import logging
import math
from mcp.types import Tool
from . import selection_helpers as sel
from .com_utils import exit_active_sketch

logger = logging.getLogger(__name__)


def _select_all_or_raise(doc, points, kind, mark, append_first=False, what=""):
    """Select EVERY point in `points` as `kind` ('edge' or 'face') or raise.

    Partial selection (asked 5, selected 3) used to fall through to feature
    creation and return ✓ for a feature applied to fewer entities than
    requested. All-or-nothing: name the failing points so the agent can fix
    coordinates instead of shipping a wrong model.
    """
    select_fn = sel.select_edge if kind == "edge" else sel.select_face
    failed = []
    count = 0
    for i, pt in enumerate(points):
        append = append_first or i > 0
        if select_fn(doc, pt["x"], pt["y"], pt["z"], append=append, mark=mark):
            count += 1
        else:
            failed.append(pt)
    if failed:
        pts = "; ".join(f"({p['x']}, {p['y']}, {p['z']})" for p in failed)
        raise Exception(
            f"Only {count} of {len(points)} {kind}(s) could be selected"
            + (f" for {what}" if what else "")
            + f" — no {kind} found within 1mm of: {pts} (mm). Nothing was "
            f"created. Use get_edges/get_faces to obtain exact on-geometry "
            f"coordinates, or select every edge of a feature at once with "
            f"the 'feature' parameter (fillet/chamfer)."
        )
    return count


class AppliedFeatureTools:
    """Applied feature operations (fillet, chamfer, shell, draft, rib, wrap, intersect)"""

    def __init__(self, connection, tracker=None):
        self.connection = connection
        self.tracker = tracker

    def _json_result(self, result, **extra):
        d = {"result": result}
        d.update(extra)
        return json.dumps(d)

    def get_tool_definitions(self) -> list[Tool]:
        return [
            Tool(
                name="solidworks_fillet",
                description=(
                    "Apply a constant-radius fillet to edges of the active part. "
                    "PREFERRED: pass 'feature' to fillet every edge of that feature "
                    "(e.g. 'R3 TYP on the boss' = feature: 'Boss-Extrude2') — no "
                    "coordinates needed. Or/and select specific edges by 3D "
                    "coordinates (mm) near each edge."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "radius": {
                            "type": "number",
                            "description": "Fillet radius (mm)"
                        },
                        "edges": {
                            "type": "array",
                            "description": "Array of points on edges to fillet. Each point is {x, y, z} in mm.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "x": {"type": "number", "description": "X coordinate (mm)"},
                                    "y": {"type": "number", "description": "Y coordinate (mm)"},
                                    "z": {"type": "number", "description": "Z coordinate (mm)"}
                                },
                                "required": ["x", "y", "z"]
                            }
                        },
                        "feature": {
                            "type": "string",
                            "description": "Fillet ALL edges belonging to this feature (id or name, e.g. 'feat:Boss-Extrude2') — preferred over coordinates"
                        }
                    },
                    "required": ["radius"]
                }
            ),
            Tool(
                name="solidworks_chamfer",
                description=(
                    "Apply a chamfer to edges of the active part. PREFERRED: "
                    "pass 'feature' to chamfer every edge of that feature — "
                    "no coordinates needed, works regardless of camera view. "
                    "Or/and select specific edges by 3D coordinates (mm) near "
                    "each edge."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "distance": {
                            "type": "number",
                            "description": "Chamfer distance (mm)"
                        },
                        "edges": {
                            "type": "array",
                            "description": "Array of points on edges to chamfer. Each point is {x, y, z} in mm.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "x": {"type": "number", "description": "X coordinate (mm)"},
                                    "y": {"type": "number", "description": "Y coordinate (mm)"},
                                    "z": {"type": "number", "description": "Z coordinate (mm)"}
                                },
                                "required": ["x", "y", "z"]
                            }
                        },
                        "feature": {
                            "type": "string",
                            "description": "Chamfer ALL edges belonging to this feature (id or name, e.g. 'feat:Boss-Extrude2') — preferred over coordinates"
                        },
                        "angle": {
                            "type": "number",
                            "description": "Chamfer angle in degrees (default: 45). Only used with DISTANCE_ANGLE type.",
                            "default": 45
                        },
                        "distance2": {
                            "type": "number",
                            "description": "Second distance (mm) for TWO_DISTANCES chamfer type."
                        },
                        "type": {
                            "type": "string",
                            "enum": ["EQUAL_DISTANCE", "DISTANCE_ANGLE", "TWO_DISTANCES"],
                            "description": "Chamfer type. Default: EQUAL_DISTANCE",
                            "default": "EQUAL_DISTANCE"
                        }
                    },
                    "required": ["distance"]
                }
            ),
            Tool(
                name="solidworks_shell",
                description="Create a shell feature by hollowing out the active part. Select faces to remove (open) by providing 3D coordinates (mm).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "thickness": {
                            "type": "number",
                            "description": "Shell wall thickness (mm)"
                        },
                        "facesToRemove": {
                            "type": "array",
                            "description": "Array of points on faces to remove (open). Each point is {x, y, z} in mm.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "x": {"type": "number", "description": "X coordinate (mm)"},
                                    "y": {"type": "number", "description": "Y coordinate (mm)"},
                                    "z": {"type": "number", "description": "Z coordinate (mm)"}
                                },
                                "required": ["x", "y", "z"]
                            }
                        },
                        "outward": {
                            "type": "boolean",
                            "description": "Shell outward instead of inward (default: false)",
                            "default": False
                        }
                    },
                    "required": ["thickness", "facesToRemove"]
                }
            ),
            Tool(
                name="solidworks_draft",
                description="Apply a draft angle to one or more faces. Requires a neutral plane and faces to draft.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "angle": {
                            "type": "number",
                            "description": "Draft angle in degrees"
                        },
                        "neutralPlane": {
                            "type": "string",
                            "description": "Neutral plane name ('Front', 'Top', 'Right', or custom plane name)"
                        },
                        "facesToDraft": {
                            "type": "array",
                            "description": "Array of points on faces to apply draft to. Each point is {x, y, z} in mm.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "x": {"type": "number", "description": "X coordinate (mm)"},
                                    "y": {"type": "number", "description": "Y coordinate (mm)"},
                                    "z": {"type": "number", "description": "Z coordinate (mm)"}
                                },
                                "required": ["x", "y", "z"]
                            }
                        },
                        "outward": {
                            "type": "boolean",
                            "description": "Draft outward (default: false)",
                            "default": False
                        }
                    },
                    "required": ["angle", "neutralPlane", "facesToDraft"]
                }
            ),
            Tool(
                name="solidworks_rib",
                description="Create a rib feature from the current sketch. The sketch should be an open profile that intersects the existing body. The rib adds material between the sketch and the body.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "thickness": {
                            "type": "number",
                            "description": "Rib thickness (mm)"
                        },
                        "reverse": {
                            "type": "boolean",
                            "description": "Reverse thickness direction (default: false)",
                            "default": False
                        },
                        "flipSide": {
                            "type": "boolean",
                            "description": "Flip the extrusion side (default: false)",
                            "default": False
                        }
                    },
                    "required": ["thickness"]
                }
            ),
            Tool(
                name="solidworks_wrap",
                description="Wrap a sketch profile onto a face. The sketch should be on a plane tangent to or near the target face. Supports emboss (add material), deboss (remove material), and scribe (split line only).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["EMBOSS", "DEBOSS", "SCRIBE"],
                            "description": "Wrap type: EMBOSS adds material, DEBOSS removes material, SCRIBE creates a split line"
                        },
                        "face": {
                            "type": "object",
                            "description": "Point on the target face to wrap onto ({x, y, z} in mm)",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        },
                        "depth": {
                            "type": "number",
                            "description": "Depth (mm) for emboss/deboss. Not used for scribe."
                        }
                    },
                    "required": ["type", "face"]
                }
            ),
            Tool(
                name="solidworks_intersect",
                description=(
                    "Keep only the shared (intersecting) volume of overlapping SOLID "
                    "bodies in a multi-body part — a COMMON boolean. Create separate "
                    "bodies first with create_extrusion merge=false. If 'bodies' is "
                    "empty, ALL solid bodies are intersected. (SolidWorks exposes no "
                    "COM API for the full Intersect feature; surfaces/planes are not "
                    "supported.)"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "bodies": {
                            "type": "array",
                            "description": "Body names to intersect (from list_features/get_body_info; a body is named after its last feature, e.g. 'Boss-Extrude2'). Empty = all solid bodies.",
                            "items": {"type": "string"}
                        }
                    }
                }
            ),
        ]

    def execute(self, tool_name: str, args: dict) -> str:
        self.connection.ensure_connection()
        dispatch = {
            "solidworks_fillet": lambda: self.fillet(args),
            "solidworks_chamfer": lambda: self.chamfer(args),
            "solidworks_shell": lambda: self.shell(args),
            "solidworks_draft": lambda: self.draft(args),
            "solidworks_rib": lambda: self.rib(args),
            "solidworks_wrap": lambda: self.wrap(args),
            "solidworks_intersect": lambda: self.intersect(args),
        }
        handler = dispatch.get(tool_name)
        if not handler:
            raise Exception(f"Unknown applied feature tool: {tool_name}")
        return handler()

    def _edge_objects_of_feature(self, doc, feature_name: str) -> list:
        """IEdge COM objects for every edge adjacent to a face created by
        the named feature. Returns OBJECTS, not coordinates: coordinate
        picks (SelectByID2) resolve against the current camera and fail on
        occluded edges, and closed edges (circles) have no midpoint to pick.
        Caller must not rebuild between collection and selection — a rebuild
        invalidates the returned COM pointers."""
        import types as _types

        def prop(obj, name):
            v = getattr(obj, name)
            return v() if isinstance(v, _types.MethodType) else v

        if feature_name.startswith("feat:"):
            feature_name = feature_name[5:]
        doc.ForceRebuild3(True)
        bodies = doc.GetBodies2(0, True)
        edges = []
        for body in bodies or []:
            for edge in body.GetEdges() or []:
                try:
                    faces = prop(edge, "GetTwoAdjacentFaces2")
                    for face in faces or []:
                        if face is None:
                            continue
                        feat = prop(face, "GetFeature")
                        if feat is not None and str(prop(feat, "Name")).lower() == feature_name.lower():
                            edges.append(edge)
                            break
                except Exception:
                    continue
        return edges

    def fillet(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        radius_m = args["radius"] / 1000.0
        edges = args.get("edges") or []
        # Semantic selection: fillet every edge of a feature (e.g. a drawing's
        # 'R3 TYP on all edges of the boss') without coordinate guessing.
        # Edge OBJECTS are selected directly (view-independent) — coordinate
        # picks fail on edges the current camera can't see.
        feature_edges = []
        if args.get("feature"):
            feature_edges = self._edge_objects_of_feature(doc, args["feature"])
            if not feature_edges:
                raise Exception(f"no edges found for feature {args['feature']!r} "
                                f"(check list_features for the exact name)")
        if not edges and not feature_edges:
            raise Exception("fillet requires 'edges' coordinates and/or a 'feature' name")

        # Force rebuild to ensure geometry is fully computed before edge
        # selection. Must happen before _edge_objects_of_feature's pointers
        # are used — that helper rebuilds internally before collecting.
        if not feature_edges:
            doc.ForceRebuild3(True)

        sel.clear_selection(doc)
        count = 0
        if feature_edges:
            count = sel.select_entities_directly(doc, feature_edges, mark=1)
            if count < len(feature_edges):
                raise Exception(
                    f"Only {count} of {len(feature_edges)} edges of feature "
                    f"{args['feature']!r} could be selected. Nothing was created."
                )
        if edges:
            count += _select_all_or_raise(doc, edges, "edge", mark=1,
                                          append_first=count > 0, what="fillet")

        # FeatureFillet3 parameters:
        # Options (int bitmask), R1, R2, R3, Rho, Ftyp, Overflow, Conic
        # Options=195 required for SolidWorks 2025+
        feature = doc.FeatureManager.FeatureFillet3(
            195,        # Options: 195 required for SW2025+
            radius_m,   # R1: fillet radius
            0.0,        # R2: not used
            0.0,        # R3: not used
            0,          # Rho: not used
            0,          # Ftyp: 0 = constant
            0,          # Overflow: 0 = default
            0,          # Conic: 0 = circular
        )

        if not feature:
            raise Exception("Failed to create fillet. Verify edge coordinates are correct.")

        feature_name = feature.Name
        doc.ViewZoomtofit2()
        logger.info(f"Fillet '{feature_name}' created: {args['radius']}mm radius on {count} edge(s)")
        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(feature_name, "fillet", parameters={"radius": args["radius"]})
        return self._json_result(f"✓ Fillet '{feature_name}' {args['radius']}mm radius applied to {count} edge(s)", id=feature_id, type="fillet")

    def chamfer(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        distance_m = args["distance"] / 1000.0
        edges = args.get("edges") or []
        chamfer_type = args.get("type", "EQUAL_DISTANCE")
        angle_deg = args.get("angle", 45)
        angle_rad = math.radians(angle_deg)
        distance2_m = args.get("distance2", args["distance"]) / 1000.0

        type_map = {
            "EQUAL_DISTANCE": 0,
            "DISTANCE_ANGLE": 1,
            "TWO_DISTANCES": 2,
        }
        chamfer_type_int = type_map.get(chamfer_type, 0)

        # Semantic selection by feature — same view-independent object
        # selection as fillet (see _edge_objects_of_feature).
        feature_edges = []
        if args.get("feature"):
            feature_edges = self._edge_objects_of_feature(doc, args["feature"])
            if not feature_edges:
                raise Exception(f"no edges found for feature {args['feature']!r} "
                                f"(check list_features for the exact name)")
        if not edges and not feature_edges:
            raise Exception("chamfer requires 'edges' coordinates and/or a 'feature' name")

        # Force rebuild to ensure geometry is fully computed before edge
        # selection (_edge_objects_of_feature rebuilds internally).
        if not feature_edges:
            doc.ForceRebuild3(True)

        sel.clear_selection(doc)
        count = 0
        if feature_edges:
            count = sel.select_entities_directly(doc, feature_edges, mark=0)
            if count < len(feature_edges):
                raise Exception(
                    f"Only {count} of {len(feature_edges)} edges of feature "
                    f"{args['feature']!r} could be selected. Nothing was created."
                )
        if edges:
            count += _select_all_or_raise(doc, edges, "edge", mark=0,
                                          append_first=count > 0, what="chamfer")

        # InsertFeatureChamfer params (8 params required for SW2025+):
        # Options, ChamferType, Width, Angle, OtherDist, 0, 0, 0
        feature = doc.FeatureManager.InsertFeatureChamfer(
            4,                  # Options: 4 = select edges
            chamfer_type_int,   # Type: 0=equal, 1=dist-angle, 2=two-dist
            distance_m,         # Width (distance 1)
            angle_rad,          # Angle in radians
            distance2_m,        # Other distance
            0,                  # SW2025 extra param 1
            0,                  # SW2025 extra param 2
            0,                  # SW2025 extra param 3
        )

        if not feature:
            raise Exception("Failed to create chamfer. Verify edge coordinates are correct.")

        feature_name = feature.Name
        doc.ViewZoomtofit2()
        logger.info(f"Chamfer '{feature_name}' created: {args['distance']}mm on {count} edge(s)")
        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(feature_name, "chamfer", parameters={"distance": args["distance"]})
        return self._json_result(f"✓ Chamfer '{feature_name}' {args['distance']}mm applied to {count} edge(s)", id=feature_id, type="chamfer")

    def shell(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        thickness_m = args["thickness"] / 1000.0
        faces = args["facesToRemove"]
        outward = args.get("outward", False)

        # Force rebuild to ensure geometry is fully computed before face selection
        doc.ForceRebuild3(True)

        sel.clear_selection(doc)
        count = _select_all_or_raise(doc, faces, "face", mark=0, what="shell")

        # Snapshot the tree BEFORE shelling so the None-return fallback can
        # only ever report a feature that is genuinely NEW (a failed second
        # shell used to return ✓ naming the pre-existing Shell1).
        try:
            names_before = {f.Name for f in (doc.FeatureManager.GetFeatures(True) or [])}
        except Exception:
            names_before = set()

        # In SW2025, InsertFeatureShell lives on the model (IModelDoc2),
        # NOT on FeatureManager. It may return None even on success.
        doc._FlagAsMethod("InsertFeatureShell")
        feature = doc.InsertFeatureShell(thickness_m, outward)

        # Force rebuild and verify by checking feature tree
        doc.ForceRebuild3(True)

        if not feature:
            # InsertFeatureShell may return None even on success in SW2025;
            # verify by scanning the feature tree for a Shell feature that
            # was NOT there before this call (newest first).
            features = doc.FeatureManager.GetFeatures(True)
            for f in reversed(features or []):
                if "Shell" in f.Name and f.Name not in names_before:
                    feature = f
                    break

        if not feature:
            raise Exception(
                "Failed to create shell — no new Shell feature appeared in the "
                "feature tree. Verify face coordinates and wall thickness."
            )

        feature_name = feature.Name
        doc.ViewZoomtofit2()
        logger.info(f"Shell '{feature_name}' created: {args['thickness']}mm thickness, {count} face(s) removed")
        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(feature_name, "shell", parameters={"thickness": args["thickness"]})
        return self._json_result(f"✓ Shell '{feature_name}' {args['thickness']}mm created with {count} face(s) removed", id=feature_id, type="shell")

    def draft(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        angle_rad = math.radians(args["angle"])
        outward = args.get("outward", False)

        sel.clear_selection(doc)

        # Select neutral plane first
        plane_name = args["neutralPlane"]
        if not sel.select_plane_with_mark(doc, plane_name, mark=1, append=False):
            raise Exception(f"Could not select neutral plane: {plane_name}")

        # Select faces to draft (append_first: the neutral plane is already
        # selected with mark=1 and must stay selected)
        faces = args["facesToDraft"]
        count = _select_all_or_raise(doc, faces, "face", mark=0,
                                     append_first=True, what="draft")

        # InsertFeatureDraft: type, angle, outward
        # Type 0 = Neutral plane draft
        feature = doc.FeatureManager.InsertFeatureDraft(
            0,          # DraftType: 0 = Neutral Plane
            angle_rad,  # Draft angle in radians
            outward,    # Draft outward
        )

        if not feature:
            raise Exception("Failed to create draft. Verify selections are correct.")

        feature_name = feature.Name
        doc.ViewZoomtofit2()
        logger.info(f"Draft '{feature_name}' created: {args['angle']}° on {count} face(s)")
        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(feature_name, "draft", parameters={"angle": args["angle"]})
        return self._json_result(f"✓ Draft '{feature_name}' {args['angle']}° applied to {count} face(s)", id=feature_id, type="draft")

    def rib(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        thickness_m = args["thickness"] / 1000.0
        reverse = args.get("reverse", False)
        flip_side = args.get("flipSide", False)

        # Exit current sketch (tracker-aware) and select it
        sketch_name = exit_active_sketch(doc, self.tracker)
        if not sketch_name:
            # No sketch was active — fall back to the newest sketch in the tree
            features = doc.FeatureManager.GetFeatures(True)
            sketch_name = "Sketch1"
            if features:
                for feature in reversed(features):
                    if feature.GetTypeName2 == "ProfileFeature":
                        sketch_name = feature.Name
                        break

        sketch_feature = doc.FeatureByName(sketch_name)
        if not sketch_feature:
            raise Exception(f"Could not find sketch: {sketch_name}")
        doc.ClearSelection2(True)
        sketch_feature.Select2(False, 0)

        # InsertRib params: IsSolid, IsFlipped, Thickness, RibType, Direction, ...
        # RibType: 0 = Linear, 1 = Natural
        feature = doc.FeatureManager.InsertRib(
            True,           # IsSolid
            flip_side,      # IsFlipped
            reverse,        # ReverseThicknessDir
            thickness_m,    # Thickness
            0,              # RibType: 0 = Linear
            False,          # IsDrafted
            0.0,            # DraftAngle
            False,          # DraftOutward
            False,          # IsNatural
        )

        if not feature:
            raise Exception("Failed to create rib. Ensure sketch profile intersects the body.")

        feature_name = feature.Name
        doc.ViewZoomtofit2()
        logger.info(f"Rib '{feature_name}' created: {args['thickness']}mm thickness")
        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(feature_name, "rib", parameters={"thickness": args["thickness"]})
        return self._json_result(f"✓ Rib '{feature_name}' {args['thickness']}mm created", id=feature_id, type="rib")

    def wrap(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        wrap_type = args["type"]
        face = args["face"]
        depth_m = args.get("depth", 1.0) / 1000.0

        type_map = {
            "EMBOSS": 0,
            "DEBOSS": 1,
            "SCRIBE": 2,
        }
        wrap_type_int = type_map.get(wrap_type, 0)

        # Exit current sketch (tracker-aware)
        sketch_name = exit_active_sketch(doc, self.tracker)
        if not sketch_name:
            # No sketch was active — fall back to the newest sketch in the tree
            features = doc.FeatureManager.GetFeatures(True)
            sketch_name = "Sketch1"
            if features:
                for feature in reversed(features):
                    if feature.GetTypeName2 == "ProfileFeature":
                        sketch_name = feature.Name
                        break

        # Select sketch and face — both selections are load-bearing; a silent
        # miss used to fall through to InsertWrapFeature2 anyway
        sel.clear_selection(doc)
        if not sel.select_sketch(doc, sketch_name, mark=0, append=False):
            raise Exception(f"Could not select sketch '{sketch_name}' for wrap")
        if not sel.select_face(doc, face["x"], face["y"], face["z"], append=True, mark=1):
            raise Exception(
                f"Could not select target face at ({face['x']}, {face['y']}, "
                f"{face['z']}) mm for wrap — use get_faces for exact coordinates"
            )

        # InsertWrapFeature2 params: Type, Thickness, ReverseDir, ...
        feature = doc.FeatureManager.InsertWrapFeature2(
            wrap_type_int,  # Type: 0=Emboss, 1=Deboss, 2=Scribe
            depth_m,        # Thickness in meters
            False,          # ReverseDir
        )

        if not feature:
            raise Exception("Failed to create wrap feature. Ensure sketch is on a plane near the target face.")

        feature_name = feature.Name
        doc.ViewZoomtofit2()
        logger.info(f"Wrap '{feature_name}' created: {wrap_type}, depth={args.get('depth', 1.0)}mm")
        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(feature_name, "wrap", parameters={"wrapType": wrap_type})
        return self._json_result(f"✓ Wrap '{feature_name}' ({wrap_type}) created", id=feature_id, type="wrap")

    def intersect(self, args: dict) -> str:
        """Keep only the shared volume of overlapping solid bodies.

        Probed live on SW2025: IFeatureManager has NO InsertIntersect member
        (DISP_E_UNKNOWNNAME), and neither SelectByID2('BODYFEATURE'/'SOLIDBODY')
        nor IBody2.Select2 selects bodies by name — the previous implementation
        could never have produced a feature. The COMMON boolean via
        InsertCombineFeature (swBodyOperationType_e 15901, live-validated by
        combine_bodies) implements the same solid-body semantics.
        """
        import pythoncom
        import win32com.client

        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        wanted_names = [n.strip() for n in (args.get("bodies") or []) if n and n.strip()]

        doc.ForceRebuild3(True)
        bodies = doc.GetBodies2(0, True)
        if not bodies or len(bodies) < 2:
            raise Exception(
                f"intersect needs at least 2 solid bodies (found "
                f"{len(bodies) if bodies else 0}). Create separate bodies with "
                f"create_extrusion merge=false."
            )

        if wanted_names:
            by_name = {str(b.Name).lower(): b for b in bodies}
            missing = [n for n in wanted_names if n.lower() not in by_name]
            if missing:
                raise Exception(
                    f"Body name(s) not found: {', '.join(missing)}. "
                    f"Available bodies: {', '.join(str(b.Name) for b in bodies)}"
                )
            use = [by_name[n.lower()] for n in wanted_names]
            if len(use) < 2:
                raise Exception("intersect needs at least 2 body names")
        else:
            use = list(bodies)

        doc.ClearSelection2(True)
        # COMMON: main body must be null; all bodies go in the array
        main = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        arr = win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, use)
        feature = doc.FeatureManager.InsertCombineFeature(15901, main, arr)

        if not feature:
            raise Exception(
                "Intersect (COMMON) failed — the selected bodies must overlap. "
                "Nothing was created."
            )
        doc.ForceRebuild3(True)

        feature_name = feature.Name
        doc.ViewZoomtofit2()
        remaining = doc.GetBodies2(0, True)
        logger.info(f"Intersect (COMMON) '{feature_name}' created from {len(use)} bodies")
        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(
                feature_name, "intersect", parameters={"bodies": len(use)})
        return self._json_result(
            f"✓ Intersect '{feature_name}' created: kept the common volume of "
            f"{len(use)} bodies ({len(remaining) if remaining else 0} body(ies) remain).",
            id=feature_id, type="intersect")
