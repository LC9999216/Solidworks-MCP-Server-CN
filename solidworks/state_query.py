"""
SolidWorks State Query Tools
MCP tools for querying the tracked state of features, sketches, and entities.

get_state combines the pure-Python tracker summary with best-effort live COM
enrichment (bounding box, sketch constraint status, feature tree, active
configuration). Every COM enrichment is wrapped in try/except so get_state
never fails just because SolidWorks is busy or disconnected.
"""

import json
import logging
from mcp.types import Tool
from .state_tracker import SketchEntityRecord, SketchRecord, FeatureRecord, RefGeometryRecord
from .com_utils import com_prop as _prop

logger = logging.getLogger(__name__)

# ISketch.GetConstrainedStatus values (verified empirically on SW2025):
#   3 = fully defined, 2 = under defined (an empty sketch also reports 2)
CONSTRAINED_STATUS = {
    3: "FULLY_DEFINED",
    2: "UNDER_DEFINED",
}


def _json_result(result, **extra):
    d = {"result": result}
    d.update(extra)
    return json.dumps(d)


class StateQueryTools:
    """Tools for querying the state tracker."""

    def __init__(self, tracker, connection=None):
        self.tracker = tracker
        self.connection = connection

    def get_tool_definitions(self) -> list[Tool]:
        return [
            Tool(
                name="solidworks_get_state",
                description="Get a summary of the current session: tracked features, sketches, entities, and reference geometry with their IDs, plus live model context (bounding box, sketch constraint status, active configuration). Use detail='full' to also include the feature dependency tree (parents/children per feature).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "detail": {
                            "type": "string",
                            "enum": ["summary", "full"],
                            "description": "'summary' (default) = tracked objects + bounding box + sketch status. 'full' adds feature parent/child dependencies."
                        }
                    }
                }
            ),
            Tool(
                name="solidworks_get_entity",
                description="Get detailed information about a tracked object by its ID. Accepts feature IDs (feat:...), sketch IDs (sketch:...), entity IDs (entity:...), or reference IDs (ref:...).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "The stable ID of the object to query (e.g., 'feat:Boss-Extrude1', 'sketch:Sketch1', 'entity:Sketch1/line_0')"
                        }
                    },
                    "required": ["id"]
                }
            ),
            Tool(
                name="solidworks_get_sketch_entities",
                description="List all tracked sketch entities in a specific sketch. Returns entity IDs, types, and coordinates.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "sketchId": {
                            "type": "string",
                            "description": "Sketch ID (e.g., 'sketch:Sketch1') or just the sketch name (e.g., 'Sketch1')"
                        }
                    },
                    "required": ["sketchId"]
                }
            ),
        ]

    def execute(self, tool_name: str, args: dict) -> str:
        args = args or {}
        if tool_name == "solidworks_get_state":
            return self._get_state(args)
        elif tool_name == "solidworks_get_entity":
            return self._get_entity(args)
        elif tool_name == "solidworks_get_sketch_entities":
            return self._get_sketch_entities(args)
        else:
            raise Exception(f"Unknown state query tool: {tool_name}")

    # --- Live COM enrichment helpers (all best-effort) ---

    def _get_live_doc(self):
        if not self.connection:
            return None
        try:
            if not self.connection.is_alive():
                return None
            return self.connection.get_active_doc()
        except Exception:
            return None

    def _enrich_document_info(self, summary, doc):
        try:
            info = summary.get("activeDocument") or {}
            info.setdefault("name", doc.GetTitle)
            doc_type = int(_prop(doc, "GetType"))
            info["type"] = {1: "part", 2: "assembly", 3: "drawing"}.get(doc_type, "unknown")
            info["configuration"] = doc.ConfigurationManager.ActiveConfiguration.Name
            summary["activeDocument"] = info
        except Exception as e:
            logger.debug(f"get_state: document info enrichment failed: {e}")

    def _enrich_body_overview(self, summary, doc):
        """Bounding box and topology counts for part documents (no forced rebuild)."""
        try:
            if int(_prop(doc, "GetType")) != 1:  # parts only
                return
            bodies = doc.GetBodies2(0, True)
            if not bodies:
                return
            bb_min = [float("inf")] * 3
            bb_max = [float("-inf")] * 3
            total_faces = 0
            total_edges = 0
            for body in bodies:
                box = body.GetBodyBox()
                if box:
                    for i in range(3):
                        bb_min[i] = min(bb_min[i], box[i] * 1000.0)
                        bb_max[i] = max(bb_max[i], box[i + 3] * 1000.0)
                faces = body.GetFaces()
                total_faces += len(faces) if faces else 0
                edges = body.GetEdges()
                total_edges += len(edges) if edges else 0
            summary["body"] = {
                "boundingBox": {
                    "min": {"x": round(bb_min[0], 2), "y": round(bb_min[1], 2), "z": round(bb_min[2], 2)},
                    "max": {"x": round(bb_max[0], 2), "y": round(bb_max[1], 2), "z": round(bb_max[2], 2)},
                },
                "size": {
                    "x": round(bb_max[0] - bb_min[0], 2),
                    "y": round(bb_max[1] - bb_min[1], 2),
                    "z": round(bb_max[2] - bb_min[2], 2),
                },
                "faces": total_faces,
                "edges": total_edges,
            }
        except Exception as e:
            logger.debug(f"get_state: body overview enrichment failed: {e}")

    def _enrich_sketch_status(self, summary, doc):
        """Add constraint status per tracked sketch."""
        for sketch_data in summary.get("sketches", []):
            try:
                feat = doc.FeatureByName(sketch_data["name"])
                if not feat:
                    continue
                sk = _prop(feat, "GetSpecificFeature2")
                status = int(_prop(sk, "GetConstrainedStatus"))
                sketch_data["constrainedStatus"] = CONSTRAINED_STATUS.get(
                    status, f"UNKNOWN({status})"
                )
            except Exception as e:
                logger.debug(f"get_state: sketch status failed for {sketch_data.get('name')}: {e}")

    def _enrich_feature_tree(self, summary, doc):
        """Add parent/child feature names per tracked feature (detail=full)."""
        for feat_data in summary.get("features", []):
            try:
                feat = doc.FeatureByName(feat_data["name"])
                if not feat:
                    continue
                parents = _prop(feat, "GetParents")
                if parents:
                    feat_data["parents"] = [p.Name for p in parents]
                children = _prop(feat, "GetChildren")
                if children:
                    feat_data["children"] = [c.Name for c in children]
            except Exception as e:
                logger.debug(f"get_state: feature tree failed for {feat_data.get('name')}: {e}")

    # --- Tool implementations ---

    def _get_state(self, args: dict) -> str:
        detail = args.get("detail", "summary")
        summary = self.tracker.format_state_summary()

        doc = self._get_live_doc()
        if doc:
            self._enrich_document_info(summary, doc)
            self._enrich_body_overview(summary, doc)
            self._enrich_sketch_status(summary, doc)
            if detail == "full":
                self._enrich_feature_tree(summary, doc)

        return json.dumps({"result": "✓ Session state", **summary})

    def _get_entity(self, args: dict) -> str:
        id_str = args["id"]
        record = self.tracker.resolve_id(id_str)
        if not record:
            return _json_result(f"No object found with ID: {id_str}")

        if isinstance(record, FeatureRecord):
            data = {
                "id": record.feature_id,
                "name": record.sw_name,
                "type": record.feature_type,
            }
            if record.source_sketch:
                data["sourceSketch"] = record.source_sketch
            if record.parameters:
                data["parameters"] = record.parameters
            return json.dumps({"result": f"✓ Feature: {record.sw_name}", **data})

        elif isinstance(record, SketchRecord):
            data = {
                "id": record.sketch_id,
                "name": record.sw_name,
                "plane": record.plane,
                "entityCount": len(record.entities),
                "entities": [
                    {"id": e.entity_id, "type": e.entity_type}
                    for e in record.entities
                ],
            }
            return json.dumps({"result": f"✓ Sketch: {record.sw_name}", **data})

        elif isinstance(record, SketchEntityRecord):
            data = {
                "id": record.entity_id,
                "sketchName": record.sketch_name,
                "type": record.entity_type,
                "coordinates": record.coordinates,
                "shapeInfo": record.shape_info,
            }
            return json.dumps({"result": f"✓ Entity: {record.entity_id}", **data})

        elif isinstance(record, RefGeometryRecord):
            data = {
                "id": record.ref_id,
                "name": record.sw_name,
                "type": record.ref_type,
            }
            if record.parameters:
                data["parameters"] = record.parameters
            return json.dumps({"result": f"✓ Ref geometry: {record.sw_name}", **data})

        # Component / mate records (assembly) — serialize generically
        data = {k: v for k, v in vars(record).items()}
        return json.dumps({"result": f"✓ {id_str}", **data})

    def _get_sketch_entities(self, args: dict) -> str:
        sketch_id = args["sketchId"]
        entities = self.tracker.get_sketch_entities(sketch_id)
        if entities:
            entity_list = []
            for e in entities:
                entity_list.append({
                    "id": e.entity_id,
                    "type": e.entity_type,
                    "coordinates": e.coordinates,
                })

            return json.dumps({
                "result": f"✓ {len(entities)} entities in {sketch_id}",
                "source": "tracker",
                "sketchId": sketch_id,
                "entities": entity_list,
                "unsupportedCount": sum(e.entity_type == "unsupported" for e in entities),
            })

        sketch_name = sketch_id.partition(":")[2] if ":" in sketch_id else sketch_id
        if not self.connection:
            return _json_result(
                f"No active SolidWorks document for sketch: {sketch_name}",
                source="live_com", sketchId=sketch_id,
                error={"code": "NO_CONNECTION"},
            )
        try:
            if not self.connection.is_alive():
                return _json_result(
                    f"No active SolidWorks document for sketch: {sketch_name}",
                    source="live_com", sketchId=sketch_id,
                    error={"code": "NO_ACTIVE_DOCUMENT"},
                )
            doc = self.connection.get_active_doc()
            if not doc:
                return _json_result(
                    f"No active SolidWorks document for sketch: {sketch_name}",
                    source="live_com", sketchId=sketch_id,
                    error={"code": "NO_ACTIVE_DOCUMENT"},
                )
            feature = doc.FeatureByName(sketch_name)
            if not feature:
                return _json_result(
                    f"Sketch not found: {sketch_name}", source="live_com",
                    documentPath=self._document_path(doc), sketchId=sketch_id,
                    error={"code": "SKETCH_NOT_FOUND"},
                )
            sketch = _prop(feature, "GetSpecificFeature2")
            segments = _prop(sketch, "GetSketchSegments") or []
            live_entities = []
            unsupported_count = 0
            for index, segment in enumerate(list(segments)):
                item = self._serialize_live_segment(segment, sketch_name, index)
                if item["type"] == "unsupported":
                    unsupported_count += 1
                live_entities.append(item)
            if not live_entities:
                return _json_result(
                    f"Sketch contains no readable entities: {sketch_name}",
                    source="live_com", documentPath=self._document_path(doc),
                    sketchId=f"sketch:{sketch_name}", entities=[], unsupportedCount=0,
                    error={"code": "NO_SKETCH_ENTITIES"},
                )
            return json.dumps({
                "result": f"✓ {len(live_entities)} live entities in {sketch_name}",
                "source": "live_com",
                "documentPath": self._document_path(doc),
                "sketchId": f"sketch:{sketch_name}",
                "entities": live_entities,
                "unsupportedCount": unsupported_count,
            })
        except Exception as error:
            logger.debug("live sketch entity query failed: %s", error)
            return _json_result(
                f"Unable to read live sketch entities: {sketch_name}",
                source="live_com", sketchId=f"sketch:{sketch_name}",
                error={"code": "LIVE_COM_READ_FAILED", "message": str(error)},
            )

    @staticmethod
    def _document_path(doc):
        try:
            return str(_prop(doc, "GetPathName") or _prop(doc, "GetTitle"))
        except Exception:
            return None

    @staticmethod
    def _point_mm(point):
        return {
            "x": float(_prop(point, "X")) * 1000.0,
            "y": float(_prop(point, "Y")) * 1000.0,
        }

    def _serialize_live_segment(self, segment, sketch_name, index):
        entity_id = f"entity:{sketch_name}/{index}"
        try:
            kind = int(_prop(segment, "GetType"))
            if kind == 0:
                return {
                    "id": entity_id, "type": "line",
                    "coordinates": {
                        "p1": self._point_mm(_prop(segment, "GetStartPoint2")),
                        "p2": self._point_mm(_prop(segment, "GetEndPoint2")),
                    },
                }
            if kind == 1:
                center = self._point_mm(_prop(segment, "GetCenterPoint2"))
                radius = float(_prop(segment, "GetRadius")) * 1000.0
                if bool(_prop(segment, "IsCircle")):
                    return {
                        "id": entity_id, "type": "circle",
                        "coordinates": {"center": center, "radius": radius},
                    }
                return {
                    "id": entity_id, "type": "arc",
                    "coordinates": {
                        "center": center, "radius": radius,
                        "p1": self._point_mm(_prop(segment, "GetStartPoint2")),
                        "p2": self._point_mm(_prop(segment, "GetEndPoint2")),
                        "length": float(_prop(segment, "GetLength")) * 1000.0,
                    },
                }
            return {
                "id": entity_id, "type": "unsupported",
                "coordinates": {"swType": kind},
            }
        except Exception as error:
            return {
                "id": entity_id, "type": "unsupported",
                "coordinates": {"error": str(error)},
            }
