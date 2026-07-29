"""
SolidWorks Reference Geometry Tools
Reference Plane, Reference Axis, Reference Point, Coordinate System
"""

import json
import logging
import math
from mcp.types import Tool
from . import selection_helpers as sel

logger = logging.getLogger(__name__)


class ReferenceGeometryTools:
    """Reference geometry creation operations"""

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
                name="solidworks_ref_plane",
                description="Create a reference plane. Supports offset from a reference plane, at an angle to a plane through an edge, or through a point parallel to a plane.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["OFFSET", "ANGLE", "THROUGH_POINT"],
                            "description": "Plane creation type (default: OFFSET)",
                            "default": "OFFSET"
                        },
                        "referencePlane": {
                            "type": "string",
                            "description": "Base reference plane name ('Front', 'Top', 'Right', or custom). Required for OFFSET and ANGLE types."
                        },
                        "offset": {
                            "type": "number",
                            "description": "Offset distance (mm) from reference plane. Used for OFFSET type."
                        },
                        "reverse": {
                            "type": "boolean",
                            "description": "Reverse offset/angle direction (default: false)",
                            "default": False
                        },
                        "angle": {
                            "type": "number",
                            "description": "Angle in degrees from reference plane. Used for ANGLE type."
                        },
                        "edge": {
                            "type": "object",
                            "description": "Point on an edge for ANGLE type ({x, y, z} in mm). The plane rotates around this edge.",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        },
                        "point": {
                            "type": "object",
                            "description": "Point for THROUGH_POINT type ({x, y, z} in mm). Creates a plane through this point parallel to referencePlane.",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        }
                    }
                }
            ),
            Tool(
                name="solidworks_ref_axis",
                description="Create a reference axis. Can be defined by two points, a cylindrical face, or an edge.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["TWO_POINTS", "CYLINDRICAL_FACE", "EDGE"],
                            "description": "Axis creation type"
                        },
                        "point1": {
                            "type": "object",
                            "description": "First point ({x, y, z} in mm) for TWO_POINTS type",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        },
                        "point2": {
                            "type": "object",
                            "description": "Second point ({x, y, z} in mm) for TWO_POINTS type",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        },
                        "face": {
                            "type": "object",
                            "description": "Point on a cylindrical face ({x, y, z} in mm) for CYLINDRICAL_FACE type",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        },
                        "edge": {
                            "type": "object",
                            "description": "Point on an edge ({x, y, z} in mm) for EDGE type",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        }
                    },
                    "required": ["type"]
                }
            ),
            Tool(
                name="solidworks_ref_point",
                description="Create a reference point at specific coordinates, at the center of an arc/edge, or on a face.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["COORDINATES", "ARC_CENTER", "FACE_CENTER", "ON_EDGE"],
                            "description": "Point creation type (default: COORDINATES)",
                            "default": "COORDINATES"
                        },
                        "x": {
                            "type": "number",
                            "description": "X coordinate (mm) for COORDINATES type"
                        },
                        "y": {
                            "type": "number",
                            "description": "Y coordinate (mm) for COORDINATES type"
                        },
                        "z": {
                            "type": "number",
                            "description": "Z coordinate (mm) for COORDINATES type"
                        },
                        "edge": {
                            "type": "object",
                            "description": "Point on an edge/arc ({x, y, z} in mm) for ARC_CENTER or ON_EDGE type",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        },
                        "face": {
                            "type": "object",
                            "description": "Point on a face ({x, y, z} in mm) for FACE_CENTER type",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        }
                    }
                }
            ),
            Tool(
                name="solidworks_coordinate_system",
                description="Create a coordinate system at a specified origin with optional axis directions defined by edges or vertices.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "origin": {
                            "type": "object",
                            "description": "Origin point ({x, y, z} in mm)",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        },
                        "xAxisEdge": {
                            "type": "object",
                            "description": "Optional: point on edge defining X axis direction ({x, y, z} in mm)",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        },
                        "yAxisEdge": {
                            "type": "object",
                            "description": "Optional: point on edge defining Y axis direction ({x, y, z} in mm)",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        }
                    },
                    "required": ["origin"]
                }
            ),
        ]

    def execute(self, tool_name: str, args: dict) -> str:
        self.connection.ensure_connection()
        dispatch = {
            "solidworks_ref_plane": lambda: self.ref_plane(args),
            "solidworks_ref_axis": lambda: self.ref_axis(args),
            "solidworks_ref_point": lambda: self.ref_point(args),
            "solidworks_coordinate_system": lambda: self.coordinate_system(args),
        }
        handler = dispatch.get(tool_name)
        if not handler:
            raise Exception(f"Unknown reference geometry tool: {tool_name}")
        return handler()

    def ref_plane(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        plane_type = args.get("type", "OFFSET")
        ref_plane_name = args.get("referencePlane", "Front")
        reverse = args.get("reverse", False)

        sel.clear_selection(doc)

        if plane_type == "OFFSET":
            offset_m = args.get("offset", 0) / 1000.0
            if reverse:
                offset_m = -offset_m

            # Select reference plane
            if not sel.select_plane_with_mark(doc, ref_plane_name, mark=0, append=False):
                raise Exception(f"Could not select reference plane: {ref_plane_name}")

            # swRefPlaneReferenceConstraints_e is a BIT-FLAG enum (probed live):
            # Parallel=1, Perpendicular=2, Coincident=4, Distance=8, Angle=16
            feature = doc.FeatureManager.InsertRefPlane(
                8,          # First constraint: Distance
                offset_m,   # Distance value in meters
                0,          # Second ref: none
                0,          # Second value
                0,          # Third ref: none
                0,          # Third value
            )

            if not feature:
                raise Exception("Failed to create offset reference plane")

            plane_name = feature.Name
            ref_id = None
            if self.tracker:
                ref_id = self.tracker.register_ref_geometry(plane_name, "plane", parameters={
                    "method": "OFFSET",
                    "referencePlane": ref_plane_name,
                    "offset": args.get("offset", 0),
                })

            doc.ViewZoomtofit2()
            offset_mm = args.get("offset", 0)
            logger.info(f"Reference plane '{plane_name}' created: offset {offset_mm}mm from {ref_plane_name}")
            return self._json_result(f"✓ Reference plane '{plane_name}' created: offset {offset_mm}mm from {ref_plane_name}", id=ref_id, type="ref_plane")

        elif plane_type == "ANGLE":
            angle_deg = args.get("angle", 0)
            angle_rad = math.radians(angle_deg)
            if reverse:
                angle_rad = -angle_rad

            # Select reference plane
            if not sel.select_plane_with_mark(doc, ref_plane_name, mark=0, append=False):
                raise Exception(f"Could not select reference plane: {ref_plane_name}")

            # Select edge for rotation axis (mark=1 — second constraint)
            edge = args.get("edge")
            if not edge:
                raise Exception("'edge' (a point on the rotation-axis edge) is required for ANGLE type")
            sel.select_edge(doc, edge["x"], edge["y"], edge["z"], append=True, mark=1)

            # Bit-flag enum (probed live): Angle=16 on the plane, Coincident=4 on
            # the axis edge — an angled plane needs BOTH constraints.
            feature = doc.FeatureManager.InsertRefPlane(
                16,          # First constraint: Angle (on the selected plane)
                angle_rad,   # Angle in radians
                4,           # Second constraint: Coincident (with the axis edge)
                0,           # Second value
                0,           # Third ref
                0,           # Third value
            )

            if not feature:
                raise Exception("Failed to create angled reference plane")

            plane_name = feature.Name
            ref_id = None
            if self.tracker:
                ref_id = self.tracker.register_ref_geometry(plane_name, "plane", parameters={
                    "method": "ANGLE",
                    "referencePlane": ref_plane_name,
                    "angle": angle_deg,
                })

            doc.ViewZoomtofit2()
            logger.info(f"Reference plane '{plane_name}' created: {angle_deg}° from {ref_plane_name}")
            return self._json_result(f"✓ Reference plane '{plane_name}' created: {angle_deg}° from {ref_plane_name}", id=ref_id, type="ref_plane")

        elif plane_type == "THROUGH_POINT":
            point = args.get("point")
            if not point:
                raise Exception("'point' is required for THROUGH_POINT type")

            # Select reference plane (parallel to)
            if not sel.select_plane_with_mark(doc, ref_plane_name, mark=0, append=False):
                raise Exception(f"Could not select reference plane: {ref_plane_name}")

            # Select the point (mark=1 — second constraint)
            sel.select_vertex(doc, point["x"], point["y"], point["z"], mark=1, append=True)

            # Bit-flag enum (probed live): Parallel=1 to the plane,
            # Coincident=4 with the vertex
            feature = doc.FeatureManager.InsertRefPlane(
                1,          # First constraint: Parallel (to the selected plane)
                0,          # Value
                4,          # Second constraint: Coincident (with the vertex)
                0,          # Value
                0,          # Third ref
                0,          # Third value
            )

            if not feature:
                raise Exception("Failed to create reference plane through point")

            plane_name = feature.Name
            ref_id = None
            if self.tracker:
                ref_id = self.tracker.register_ref_geometry(plane_name, "plane", parameters={
                    "method": "THROUGH_POINT",
                    "referencePlane": ref_plane_name,
                    "point": point,
                })

            doc.ViewZoomtofit2()
            logger.info(f"Reference plane '{plane_name}' created through point, parallel to {ref_plane_name}")
            return self._json_result(f"✓ Reference plane '{plane_name}' created through point, parallel to {ref_plane_name}", id=ref_id, type="ref_plane")

        else:
            raise Exception(f"Unknown plane type: {plane_type}")

    def ref_axis(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        axis_type = args["type"]

        sel.clear_selection(doc)

        if axis_type == "TWO_POINTS":
            p1 = args.get("point1")
            p2 = args.get("point2")
            if not p1 or not p2:
                raise Exception("Both point1 and point2 are required for TWO_POINTS type")

            sel.select_vertex(doc, p1["x"], p1["y"], p1["z"], mark=0, append=False)
            sel.select_vertex(doc, p2["x"], p2["y"], p2["z"], mark=0, append=True)

        elif axis_type == "CYLINDRICAL_FACE":
            face = args.get("face")
            if not face:
                raise Exception("'face' is required for CYLINDRICAL_FACE type")
            sel.select_face(doc, face["x"], face["y"], face["z"], append=False, mark=0)

        elif axis_type == "EDGE":
            edge = args.get("edge")
            if not edge:
                raise Exception("'edge' is required for EDGE type")
            sel.select_edge(doc, edge["x"], edge["y"], edge["z"], append=False, mark=0)

        else:
            raise Exception(f"Unknown axis type: {axis_type}")

        feature = doc.FeatureManager.InsertRefAxis()

        if not feature:
            raise Exception("Failed to create reference axis. Verify selections.")

        feature_name = feature.Name
        ref_id = None
        if self.tracker:
            ref_id = self.tracker.register_ref_geometry(feature_name, "axis", parameters={
                "method": axis_type,
            })

        doc.ViewZoomtofit2()
        logger.info(f"Reference axis '{feature_name}' created ({axis_type})")
        return self._json_result(f"✓ Reference axis '{feature_name}' created ({axis_type})", id=ref_id, type="ref_axis")

    def ref_point(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        point_type = args.get("type", "COORDINATES")

        sel.clear_selection(doc)

        if point_type == "COORDINATES":
            x = args.get("x", 0)
            y = args.get("y", 0)
            z = args.get("z", 0)

            # For coordinate-based points, we use InsertReferencePoint
            # Select nothing, then create at coordinates
            # swRefPointAlongCurve = 0, swRefPointOnFace = 1, swRefPointOnVertex = 2
            feature = doc.FeatureManager.InsertReferencePoint(
                4,              # Type: 4 = arbitrary coordinates
                0,              # AlongCurveOption
                x / 1000.0,    # X in meters
                y / 1000.0,    # Y in meters
                z / 1000.0,    # Z in meters
            )

            if not feature:
                raise Exception("Failed to create reference point at coordinates")

            feature_name = feature.Name
            ref_id = None
            if self.tracker:
                ref_id = self.tracker.register_ref_geometry(feature_name, "point", parameters={
                    "method": "COORDINATES",
                    "x": x, "y": y, "z": z,
                })

            doc.ViewZoomtofit2()
            logger.info(f"Reference point '{feature_name}' created at ({x}, {y}, {z}) mm")
            return self._json_result(f"✓ Reference point '{feature_name}' created at ({x}, {y}, {z}) mm", id=ref_id, type="ref_point")

        elif point_type == "ARC_CENTER":
            edge = args.get("edge")
            if not edge:
                raise Exception("'edge' is required for ARC_CENTER type")
            sel.select_edge(doc, edge["x"], edge["y"], edge["z"], append=False, mark=0)

            feature = doc.FeatureManager.InsertReferencePoint(
                3,      # Type: 3 = center
                0, 0, 0, 0,
            )

            if not feature:
                raise Exception("Failed to create reference point at arc center")

            feature_name = feature.Name
            ref_id = None
            if self.tracker:
                ref_id = self.tracker.register_ref_geometry(feature_name, "point", parameters={
                    "method": "ARC_CENTER",
                })

            doc.ViewZoomtofit2()
            logger.info(f"Reference point '{feature_name}' created at arc center")
            return self._json_result(f"✓ Reference point '{feature_name}' created at arc center", id=ref_id, type="ref_point")

        elif point_type == "FACE_CENTER":
            face = args.get("face")
            if not face:
                raise Exception("'face' is required for FACE_CENTER type")
            sel.select_face(doc, face["x"], face["y"], face["z"], append=False, mark=0)

            feature = doc.FeatureManager.InsertReferencePoint(
                1,      # Type: 1 = on face
                0, 0, 0, 0,
            )

            if not feature:
                raise Exception("Failed to create reference point on face")

            feature_name = feature.Name
            ref_id = None
            if self.tracker:
                ref_id = self.tracker.register_ref_geometry(feature_name, "point", parameters={
                    "method": "FACE_CENTER",
                })

            doc.ViewZoomtofit2()
            logger.info(f"Reference point '{feature_name}' created at face center")
            return self._json_result(f"✓ Reference point '{feature_name}' created at face center", id=ref_id, type="ref_point")

        elif point_type == "ON_EDGE":
            edge = args.get("edge")
            if not edge:
                raise Exception("'edge' is required for ON_EDGE type")
            sel.select_edge(doc, edge["x"], edge["y"], edge["z"], append=False, mark=0)

            feature = doc.FeatureManager.InsertReferencePoint(
                0,      # Type: 0 = along curve
                0, 0, 0, 0,
            )

            if not feature:
                raise Exception("Failed to create reference point on edge")

            feature_name = feature.Name
            ref_id = None
            if self.tracker:
                ref_id = self.tracker.register_ref_geometry(feature_name, "point", parameters={
                    "method": "ON_EDGE",
                })

            doc.ViewZoomtofit2()
            logger.info(f"Reference point '{feature_name}' created on edge")
            return self._json_result(f"✓ Reference point '{feature_name}' created on edge", id=ref_id, type="ref_point")

        else:
            raise Exception(f"Unknown point type: {point_type}")

    def coordinate_system(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        origin = args["origin"]

        sel.clear_selection(doc)

        # Selection marks for InsertCoordinateSystem (verified live on SW2025):
        # origin vertex = 1, X-axis entity = 2, Y-axis entity = 4
        sel.select_vertex(doc, origin["x"], origin["y"], origin["z"], mark=1, append=False)

        x_edge = args.get("xAxisEdge")
        if x_edge:
            sel.select_edge(doc, x_edge["x"], x_edge["y"], x_edge["z"], mark=2, append=True)

        y_edge = args.get("yAxisEdge")
        if y_edge:
            sel.select_edge(doc, y_edge["x"], y_edge["y"], y_edge["z"], mark=4, append=True)

        # InsertCoordinateSystem takes exactly 3 args (FlipX, FlipY, FlipZ) —
        # passing more raises 'Invalid number of parameters' (verified live)
        feature = doc.FeatureManager.InsertCoordinateSystem(False, False, False)

        if not feature:
            raise Exception("Failed to create coordinate system. Verify origin vertex selection.")

        feature_name = feature.Name
        ref_id = None
        if self.tracker:
            ref_id = self.tracker.register_ref_geometry(feature_name, "coordinate_system", parameters={
                "origin": origin,
            })

        doc.ViewZoomtofit2()
        logger.info(f"Coordinate system '{feature_name}' created at ({origin['x']}, {origin['y']}, {origin['z']}) mm")
        return self._json_result(f"✓ Coordinate system '{feature_name}' created at ({origin['x']}, {origin['y']}, {origin['z']}) mm", id=ref_id, type="coordinate_system")
