"""
SolidWorks MCP State Tracker
Centralized registry for features, sketches, sketch entities, reference geometry,
assembly components, and mates. Provides stable IDs for referencing objects
across tool calls.

State is scoped per document: each open part/assembly gets its own DocumentScope
so that building multiple parts and an assembly in one session doesn't clobber
state. The tracker keeps the existing single-document public API (register_*,
resolve_name, last_shape, ...) by delegating to the currently active scope, so
tool modules don't need to know about scoping.

ID format:
  feat:<sw_feature_name>       e.g. feat:Boss-Extrude1
  sketch:<sw_sketch_name>      e.g. sketch:Sketch1
  entity:<sketch>/<type>_<idx> e.g. entity:Sketch1/rect_0
  ref:<sw_feature_name>        e.g. ref:Plane1
  comp:<sw_component_name>     e.g. comp:bracket-1
  mate:<sw_mate_name>          e.g. mate:Coincident1
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Document titles sometimes include the file extension depending on Windows
# Explorer settings — normalize scope keys by stripping known extensions.
_DOC_EXTENSIONS = (".sldprt", ".sldasm", ".slddrw")


def normalize_doc_key(title: str) -> str:
    """Normalize a document title/path into a stable scope key."""
    if not title:
        return "__default__"
    key = title.strip()
    lower = key.lower()
    for ext in _DOC_EXTENSIONS:
        if lower.endswith(ext):
            key = key[: -len(ext)]
            break
    return key


@dataclass
class SketchEntityRecord:
    """A tracked sketch entity (line, circle, arc, rectangle, etc.)"""
    entity_id: str
    sketch_name: str
    entity_type: str
    index: int
    coordinates: Dict
    shape_info: Dict


@dataclass
class SketchRecord:
    """A tracked sketch"""
    sketch_id: str
    sw_name: str
    plane: str
    entities: List[SketchEntityRecord] = field(default_factory=list)
    entity_counter: Dict[str, int] = field(default_factory=dict)


@dataclass
class FeatureRecord:
    """A tracked feature (extrusion, fillet, revolve, etc.)"""
    feature_id: str
    sw_name: str
    feature_type: str
    source_sketch: Optional[str] = None
    parameters: Dict = field(default_factory=dict)


@dataclass
class RefGeometryRecord:
    """A tracked reference geometry element"""
    ref_id: str
    sw_name: str
    ref_type: str
    parameters: Dict = field(default_factory=dict)


@dataclass
class ComponentRecord:
    """A tracked assembly component"""
    component_id: str            # comp:bracket-1
    sw_name: str                 # bracket-1
    file_path: str               # C:\...\bracket.SLDPRT
    position: Dict = field(default_factory=dict)   # {x, y, z} in mm (component origin)
    fixed: bool = False
    suppressed: bool = False


@dataclass
class MateRecord:
    """A tracked assembly mate"""
    mate_id: str                 # mate:Coincident1
    sw_name: str
    mate_type: str               # coincident, concentric, distance, ...
    entities: List[str] = field(default_factory=list)  # descriptions/IDs of mated entities
    value: Optional[float] = None  # distance (mm) / angle (deg) if applicable


@dataclass
class DocumentScope:
    """All tracked state for a single document."""
    doc_key: str
    doc_type: str = "part"  # "part" | "assembly" | "unknown"
    features: Dict[str, FeatureRecord] = field(default_factory=dict)
    sketches: Dict[str, SketchRecord] = field(default_factory=dict)
    entities: Dict[str, SketchEntityRecord] = field(default_factory=dict)
    ref_geometry: Dict[str, RefGeometryRecord] = field(default_factory=dict)
    components: Dict[str, ComponentRecord] = field(default_factory=dict)
    mates: Dict[str, MateRecord] = field(default_factory=dict)
    active_sketch: Optional[str] = None
    last_shape: Optional[Dict] = None
    created_shapes: List[Dict] = field(default_factory=list)


class StateTracker:
    """Centralized, document-scoped state tracker for the MCP session."""

    def __init__(self):
        self.scopes: Dict[str, DocumentScope] = {}
        self._active_key: Optional[str] = None

    # --- Scope management ---

    def _scope(self) -> DocumentScope:
        """Return the active scope, creating a default one if none exists."""
        if self._active_key is None or self._active_key not in self.scopes:
            self._active_key = self._active_key or "__default__"
            if self._active_key not in self.scopes:
                self.scopes[self._active_key] = DocumentScope(doc_key=self._active_key)
        return self.scopes[self._active_key]

    @property
    def active_doc_key(self) -> Optional[str]:
        return self._active_key

    @property
    def active_doc_type(self) -> str:
        return self._scope().doc_type

    def new_document(self, title: str, doc_type: str = "part") -> str:
        """Create a fresh scope for a newly created document and make it active.
        Replaces the old blanket reset(): other documents' state is preserved."""
        key = normalize_doc_key(title)
        self.scopes[key] = DocumentScope(doc_key=key, doc_type=doc_type)
        self._active_key = key
        logger.info(f"New document scope: {key} ({doc_type})")
        return key

    def activate_document(self, title: str, doc_type: str = "unknown") -> str:
        """Switch the active scope to the given document, creating a scope if
        the document wasn't created through the tracker (e.g. opened from disk)."""
        key = normalize_doc_key(title)
        if key not in self.scopes:
            self.scopes[key] = DocumentScope(doc_key=key, doc_type=doc_type)
            logger.info(f"Created scope for externally opened document: {key}")
        elif doc_type != "unknown":
            self.scopes[key].doc_type = doc_type
        self._active_key = key
        logger.info(f"Activated document scope: {key}")
        return key

    def rename_document(self, old_title: str, new_title: str):
        """Re-key a scope after a document is saved under a new name."""
        old_key = normalize_doc_key(old_title)
        new_key = normalize_doc_key(new_title)
        if old_key == new_key:
            return
        scope = self.scopes.pop(old_key, None)
        if scope is None:
            return
        scope.doc_key = new_key
        self.scopes[new_key] = scope
        if self._active_key == old_key:
            self._active_key = new_key
        logger.info(f"Renamed document scope: {old_key} -> {new_key}")

    def remove_document(self, title: str):
        """Drop a scope when its document is closed."""
        key = normalize_doc_key(title)
        if key in self.scopes:
            del self.scopes[key]
            logger.info(f"Removed document scope: {key}")
        if self._active_key == key:
            self._active_key = None

    def reset(self):
        """Reset ALL state (all documents)."""
        self.scopes.clear()
        self._active_key = None

    # --- Active-scope delegation (back-compat public API) ---

    @property
    def features(self) -> Dict[str, FeatureRecord]:
        return self._scope().features

    @property
    def sketches(self) -> Dict[str, SketchRecord]:
        return self._scope().sketches

    @property
    def entities(self) -> Dict[str, SketchEntityRecord]:
        return self._scope().entities

    @property
    def ref_geometry(self) -> Dict[str, RefGeometryRecord]:
        return self._scope().ref_geometry

    @property
    def components(self) -> Dict[str, ComponentRecord]:
        return self._scope().components

    @property
    def mates(self) -> Dict[str, MateRecord]:
        return self._scope().mates

    @property
    def last_shape(self) -> Optional[Dict]:
        return self._scope().last_shape

    @last_shape.setter
    def last_shape(self, value):
        self._scope().last_shape = value

    @property
    def created_shapes(self) -> List[Dict]:
        return self._scope().created_shapes

    @created_shapes.setter
    def created_shapes(self, value):
        self._scope().created_shapes = value

    # --- Sketch tracking ---

    def register_sketch(self, sw_name: str, plane: str) -> str:
        scope = self._scope()
        sketch_id = f"sketch:{sw_name}"
        record = SketchRecord(sketch_id=sketch_id, sw_name=sw_name, plane=plane)
        scope.sketches[sketch_id] = record
        scope.active_sketch = sketch_id
        scope.created_shapes = []
        scope.last_shape = None
        logger.info(f"Registered sketch: {sketch_id} on {plane}")
        return sketch_id

    def close_sketch(self, actual_sw_name: str) -> str:
        scope = self._scope()
        if scope.active_sketch:
            record = scope.sketches.get(scope.active_sketch)
            if record and record.sw_name != actual_sw_name:
                old_id = scope.active_sketch
                del scope.sketches[old_id]
                old_sw_name = record.sw_name
                record.sw_name = actual_sw_name
                record.sketch_id = f"sketch:{actual_sw_name}"
                scope.sketches[record.sketch_id] = record
                self._rebase_entity_ids(old_sw_name, actual_sw_name, record)
            sketch_id = record.sketch_id if record else f"sketch:{actual_sw_name}"
            scope.active_sketch = None
            return sketch_id
        return f"sketch:{actual_sw_name}"

    def _rebase_entity_ids(self, old_sw_name: str, new_sw_name: str, sketch_record: SketchRecord):
        scope = self._scope()
        prefix = f"entity:{old_sw_name}/"
        to_update = [eid for eid in scope.entities if eid.startswith(prefix)]
        for old_eid in to_update:
            record = scope.entities.pop(old_eid)
            suffix = old_eid.split("/", 1)[1]
            new_eid = f"entity:{new_sw_name}/{suffix}"
            record.entity_id = new_eid
            record.sketch_name = new_sw_name
            scope.entities[new_eid] = record
        # Update entity list in sketch record
        for entity in sketch_record.entities:
            if entity.sketch_name == old_sw_name:
                suffix = entity.entity_id.split("/", 1)[1]
                entity.entity_id = f"entity:{new_sw_name}/{suffix}"
                entity.sketch_name = new_sw_name

    @property
    def active_sketch_id(self) -> Optional[str]:
        return self._scope().active_sketch

    @property
    def active_sketch_name(self) -> Optional[str]:
        scope = self._scope()
        if scope.active_sketch:
            record = scope.sketches.get(scope.active_sketch)
            return record.sw_name if record else None
        return None

    # --- Sketch entity tracking ---

    def register_entity(self, entity_type: str, coordinates: Dict,
                        shape_info: Dict, update_spatial: bool = True) -> str:
        scope = self._scope()
        if not scope.active_sketch:
            logger.warning("No active sketch for entity registration")
            return ""

        sketch_record = scope.sketches[scope.active_sketch]
        sw_name = sketch_record.sw_name

        idx = sketch_record.entity_counter.get(entity_type, 0)
        sketch_record.entity_counter[entity_type] = idx + 1

        entity_id = f"entity:{sw_name}/{entity_type}_{idx}"
        record = SketchEntityRecord(
            entity_id=entity_id,
            sketch_name=sw_name,
            entity_type=entity_type,
            index=idx,
            coordinates=coordinates,
            shape_info=shape_info,
        )
        scope.entities[entity_id] = record
        sketch_record.entities.append(record)

        if update_spatial:
            scope.created_shapes.append(shape_info)
            scope.last_shape = shape_info

        logger.info(f"Registered entity: {entity_id}")
        return entity_id

    # --- Feature tracking ---

    def register_feature(self, sw_name: str, feature_type: str,
                         source_sketch: Optional[str] = None,
                         parameters: Optional[Dict] = None) -> str:
        feature_id = f"feat:{sw_name}"
        record = FeatureRecord(
            feature_id=feature_id,
            sw_name=sw_name,
            feature_type=feature_type,
            source_sketch=source_sketch,
            parameters=parameters or {},
        )
        self._scope().features[feature_id] = record
        logger.info(f"Registered feature: {feature_id} ({feature_type})")
        return feature_id

    def remove_feature(self, sw_name: str) -> List[str]:
        """Remove a deleted object's records from the active scope.

        Handles feature, sketch, and ref-geometry records by SolidWorks name.
        When a feature is removed and no other tracked feature references its
        source sketch, the sketch record (and its entity records) is removed
        too — SolidWorks deletes absorbed/dependent sketches along with the
        feature (DeleteSelection2 with swDelete_Children).

        Returns the list of removed IDs (empty if nothing was tracked).
        """
        scope = self._scope()
        removed: List[str] = []

        def _remove_sketch(sketch_id: str):
            record = scope.sketches.pop(sketch_id, None)
            if record is None:
                return
            removed.append(sketch_id)
            prefix = f"entity:{record.sw_name}/"
            for eid in [e for e in scope.entities if e.startswith(prefix)]:
                del scope.entities[eid]
                removed.append(eid)
            if scope.active_sketch == sketch_id:
                scope.active_sketch = None

        feat_id = f"feat:{sw_name}"
        feat = scope.features.pop(feat_id, None)
        if feat is not None:
            removed.append(feat_id)
            src = feat.source_sketch
            if src and not any(f.source_sketch == src
                               for f in scope.features.values()):
                _remove_sketch(src)

        # The deleted object may itself be a tracked sketch or ref geometry
        _remove_sketch(f"sketch:{sw_name}")
        ref_id = f"ref:{sw_name}"
        if scope.ref_geometry.pop(ref_id, None) is not None:
            removed.append(ref_id)

        if removed:
            logger.info(f"Removed tracked records for '{sw_name}': {removed}")
        return removed

    # --- Reference geometry tracking ---

    def register_ref_geometry(self, sw_name: str, ref_type: str,
                              parameters: Optional[Dict] = None) -> str:
        ref_id = f"ref:{sw_name}"
        record = RefGeometryRecord(
            ref_id=ref_id,
            sw_name=sw_name,
            ref_type=ref_type,
            parameters=parameters or {},
        )
        self._scope().ref_geometry[ref_id] = record
        logger.info(f"Registered ref geometry: {ref_id} ({ref_type})")
        return ref_id

    # --- Assembly tracking ---

    def register_component(self, sw_name: str, file_path: str,
                           position: Optional[Dict] = None,
                           fixed: bool = False,
                           suppressed: bool = False) -> str:
        component_id = f"comp:{sw_name}"
        record = ComponentRecord(
            component_id=component_id,
            sw_name=sw_name,
            file_path=file_path,
            position=position or {},
            fixed=fixed,
            suppressed=suppressed,
        )
        self._scope().components[component_id] = record
        logger.info(f"Registered component: {component_id}")
        return component_id

    def register_mate(self, sw_name: str, mate_type: str,
                      entities: Optional[List[str]] = None,
                      value: Optional[float] = None) -> str:
        mate_id = f"mate:{sw_name}"
        record = MateRecord(
            mate_id=mate_id,
            sw_name=sw_name,
            mate_type=mate_type,
            entities=entities or [],
            value=value,
        )
        self._scope().mates[mate_id] = record
        logger.info(f"Registered mate: {mate_id} ({mate_type})")
        return mate_id

    # --- Lookup / query ---

    def resolve_id(self, id_str: str) -> Optional[Any]:
        scope = self._scope()
        for registry in (scope.features, scope.sketches, scope.entities,
                         scope.ref_geometry, scope.components, scope.mates):
            if id_str in registry:
                return registry[id_str]
        return None

    def get_sw_name(self, id_str: str) -> Optional[str]:
        record = self.resolve_id(id_str)
        if record is None:
            return None
        return getattr(record, 'sw_name', None)

    def resolve_name(self, name_or_id: str) -> str:
        """Resolve a prefixed ID to a SolidWorks name, or return as-is with warning."""
        if name_or_id.startswith(("feat:", "sketch:", "ref:", "comp:", "mate:")):
            sw_name = self.get_sw_name(name_or_id)
            if not sw_name:
                raise Exception(f"Unknown ID: {name_or_id}")
            return sw_name
        else:
            logger.warning(
                f"Raw SolidWorks name '{name_or_id}' used — consider using tracked ID instead"
            )
            return name_or_id

    def get_id_by_sw_name(self, sw_name: str) -> Optional[str]:
        """Look up a tracked ID by SolidWorks feature name."""
        scope = self._scope()
        for registry in (scope.features, scope.sketches, scope.ref_geometry,
                         scope.components, scope.mates):
            for rid, rec in registry.items():
                if rec.sw_name == sw_name:
                    return rid
        return None

    def get_entity_coordinates(self, entity_id: str) -> Optional[Dict]:
        record = self._scope().entities.get(entity_id)
        return record.coordinates if record else None

    def get_sketch_entities(self, sketch_id: str) -> List[SketchEntityRecord]:
        scope = self._scope()
        record = scope.sketches.get(sketch_id)
        if not record:
            record = scope.sketches.get(f"sketch:{sketch_id}")
        return record.entities if record else []

    def format_state_summary(self) -> Dict:
        """Format a structured state summary for the active document."""
        scope = self._scope()
        summary = {"sketches": [], "features": [], "refGeometry": []}

        if self._active_key and self._active_key != "__default__":
            summary["activeDocument"] = {
                "name": scope.doc_key,
                "type": scope.doc_type,
            }
        open_docs = [k for k in self.scopes if k != "__default__"]
        if len(open_docs) > 1:
            summary["openDocuments"] = open_docs

        for sid, s in scope.sketches.items():
            sketch_data = {
                "id": sid,
                "name": s.sw_name,
                "plane": s.plane,
                "entityCount": len(s.entities),
                "entities": [
                    {"id": e.entity_id, "type": e.entity_type}
                    for e in s.entities
                ],
            }
            summary["sketches"].append(sketch_data)

        for fid, f in scope.features.items():
            feat_data = {
                "id": fid,
                "name": f.sw_name,
                "type": f.feature_type,
            }
            if f.source_sketch:
                feat_data["sourceSketch"] = f.source_sketch
            if f.parameters:
                feat_data["parameters"] = f.parameters
            summary["features"].append(feat_data)

        for rid, r in scope.ref_geometry.items():
            ref_data = {
                "id": rid,
                "name": r.sw_name,
                "type": r.ref_type,
            }
            if r.parameters:
                ref_data["parameters"] = r.parameters
            summary["refGeometry"].append(ref_data)

        if scope.components or scope.mates or scope.doc_type == "assembly":
            summary["components"] = [
                {
                    "id": cid,
                    "name": c.sw_name,
                    "filePath": c.file_path,
                    "position": c.position,
                    "fixed": c.fixed,
                    "suppressed": c.suppressed,
                }
                for cid, c in scope.components.items()
            ]
            summary["mates"] = [
                {
                    "id": mid,
                    "name": m.sw_name,
                    "type": m.mate_type,
                    "entities": m.entities,
                    **({"value": m.value} if m.value is not None else {}),
                }
                for mid, m in scope.mates.items()
            ]

        return summary
