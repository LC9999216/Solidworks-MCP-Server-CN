"""
SolidWorks Cut Feature Tools
Cut Revolve, Cut Sweep, Cut Loft, Boundary Cut
"""

import json
import logging
import math
from mcp.types import Tool
from . import selection_helpers as sel
from .com_utils import exit_active_sketch, resolve_tracked_name

logger = logging.getLogger(__name__)


class CutFeatureTools:
    """Cut feature operations (cut revolve, cut sweep, cut loft, boundary cut)"""

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
                name="solidworks_cut_revolve",
                description="Create a revolved cut by revolving the current sketch around a centerline axis to remove material. The sketch MUST contain a centerline that serves as the revolve axis.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "angle": {
                            "type": "number",
                            "description": "Revolve angle in degrees (default: 360 for full revolution)",
                            "default": 360
                        },
                        "reverse": {
                            "type": "boolean",
                            "description": "Reverse revolve direction (default: false)",
                            "default": False
                        }
                    }
                }
            ),
            Tool(
                name="solidworks_cut_sweep",
                description="Create a swept cut by sweeping a profile sketch along a path sketch to remove material. Both sketches must already exist.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "profileSketch": {
                            "type": "string",
                            "description": "Name of the profile sketch (cross-section), e.g. 'Sketch1'"
                        },
                        "pathSketch": {
                            "type": "string",
                            "description": "Name of the path sketch (trajectory), e.g. 'Sketch2'"
                        }
                    },
                    "required": ["profileSketch", "pathSketch"]
                }
            ),
            Tool(
                name="solidworks_cut_loft",
                description="Create a lofted cut by blending between two or more profile sketches to remove material. The profiles should be closed sketches on different planes.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "profileSketches": {
                            "type": "array",
                            "description": "Ordered array of profile sketch names to loft between, e.g. ['Sketch1', 'Sketch2']",
                            "items": {"type": "string"},
                            "minItems": 2
                        }
                    },
                    "required": ["profileSketches"]
                }
            ),
            Tool(
                name="solidworks_boundary_cut",
                description="Create a boundary cut feature from multiple profile sketches with optional guide curves to remove material.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "profiles": {
                            "type": "array",
                            "description": "Ordered array of direction 1 profile sketch names",
                            "items": {"type": "string"},
                            "minItems": 2
                        },
                        "guideCurves": {
                            "type": "array",
                            "description": "Optional array of direction 2 guide curve sketch names",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["profiles"]
                }
            ),
        ]

    def execute(self, tool_name: str, args: dict) -> str:
        self.connection.ensure_connection()
        dispatch = {
            "solidworks_cut_revolve": lambda: self.cut_revolve(args),
            "solidworks_cut_sweep": lambda: self.cut_sweep(args),
            "solidworks_cut_loft": lambda: self.cut_loft(args),
            "solidworks_boundary_cut": lambda: self.boundary_cut(args),
        }
        handler = dispatch.get(tool_name)
        if not handler:
            raise Exception(f"Unknown cut feature tool: {tool_name}")
        return handler()

    def _list_available_sketches(self, doc) -> str:
        """List all sketch names in the feature tree for error messages."""
        try:
            features = doc.FeatureManager.GetFeatures(True)
            if features:
                names = [f.Name for f in features if f.GetTypeName2 == "ProfileFeature"]
                return ", ".join(names) if names else "none found"
        except Exception:
            pass
        return "none found"

    def _get_latest_sketch_name(self, doc) -> str:
        try:
            features = doc.FeatureManager.GetFeatures(True)
            if features:
                for feature in reversed(features):
                    if feature.GetTypeName2 == "ProfileFeature":
                        return feature.Name
        except Exception as e:
            logger.warning(f"Could not find latest sketch: {e}")
        return "Sketch1"

    def cut_revolve(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        angle_deg = args.get("angle", 360)
        angle_rad = math.radians(angle_deg)
        reverse = args.get("reverse", False)

        # Exit sketch mode (tracker-aware) and select the sketch
        sketch_name = exit_active_sketch(doc, self.tracker) or self._get_latest_sketch_name(doc)
        sketch_feature = doc.FeatureByName(sketch_name)
        if not sketch_feature:
            raise Exception(f"Could not find sketch: {sketch_name}")

        doc.ClearSelection2(True)
        sketch_feature.Select2(False, 0)

        # FeatureRevolve2 with IsCut=True
        feature = doc.FeatureManager.FeatureRevolve2(
            True,       # SingleDir
            True,       # IsSolid
            False,      # IsThin
            True,       # IsCut ← key difference from boss revolve
            reverse,    # ReverseDir
            False,      # BothDirectionUpToSameEntity
            0,          # Dir1Type: 0 = Blind
            0,          # Dir2Type: 0 = Blind
            angle_rad,  # Dir1Angle
            0.0,        # Dir2Angle
            False,      # OffsetReverse1
            False,      # OffsetReverse2
            0.0,        # OffsetDist1
            0.0,        # OffsetDist2
            0,          # ThinType
            0.0,        # ThinThickness1
            0.0,        # ThinThickness2
            True,       # Merge
            True,       # UseFeatScope
            True,       # UseAutoSelect
        )

        if not feature:
            raise Exception("Failed to create cut revolve. Ensure sketch contains a centerline for the axis.")

        feature_name = feature.Name
        doc.ViewZoomtofit2()
        logger.info(f"Cut revolve '{feature_name}' created: {angle_deg}°")
        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(feature_name, "cut_revolve", parameters={"angle": angle_deg})
        return self._json_result(f"✓ Cut revolve '{feature_name}' {angle_deg}° created", id=feature_id, type="cut_revolve")

    def cut_sweep(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        profile_name = self._resolve_name(args["profileSketch"])
        path_name = self._resolve_name(args["pathSketch"])

        # Exit any active sketch (tracker-aware)
        exit_active_sketch(doc, self.tracker)

        # Select profile sketch (mark=1) and path sketch (mark=4)
        sel.clear_selection(doc)
        if not sel.select_sketch(doc, profile_name, mark=1, append=False):
            raise Exception(f"Could not select profile sketch: {profile_name}")
        if not sel.select_sketch(doc, path_name, mark=4, append=True):
            raise Exception(f"Could not select path sketch: {path_name}")

        # InsertCutSwept5 takes exactly 22 parameters on SW2025 —
        # fewer raises DISP_E_PARAMNOTOPTIONAL ('Parameter not optional').
        # Verified live: this call cuts a correct r5 hole through a 40mm cube
        # (probe volume: 60858.4 mm^3 = 64000 - pi*25*40, exact).
        feature = doc.FeatureManager.InsertCutSwept5(
            False,      # Propagate
            False,      # Alignment
            0,          # TwistCtrlOption
            False,      # PathAlign
            False,      # KeepTangency
            False,      # UseFeatScope
            True,       # UseAutoSelect
            0,          # ThinType
            0.0,        # ThinThickness1
            0.0,        # ThinThickness2
            False,      # ThinReverse
            0,          # StartTangentType
            0,          # EndTangentType
            False,      # IsThinBody
            0.0,        # TwistAngle
            False,      # MergeSmoothFaces
            True,       # NormalCut
            0, 0, 0, 0, 0,  # trailing SW2025 params (defaults; count verified live)
        )

        if not feature:
            raise Exception(
                "Failed to create cut sweep. Ensure the profile is a closed sketch, "
                "the path is an open sketch that passes through the solid, and the "
                "path does NOT lie within the profile's plane."
            )

        feature_name = feature.Name
        doc.ViewZoomtofit2()
        logger.info(f"Cut sweep '{feature_name}' created: profile={profile_name}, path={path_name}")
        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(feature_name, "cut_sweep", parameters={"profile": profile_name, "path": path_name})
        return self._json_result(f"✓ Cut sweep '{feature_name}' created (profile: {profile_name}, path: {path_name})", id=feature_id, type="cut_sweep")

    def cut_loft(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        profile_names = [self._resolve_name(n) for n in args["profileSketches"]]
        if len(profile_names) < 2:
            raise Exception("At least 2 profile sketches are required for a cut loft")

        # Exit any active sketch (tracker-aware)
        exit_active_sketch(doc, self.tracker)

        # Select all profile sketches with mark=1
        sel.clear_selection(doc)
        for i, name in enumerate(profile_names):
            if not sel.select_sketch(doc, name, mark=1, append=(i > 0)):
                available = self._list_available_sketches(doc)
                raise Exception(
                    f"Could not select profile sketch: {name}. "
                    f"Available sketches in feature tree: [{available}]"
                )

        # InsertCutBlend2 parameters (18 params for SW2025):
        # Closed, KeepTangency, ForceNonRational, TessToleranceFactor,
        # StartMatchingType, EndMatchingType,
        # StartTangentLength, EndTangentLength,
        # MaintainTangency, Merge, IsThinBody,
        # Thickness1, Thickness2, ThinType,
        # UseFeatScope, UseAutoSelect, Close, GuideCurveInfluence
        feature = doc.FeatureManager.InsertCutBlend2(
            False,  # Closed
            True,   # KeepTangency
            True,   # ForceNonRational
            1.0,    # TessToleranceFactor
            0,      # StartMatchingType: 0 = None
            0,      # EndMatchingType: 0 = None
            1.0,    # StartTangentLength
            1.0,    # EndTangentLength
            False,  # MaintainTangency
            True,   # Merge
            False,  # IsThinBody
            0.0,    # Thickness1
            0.0,    # Thickness2
            0,      # ThinType
            True,   # UseFeatScope
            True,   # UseAutoSelect
            True,   # Close (feature scope)
            0,      # GuideCurveInfluence
        )

        if not feature:
            raise Exception(
                "Failed to create cut loft. Ensure profiles are closed sketches on different planes."
            )

        feature_name = feature.Name
        doc.ViewZoomtofit2()
        logger.info(f"Cut loft '{feature_name}' created from {len(profile_names)} profiles")
        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(feature_name, "cut_loft", parameters={"profiles": profile_names})
        return self._json_result(f"✓ Cut loft '{feature_name}' created from {len(profile_names)} profiles: {', '.join(profile_names)}", id=feature_id, type="cut_loft")

    def boundary_cut(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        profiles = [self._resolve_name(n) for n in args["profiles"]]
        guide_curves = [self._resolve_name(n) for n in args.get("guideCurves", [])]

        if len(profiles) < 2:
            raise Exception("At least 2 profile sketches are required for a boundary cut")

        # Exit any active sketch (tracker-aware)
        exit_active_sketch(doc, self.tracker)

        # Select profiles (mark=1)
        sel.clear_selection(doc)
        for i, name in enumerate(profiles):
            if not sel.select_sketch(doc, name, mark=1, append=(i > 0)):
                available = self._list_available_sketches(doc)
                raise Exception(
                    f"Could not select profile sketch: {name}. "
                    f"Available sketches in feature tree: [{available}]"
                )

        # Select guide curves if provided (mark=2)
        for name in guide_curves:
            if not sel.select_sketch(doc, name, mark=2, append=True):
                logger.warning(f"Could not select guide curve: {name}")

        feature = doc.FeatureManager.InsertBoundaryCut()

        if not feature:
            raise Exception(
                "Failed to create boundary cut. Ensure profiles are closed sketches on different planes."
            )

        feature_name = feature.Name
        doc.ViewZoomtofit2()
        logger.info(f"Boundary cut '{feature_name}' created from {len(profiles)} profiles")
        feature_id = ""
        if self.tracker:
            feature_id = self.tracker.register_feature(feature_name, "boundary_cut", parameters={"profiles": profiles})
        return self._json_result(f"✓ Boundary cut '{feature_name}' created from {len(profiles)} profiles", id=feature_id, type="boundary_cut")
