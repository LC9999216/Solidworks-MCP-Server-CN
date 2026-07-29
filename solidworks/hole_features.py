"""
SolidWorks Hole Feature Tools
Hole Wizard, Thread

NOTE: Advanced Hole and Stud are deferred - these are wizard-driven UI features
that are extremely unlikely to work via COM automation without blocking dialogs.
"""

import json
import logging
from mcp.types import Tool
from . import selection_helpers as sel

logger = logging.getLogger(__name__)


class HoleFeatureTools:
    """Hole and thread feature operations"""

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
                name="solidworks_hole_wizard",
                description=(
                    "Create a Hole Wizard hole on a selected face. Supports counterbore, countersink, "
                    "standard hole, straight tap, and tapered tap types. NOTE: This feature uses the "
                    "HoleWizard COM API which may trigger a blocking dialog in some SolidWorks versions. "
                    "If it fails, use a sketch circle + cut-extrude as a workaround."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["COUNTERBORE", "COUNTERSINK", "HOLE", "STRAIGHT_TAP", "TAPERED_TAP", "LEGACY"],
                            "description": "Hole type"
                        },
                        "standard": {
                            "type": "integer",
                            "description": "Hole standard: 0=Ansi Inch, 1=Ansi Metric, 2=AS, 3=BSP, 4=DIN, 5=DME, 6=GB, 7=Hasco, 8=IS, 9=ISO, 10=JIS, 11=KS, 12=PCS, 13=Progressive, 14=Superior"
                        },
                        "fastenerType": {
                            "type": "string",
                            "description": "Fastener type string (e.g., 'Hex Bolt', 'Socket Head Cap Screw'). Depends on the standard selected."
                        },
                        "size": {
                            "type": "string",
                            "description": "Hole size designation (e.g., 'M10', '#10', '1/4')"
                        },
                        "endCondition": {
                            "type": "string",
                            "enum": ["BLIND", "THROUGH_ALL", "UP_TO_NEXT"],
                            "description": "Hole end condition (default: BLIND)",
                            "default": "BLIND"
                        },
                        "depth": {
                            "type": "number",
                            "description": "Hole depth in mm (for BLIND end condition)"
                        },
                        "face": {
                            "type": "object",
                            "description": "Point on the face to place hole ({x, y, z} in mm)",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        },
                        "positions": {
                            "type": "array",
                            "description": "Array of hole center positions on the face. Each is {x, y} in mm (2D coordinates on the face plane).",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "x": {"type": "number"},
                                    "y": {"type": "number"}
                                },
                                "required": ["x", "y"]
                            }
                        }
                    },
                    "required": ["type", "standard", "face"]
                }
            ),
            Tool(
                name="solidworks_thread",
                description=(
                    "Apply a cosmetic thread to a cylindrical edge or face. Cosmetic threads display "
                    "thread callouts in drawings but do not modify the solid geometry."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "edge": {
                            "type": "object",
                            "description": "Point on the circular edge to apply thread ({x, y, z} in mm)",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"}
                            },
                            "required": ["x", "y", "z"]
                        },
                        "depth": {
                            "type": "number",
                            "description": "Thread depth/length (mm)"
                        },
                        "diameter": {
                            "type": "number",
                            "description": "Minor diameter (mm) for the thread display"
                        }
                    },
                    "required": ["edge", "depth", "diameter"]
                }
            ),
        ]

    def execute(self, tool_name: str, args: dict) -> str:
        self.connection.ensure_connection()
        dispatch = {
            "solidworks_hole_wizard": lambda: self.hole_wizard(args),
            "solidworks_thread": lambda: self.thread(args),
        }
        handler = dispatch.get(tool_name)
        if not handler:
            raise Exception(f"Unknown hole feature tool: {tool_name}")
        return handler()

    def hole_wizard(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        hole_type = args["type"]
        standard = args["standard"]
        face = args["face"]
        end_condition = args.get("endCondition", "BLIND")
        depth_m = args.get("depth", 10) / 1000.0

        # Map hole type to SolidWorks enum
        type_map = {
            "COUNTERBORE": 4,
            "COUNTERSINK": 5,
            "HOLE": 6,
            "STRAIGHT_TAP": 7,
            "TAPERED_TAP": 8,
            "LEGACY": 9,
        }
        hole_type_int = type_map.get(hole_type, 6)

        # Map end condition
        end_map = {
            "BLIND": 0,
            "THROUGH_ALL": 1,
            "UP_TO_NEXT": 11,
        }
        end_condition_int = end_map.get(end_condition, 0)

        # Select the face
        sel.clear_selection(doc)
        if not sel.select_face(doc, face["x"], face["y"], face["z"]):
            raise Exception("Could not select face for hole placement")

        # Try with AddToDB to suppress potential dialog
        sm = doc.SketchManager
        sm.AddToDB = True
        sm.DisplayWhenAdded = False

        try:
            # HoleWizard5 params:
            # GenericHoleType, StandardIndex, FastenerTypeIndex, SSize,
            # EndType, Depth, Value1, Value2, Value3, Value4, Value5,
            # Value6, Value7, Value8, Value9, Value10, Value11, Value12
            feature = doc.FeatureManager.HoleWizard5(
                hole_type_int,      # GenericHoleType
                standard,           # StandardIndex
                0,                  # FastenerTypeIndex
                args.get("size", ""),  # SSize
                end_condition_int,  # EndType
                depth_m,            # Depth in meters
                depth_m,            # Value1 (head counterbore depth)
                0.0,                # Value2
                0.0,                # Value3
                0.0,                # Value4
                0.0,                # Value5
                0.0,                # Value6
                0.0,                # Value7
                0.0,                # Value8
                0.0,                # Value9
                0.0,                # Value10
                0.0,                # Value11
                0.0,                # Value12
            )
        finally:
            sm.AddToDB = False
            sm.DisplayWhenAdded = True

        if not feature:
            raise Exception(
                "Failed to create Hole Wizard hole. This may be due to a blocking dialog issue. "
                "Workaround: create a sketch circle and use cut-extrude instead."
            )

        feature_name = feature.Name
        feature_id = None
        if self.tracker:
            feature_id = self.tracker.register_feature(feature_name, "hole_wizard", parameters={
                "hole_type": hole_type,
                "standard": standard,
                "endCondition": end_condition,
                "depth": args.get("depth", 10),
            })
        doc.ViewZoomtofit2()
        logger.info(f"Hole Wizard '{feature_name}' created: {hole_type}")
        return self._json_result(f"✓ Hole Wizard '{feature_name}' {hole_type} hole created", id=feature_id, type="hole_wizard")

    def thread(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        edge = args["edge"]
        depth_m = args["depth"] / 1000.0
        diameter_m = args["diameter"] / 1000.0

        sel.clear_selection(doc)
        if not sel.select_edge(doc, edge["x"], edge["y"], edge["z"]):
            raise Exception("Could not select edge for thread")

        # InsertCosmeticThread3 creates a cosmetic thread annotation
        # Params: ThreadLength, MinorDiameter, ...
        feature = doc.InsertCosmeticThread3(
            depth_m,        # Thread length in meters
            diameter_m,     # Minor diameter in meters
            0,              # Thread type: 0 = standard
            True,           # Flip direction
        )

        if not feature:
            raise Exception("Failed to create cosmetic thread. Ensure a circular edge is selected.")

        feature_name = feature.Name
        feature_id = None
        if self.tracker:
            feature_id = self.tracker.register_feature(feature_name, "thread", parameters={
                "depth": args["depth"],
                "diameter": args["diameter"],
            })
        doc.ViewZoomtofit2()
        logger.info(f"Cosmetic thread '{feature_name}' created: depth={args['depth']}mm, diameter={args['diameter']}mm")
        return self._json_result(f"✓ Cosmetic thread '{feature_name}' created: {args['depth']}mm deep, {args['diameter']}mm diameter", id=feature_id, type="thread")
