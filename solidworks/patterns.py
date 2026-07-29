"""
SolidWorks Pattern and Mirror Tools
Linear Pattern, Circular Pattern, Mirror
"""

import json
import logging
import math
from mcp.types import Tool
from . import selection_helpers as sel
from .com_utils import resolve_tracked_name

logger = logging.getLogger(__name__)


class PatternTools:
    """Pattern and mirror feature operations"""

    def __init__(self, connection, tracker=None):
        self.connection = connection
        self.tracker = tracker


    def _json_result(self, result, **extra):
        d = {"result": result}
        d.update(extra)
        return json.dumps(d)

    def _resolve_name(self, name_or_id):
        return resolve_tracked_name(self.tracker, name_or_id)

    def get_tool_definitions(self) -> list[Tool]:
        return [
            Tool(
                name="solidworks_linear_pattern",
                description="Create a linear pattern of features in one or two directions. Specify features to pattern, a direction edge, spacing, and count.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "features": {
                            "type": "array",
                            "description": "Array of feature names to pattern (e.g. ['Cut-Extrude1', 'Fillet1']). Use solidworks_list_features to discover feature names.",
                            "items": {"type": "string"}
                        },
                        "direction1": {
                            "type": "object",
                            "description": "Pattern direction 1: EITHER {\"axis\": \"X\"|\"Y\"|\"Z\"} (PREFERRED — picks any body edge parallel to that model axis, no coordinates needed; use reverseDir1 if the pattern runs the wrong way) OR a point on an edge ({x, y, z} in mm)",
                            "properties": {
                                "axis": {"type": "string", "enum": ["X", "Y", "Z"],
                                         "description": "Model axis for the pattern direction (preferred over coordinates)"},
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            }
                        },
                        "spacing1": {
                            "type": "number",
                            "description": "Spacing between instances in direction 1 (mm)"
                        },
                        "count1": {
                            "type": "integer",
                            "description": "Total number of instances in direction 1 (including original)"
                        },
                        "reverseDir1": {
                            "type": "boolean",
                            "description": "Reverse direction 1 (default: false)",
                            "default": False
                        },
                        "direction2": {
                            "type": "object",
                            "description": "Optional pattern direction 2: {\"axis\": \"X\"|\"Y\"|\"Z\"} (preferred) or a point on an edge ({x, y, z} in mm)",
                            "properties": {
                                "axis": {"type": "string", "enum": ["X", "Y", "Z"],
                                         "description": "Model axis for the pattern direction (preferred over coordinates)"},
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            }
                        },
                        "spacing2": {
                            "type": "number",
                            "description": "Spacing in direction 2 (mm)"
                        },
                        "count2": {
                            "type": "integer",
                            "description": "Total instances in direction 2"
                        },
                        "reverseDir2": {
                            "type": "boolean",
                            "description": "Reverse direction 2 (default: false)",
                            "default": False
                        }
                    },
                    "required": ["features", "direction1", "spacing1", "count1"]
                }
            ),
            Tool(
                name="solidworks_circular_pattern",
                description="Create a circular pattern of features around an axis. Specify features to pattern, a rotation axis, count, and angular spacing.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "features": {
                            "type": "array",
                            "description": "Array of feature names to pattern. Use solidworks_list_features to discover names.",
                            "items": {"type": "string"}
                        },
                        "axis": {
                            "type": "string",
                            "description": "Name of the axis or edge for rotation. Can be a reference axis name, or a standard axis like 'Top Plane' edge."
                        },
                        "axisEdge": {
                            "type": "object",
                            "description": "Alternative: point on an edge to use as axis ({x, y, z} in mm). Use this instead of 'axis' when selecting by coordinate.",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        },
                        "count": {
                            "type": "integer",
                            "description": "Total number of instances (including original)"
                        },
                        "angle": {
                            "type": "number",
                            "description": "Total angle for pattern in degrees (default: 360)",
                            "default": 360
                        },
                        "equalSpacing": {
                            "type": "boolean",
                            "description": "Space instances equally within the angle (default: true)",
                            "default": True
                        }
                    },
                    "required": ["features", "count"]
                }
            ),
            Tool(
                name="solidworks_mirror",
                description="Mirror one or more features about a reference plane or planar face. Creates a symmetric copy of the selected features.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "features": {
                            "type": "array",
                            "description": "Array of feature names to mirror. Use solidworks_list_features to discover names.",
                            "items": {"type": "string"}
                        },
                        "mirrorPlane": {
                            "type": "string",
                            "description": "Mirror plane name ('Front', 'Top', 'Right', or custom plane name)"
                        },
                        "mirrorFace": {
                            "type": "object",
                            "description": "Alternative: point on a planar face to use as mirror plane ({x, y, z} in mm). Use this instead of 'mirrorPlane'.",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        }
                    },
                    "required": ["features"]
                }
            ),
        ]

    def execute(self, tool_name: str, args: dict) -> str:
        self.connection.ensure_connection()
        dispatch = {
            "solidworks_linear_pattern": lambda: self.linear_pattern(args),
            "solidworks_circular_pattern": lambda: self.circular_pattern(args),
            "solidworks_mirror": lambda: self.mirror(args),
        }
        handler = dispatch.get(tool_name)
        if not handler:
            raise Exception(f"Unknown pattern tool: {tool_name}")
        return handler()

    def _select_direction_edge(self, doc, d, mark, append, label):
        """Select a pattern direction edge: {'axis': 'X'|'Y'|'Z'} picks any
        linear body edge parallel to that model axis (object selection,
        view-independent); {x, y, z} picks by coordinate. Raises on failure."""
        axis = (d.get("axis") or "").upper() if isinstance(d, dict) else ""
        if axis:
            if axis not in ("X", "Y", "Z"):
                raise Exception(f"{label} axis must be 'X', 'Y', or 'Z'")
            edge = self._find_linear_edge_parallel(doc, axis)
            if edge is None:
                raise Exception(
                    f"No linear body edge parallel to the {axis} axis found "
                    f"for {label} — pass a coordinate point on an edge instead"
                )
            if not sel.select_entity_object(doc, edge, append=append, mark=mark):
                raise Exception(f"Could not select the {label} edge for axis {axis}")
            return
        if not all(k in d for k in ("x", "y", "z")):
            raise Exception(f"{label} needs either 'axis' or x/y/z coordinates")
        if not sel.select_edge(doc, d["x"], d["y"], d["z"], append=append, mark=mark):
            raise Exception(f"Could not select {label} edge")

    def _find_linear_edge_parallel(self, doc, axis):
        """Any linear body edge parallel to the given model axis, or None."""
        import types as _types
        unit = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}[axis]

        def prop(obj, name):
            v = getattr(obj, name)
            return v() if isinstance(v, _types.MethodType) else v

        try:
            bodies = doc.GetBodies2(0, True)
        except Exception:
            return None
        for body in bodies or []:
            for edge in body.GetEdges() or []:
                try:
                    sv, ev = prop(edge, "GetStartVertex"), prop(edge, "GetEndVertex")
                    if not sv or not ev:
                        continue  # closed curve
                    sp, ep = prop(sv, "GetPoint"), prop(ev, "GetPoint")
                    v = [ep[i] - sp[i] for i in range(3)]
                    chord = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5
                    if chord < 1e-9:
                        continue
                    if abs(sum(v[i] * unit[i] for i in range(3))) / chord < 0.9999:
                        continue
                    # Linear check: curve length == chord length (an arc's
                    # chord can be axis-parallel without the edge being one)
                    params = prop(edge, "GetCurveParams2")
                    curve = prop(edge, "GetCurve")
                    arc_len = curve.GetLength2(params[6], params[7])
                    if abs(arc_len - chord) / chord > 1e-6:
                        continue
                    return edge
                except Exception:
                    continue
        return None

    def linear_pattern(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        features = [self._resolve_name(n) for n in args["features"]]
        dir1 = args["direction1"]
        spacing1_m = args["spacing1"] / 1000.0
        count1 = args["count1"]
        reverse1 = args.get("reverseDir1", False)

        # Direction 2 (optional) — all-or-nothing: a partial spec (direction2
        # without count2, count2 without spacing2, ...) used to silently
        # produce a one-direction pattern with a ✓.
        dir2 = args.get("direction2")
        spacing2_m = args.get("spacing2", 0) / 1000.0 if args.get("spacing2") else 0.0
        count2 = args.get("count2", 1)
        reverse2 = args.get("reverseDir2", False)
        use_dir2 = dir2 is not None or args.get("spacing2") is not None or count2 > 1
        if use_dir2 and not (dir2 is not None and args.get("spacing2") and count2 > 1):
            raise Exception(
                "For a second pattern direction, provide direction2, spacing2, "
                "and count2 (> 1) together"
            )

        sel.clear_selection(doc)

        # Select direction 1 edge (mark=1)
        self._select_direction_edge(doc, dir1, mark=1, append=False, label="direction 1")

        # Select direction 2 edge if needed (mark=2)
        if use_dir2:
            self._select_direction_edge(doc, dir2, mark=2, append=True, label="direction 2")

        # Select features to pattern (mark=4)
        for i, name in enumerate(features):
            if not sel.select_feature(doc, name, mark=4, append=True):
                raise Exception(f"Could not select feature: {name}")

        # FeatureLinearPattern4 (20 params, probed live on SW2025 —
        # the older 11/12-param forms raise 'Parameter not optional'):
        # Num1, Spacing1, Num2, Spacing2, FlipDir1, FlipDir2, DName1, DName2,
        # GeometryPattern, VaryInstance, HasOffset1, HasOffset2,
        # CtrlByNum1, CtrlByNum2, FromCentroid1, FromCentroid2,
        # RevOffset1, RevOffset2, Offset1, Offset2
        feature = doc.FeatureManager.FeatureLinearPattern4(
            count1,         # Num1: instances in direction 1
            spacing1_m,     # Spacing1 (m)
            count2 if use_dir2 else 1,  # Num2
            spacing2_m,     # Spacing2 (m)
            reverse1,       # FlipDir1
            reverse2,       # FlipDir2
            "", "",         # DName1, DName2 (vary-instance dim names)
            False, False,   # GeometryPattern, VaryInstance
            False, False,   # HasOffset1, HasOffset2
            True, True,     # CtrlByNum1, CtrlByNum2 (number+spacing control)
            False, False,   # FromCentroid1, FromCentroid2
            False, False,   # RevOffset1, RevOffset2
            0.0, 0.0,       # Offset1, Offset2
        )

        if not feature:
            raise Exception("Failed to create linear pattern. Verify feature names and direction edge.")

        feature_name = feature.Name
        doc.ViewZoomtofit2()
        total = count1 * count2 if use_dir2 else count1

        # Register with tracker
        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(feature_name, "linear_pattern", parameters={
                "spacing1": args["spacing1"], "count1": count1,
            })

        logger.info(f"Linear pattern '{feature_name}' created: {total} instances")
        result = f"✓ Linear pattern '{feature_name}' created: {count1}x{count2 if use_dir2 else 1} = {total} instances"
        return self._json_result(result, id=feature_id, type="linear_pattern")

    def circular_pattern(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        features = [self._resolve_name(n) for n in args["features"]]
        count = args["count"]
        angle_deg = args.get("angle", 360)
        angle_rad = math.radians(angle_deg)
        equal_spacing = args.get("equalSpacing", True)

        sel.clear_selection(doc)

        # Select axis (mark=1)
        axis_name = args.get("axis")
        axis_edge = args.get("axisEdge")
        if axis_name:
            if not sel.select_axis(doc, axis_name, mark=1, append=False):
                # Try as edge
                if not sel.select_feature(doc, axis_name, mark=1, append=False):
                    raise Exception(f"Could not select axis: {axis_name}")
        elif axis_edge:
            if not sel.select_edge(doc, axis_edge["x"], axis_edge["y"], axis_edge["z"], append=False, mark=1):
                raise Exception("Could not select axis edge")
        else:
            raise Exception("Either 'axis' or 'axisEdge' must be provided")

        # Select features to pattern (mark=4)
        for i, name in enumerate(features):
            if not sel.select_feature(doc, name, mark=4, append=True):
                raise Exception(f"Could not select feature: {name}")

        # FeatureCircularPattern4 parameters:
        # Num, Spacing, FlipDir, EqualSpacing,
        # SeedOnly, GeomPattern, VarySketch, ...
        feature = doc.FeatureManager.FeatureCircularPattern4(
            count,          # Num: number of instances
            angle_rad,      # Spacing: total angle in radians
            False,          # FlipDir
            equal_spacing,  # EqualSpacing
            True,           # SeedOnly
            False,          # GeomPattern
            False,          # VarySketch
        )

        if not feature:
            raise Exception("Failed to create circular pattern. Verify feature names and axis.")

        feature_name = feature.Name
        doc.ViewZoomtofit2()

        # Register with tracker
        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(feature_name, "circular_pattern", parameters={
                "count": count, "angle": angle_deg,
            })

        logger.info(f"Circular pattern '{feature_name}' created: {count} instances over {angle_deg}°")
        result = f"✓ Circular pattern '{feature_name}' created: {count} instances over {angle_deg}°"
        return self._json_result(result, id=feature_id, type="circular_pattern")

    def mirror(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        features = [self._resolve_name(n) for n in args["features"]]
        mirror_plane = args.get("mirrorPlane")
        mirror_face = args.get("mirrorFace")

        sel.clear_selection(doc)

        # Selection marks for InsertMirrorFeature2, probed live on SW2025:
        # mirror plane/face = mark 2, features to mirror = mark 1.
        # (The previous plane mark=4 + BodyMirror=True combination ALWAYS
        # returned None — the tool had never successfully mirrored anything.)
        if mirror_plane:
            if not sel.select_plane_with_mark(doc, mirror_plane, mark=2, append=False):
                raise Exception(f"Could not select mirror plane: {mirror_plane}")
        elif mirror_face:
            if not sel.select_face(doc, mirror_face["x"], mirror_face["y"], mirror_face["z"], append=False, mark=2):
                raise Exception("Could not select mirror face")
        else:
            raise Exception("Either 'mirrorPlane' or 'mirrorFace' must be provided")

        # Select features to mirror (mark=1)
        for i, name in enumerate(features):
            if not sel.select_feature(doc, name, mark=1, append=True):
                raise Exception(f"Could not select feature: {name}")

        # InsertMirrorFeature2(BodyMirror, GeometryPattern,
        #                      PropagateVisualProps, Merge, KnitSurface)
        # BodyMirror=False mirrors the selected FEATURES (what this tool
        # advertises). Verified live: asymmetric notch cut mirrored about the
        # Right plane removed exactly the mirrored notch volume.
        feature = doc.FeatureManager.InsertMirrorFeature2(
            False,  # BodyMirror: False = mirror features, True = mirror body
            False,  # GeometryPattern
            False,  # PropagateVisualProps
            True,   # Merge
            False,  # KnitSurface
        )

        if not feature:
            raise Exception("Failed to create mirror feature. Verify plane and feature selections.")

        feature_name = feature.Name
        doc.ViewZoomtofit2()

        # Register with tracker
        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(feature_name, "mirror")

        logger.info(f"Mirror '{feature_name}' created for {len(features)} feature(s)")
        result = f"✓ Mirror '{feature_name}' created for {len(features)} feature(s)"
        return self._json_result(result, id=feature_id, type="mirror")
