"""
SolidWorks Geometry Query Tools
Enumerate faces, edges, vertices, and body properties for model inspection.

COM binding notes (pywin32 late binding with SolidWorks 2025):
  - Most IEdge/IFace2/ISurface getters are accessed as PROPERTIES (no parens):
    edge.GetStartVertex, vertex.GetPoint, face.GetArea, face.Normal,
    face.GetUVBounds, face.GetSurface, face.GetEdges, face.GetEdgeCount,
    surface.Identity, surface.PlaneParams, edge.GetCurveParams2, edge.GetCurve
  - Methods that take arguments use parens:
    body.GetBodyBox(), body.GetFaces(), body.GetEdges(),
    edge.GetClosestPointOn(x,y,z), curve.GetLength2(t1,t2),
    surface.Evaluate(u,v,0,0), curve.Evaluate2(t,0)
"""

import json
import logging
from mcp.types import Tool
from . import selection_helpers as sel
from .com_utils import com_prop

logger = logging.getLogger(__name__)

# Surface type constants from ISurface::Identity
SURFACE_TYPES = {
    4001: "Planar",
    4002: "Cylindrical",
    4003: "Conical",
    4004: "Spherical",
    4005: "Toroidal",
    4006: "BSpline",
    4007: "Blend",
    4008: "Offset",
    4009: "Extrusion",
}

SURFACE_TYPE_FILTER = {
    "PLANE": 4001,
    "CYLINDER": 4002,
    "CONE": 4003,
    "SPHERE": 4004,
    "TORUS": 4005,
    "BSPLINE": 4006,
}


class GeometryQueryTools:
    """Geometry inspection tools for querying faces, edges, vertices, and body info."""

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
                name="solidworks_get_body_info",
                description="Get a high-level overview of the active part body: bounding box dimensions, face count, edge count, and vertex count. Use this as a quick check of model state before querying individual faces or edges.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
            Tool(
                name="solidworks_get_faces",
                description="Enumerate all faces on the active part body. Returns each face's surface type, area, normal/axis info, a sample point (usable for selection in fillet/chamfer/shell/draft), edge count, and the feature that created it (e.g. 'feature': 'Boss-Extrude1'). Use the optional surfaceType filter to narrow results.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "surfaceType": {
                            "type": "string",
                            "enum": ["PLANE", "CYLINDER", "CONE", "SPHERE", "TORUS", "BSPLINE"],
                            "description": "Optional: filter faces by surface type. If omitted, returns all faces."
                        }
                    }
                }
            ),
            Tool(
                name="solidworks_get_edges",
                description="Enumerate all edges on the active part body. Returns each edge's type (Line/Circle/Arc), start and end vertex coordinates, a midpoint (usable for selection in fillet/chamfer/pattern direction), length, whether the edge is smooth (tangent), and the feature(s) whose faces meet at the edge ('features' list — e.g. select all edges bordering 'Boss-Extrude1'). Smooth edges (e.g., fillet boundaries) cannot be filleted or chamfered — skip them when selecting edges for those operations. Use the optional edgeType filter to narrow results.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "edgeType": {
                            "type": "string",
                            "enum": ["LINE", "CIRCLE", "ARC"],
                            "description": "Optional: filter edges by curve type. If omitted, returns all edges."
                        },
                        "feature": {
                            "type": "string",
                            "description": "Optional: only edges bordering this feature (id or name, e.g. 'feat:Boss-Extrude2'). Combines with edgeType."
                        }
                    }
                }
            ),
            Tool(
                name="solidworks_get_face_edges",
                description="Get detailed information about a specific face and its bounding edges. Select the face by providing a 3D point on or near it. Returns face properties and each edge's endpoints, midpoint, and smooth flag. Smooth edges (e.g., fillet boundaries) cannot be filleted or chamfered. Use this to drill down into a face found via get_faces.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "number", "description": "X coordinate on/near the face (mm)"},
                        "y": {"type": "number", "description": "Y coordinate on/near the face (mm)"},
                        "z": {"type": "number", "description": "Z coordinate on/near the face (mm)"}
                    },
                    "required": ["x", "y", "z"]
                }
            ),
            Tool(
                name="solidworks_get_vertices",
                description="List all unique vertex (corner) positions on the active part body. Returns 3D coordinates in mm, sorted by (x, y, z). Useful for understanding model geometry and as reference points.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
            Tool(
                name="solidworks_find_face",
                description=(
                    "Select a face by DESCRIPTION instead of coordinates: filter by "
                    "orientation (+X/-X/+Y/-Y/+Z/-Z, ANGLED = planar but not "
                    "axis-aligned, ANY), by the feature that created it, by surface "
                    "type, and/or by area rank. Returns matching face(s) with a "
                    "samplePoint ready to use in create_sketch (faceX/faceY/faceZ) "
                    "or selection-based tools. PREFER THIS over guessing coordinates "
                    "— e.g. a drawing note like 'sketch on the angled face' is "
                    "exactly find_face(orientation='ANGLED')."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "orientation": {"type": "string",
                                        "enum": ["+X", "-X", "+Y", "-Y", "+Z", "-Z",
                                                 "ANGLED", "ANY"],
                                        "description": "Planar face normal direction filter"},
                        "feature": {"type": "string",
                                    "description": "Only faces created by this feature (id or name)"},
                        "surfaceType": {"type": "string",
                                        "enum": ["PLANE", "CYLINDER", "CONE", "SPHERE", "TORUS"],
                                        "description": "Surface type filter"},
                        "areaRank": {"type": "string", "enum": ["LARGEST", "SMALLEST"],
                                     "description": "Keep only the largest/smallest match"}
                    }
                }
            ),
            Tool(
                name="solidworks_look_at_model",
                description=(
                    "SEE the model you are building: returns a screenshot of the "
                    "current part in a standard view, with face labels (F0, F1...) "
                    "overlaid at each face — label indices match get_faces/find_face. "
                    "Use it to verify features landed where intended, to pick the "
                    "right face visually, or whenever you are unsure what the model "
                    "actually looks like. view='sketch' captures the ACTIVE sketch "
                    "normal-to (flat 2D) — review your profile against the drawing "
                    "BEFORE extruding it."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "view": {"type": "string",
                                 "enum": ["isometric", "front", "back", "left",
                                          "right", "top", "bottom", "sketch"],
                                 "description": "Standard view (default isometric); 'sketch' = normal-to of the active sketch"},
                        "labels": {"type": "boolean",
                                   "description": "Overlay face labels (default true)"}
                    }
                }
            ),
        ]

    def execute(self, tool_name: str, args: dict) -> str:
        self.connection.ensure_connection()
        dispatch = {
            "solidworks_get_body_info": lambda: self.get_body_info(),
            "solidworks_get_faces": lambda: self.get_faces(args),
            "solidworks_get_edges": lambda: self.get_edges(args),
            "solidworks_get_face_edges": lambda: self.get_face_edges(args),
            "solidworks_get_vertices": lambda: self.get_vertices(),
            "solidworks_find_face": lambda: self.find_face(args),
            "solidworks_look_at_model": lambda: self.look_at_model(args),
        }
        handler = dispatch.get(tool_name)
        if not handler:
            raise Exception(f"Unknown geometry query tool: {tool_name}")
        return handler()

    # --- Semantic face selection + visual feedback ---

    def _face_normal(self, face):
        """OUTWARD unit normal for planar faces, else None.

        PlaneParams reports the SURFACE normal; the face may be reversed
        relative to its surface (FaceInSurfaceSense) — without the flip a
        box reports inward normals on half its faces and orientation
        filtering silently returns nothing.
        """
        try:
            surface = face.GetSurface
            if surface.Identity == 4001:
                p = surface.PlaneParams
                nx, ny, nz = p[0], p[1], p[2]
                try:
                    if com_prop(face, "FaceInSurfaceSense"):  # bool
                        nx, ny, nz = -nx, -ny, -nz
                except Exception:
                    pass
                return (nx, ny, nz)
        except Exception:
            pass
        return None

    _AXES = {"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0),
             "-Y": (0, -1, 0), "+Z": (0, 0, 1), "-Z": (0, 0, -1)}

    def find_face(self, args: dict) -> str:
        """Select a face by DESCRIPTION instead of coordinates: orientation,
        creating feature, surface type, area rank. Returns matching face(s)
        with a samplePoint ready to pass to create_sketch/select tools."""
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")
        bodies = self._get_bodies(doc)
        all_faces = []
        for body in bodies:
            faces = body.GetFaces()
            if faces:
                all_faces.extend(faces)

        orientation = (args.get("orientation") or "ANY").upper()
        want_feature = args.get("feature")
        want_type = args.get("surfaceType")
        type_id = SURFACE_TYPE_FILTER.get(want_type) if want_type else None
        if want_feature and want_feature.startswith("feat:"):
            want_feature = want_feature[5:]

        matches = []
        for idx, face in enumerate(all_faces):
            if type_id is not None and self._surface_identity(face) != type_id:
                continue
            feat_name = self._face_feature_name(face)
            if want_feature and (feat_name or "").lower() != want_feature.lower():
                continue
            normal = self._face_normal(face)
            if orientation != "ANY":
                if orientation == "ANGLED":
                    # planar but not axis-aligned
                    if normal is None:
                        continue
                    if max(abs(c) for c in normal) > 0.999:
                        continue
                else:
                    axis = self._AXES.get(orientation)
                    if axis is None:
                        raise Exception(f"orientation must be one of "
                                        f"{list(self._AXES) + ['ANGLED', 'ANY']}")
                    if normal is None:
                        continue
                    if (normal[0] * axis[0] + normal[1] * axis[1]
                            + normal[2] * axis[2]) < 0.999:
                        continue
            try:
                area = face.GetArea * 1e6
            except Exception:
                area = 0.0
            sample = self._face_sample_point(face)
            entry = {
                "index": idx,
                "surfaceType": self._surface_type_str(face),
                "area": round(area, 2),
                "point": {"x": round(sample[0], 2), "y": round(sample[1], 2),
                          "z": round(sample[2], 2)},
            }
            if normal:
                entry["normal"] = [round(c, 3) for c in normal]
            entry.update(self._feature_fields(feat_name))
            matches.append(entry)

        matches.sort(key=lambda m: -m["area"])
        rank = (args.get("areaRank") or "").upper()
        if rank == "LARGEST" and matches:
            matches = [matches[0]]
        elif rank == "SMALLEST" and matches:
            matches = [matches[-1]]

        if not matches:
            return self._json_result(
                "✓ No face matches those criteria — loosen a filter or use "
                "get_faces to see everything.", type="faces", faces=[])
        note = ("exactly one match — use its point for create_sketch/selection"
                if len(matches) == 1 else
                f"{len(matches)} matches (sorted by area desc) — refine with "
                f"areaRank or feature, or pick by the labeled view from "
                f"look_at_model")
        return self._json_result(f"✓ {len(matches)} matching face(s); {note}",
                                 type="faces", faces=matches)

    # Screen-space axes (right, up) per standard view, model coordinates.
    _VIEW_AXES = {
        "front": ((1, 0, 0), (0, 1, 0)),
        "back": ((-1, 0, 0), (0, 1, 0)),
        "left": ((0, 0, -1), (0, 1, 0)),
        "right": ((0, 0, 1), (0, 1, 0)),
        "top": ((1, 0, 0), (0, 0, -1)),
        "bottom": ((1, 0, 0), (0, 0, 1)),
        "isometric": ((0.7071, 0, -0.7071), (-0.4082, 0.8165, -0.4082)),
    }
    _VIEW_IDS = {"front": 1, "back": 2, "left": 3, "right": 4,
                 "top": 5, "bottom": 6, "isometric": 7}

    def look_at_model(self, args: dict) -> str:
        """Screenshot the current model (standard view) with face labels
        overlaid — the agent's eyes during the build. Returns IMAGE_FILE:
        convention so the server attaches the PNG as image content."""
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")
        view = (args.get("view") or "isometric").lower()
        if view != "sketch" and view not in self._VIEW_IDS:
            raise Exception(f"view must be one of {list(self._VIEW_IDS) + ['sketch']}")

        from pathlib import Path
        out_dir = Path(__file__).parent.parent / "workspace" / "agent_views"
        out_dir.mkdir(parents=True, exist_ok=True)
        png = out_dir / f"view_{view}.png"

        if view == "sketch":
            # Normal-to view of the ACTIVE sketch: a flat, distortion-free 2D
            # check against the drawing BEFORE any feature is made. Cheapest
            # possible catch point for profile errors.
            if doc.SketchManager.ActiveSketch is None:
                raise Exception("view='sketch' requires an active sketch — "
                                "call it between drawing and exit_sketch")
            doc.ShowNamedView2("*Normal To", -1)
        else:
            doc.ShowNamedView2("", self._VIEW_IDS[view])
        doc.ViewZoomtofit2()
        if png.exists():
            png.unlink()
        # SaveAs3's return value is unreliable across versions — trust the file
        doc.SaveAs3(str(png), 0, 2)
        if not png.exists():
            raise Exception(f"screenshot save failed for {png}")

        face_table = []
        labeled = False
        if view != "sketch" and args.get("labels", True):
            try:
                labeled, face_table = self._label_faces(doc, png, view)
            except Exception as e:
                logger.warning(f"look_at_model labeling failed: {e}")

        payload = {
            "view": view,
            "labeled": labeled,
            "faces": face_table,
            "note": ("labels F<n> match get_faces/find_face indices; labels of "
                     "hidden faces may overlay the silhouette" if labeled else
                     "unlabeled screenshot"),
        }
        return "IMAGE_FILE:" + str(png) + "\n" + self._json_result(
            f"✓ {view} view captured" + (" with face labels" if labeled else ""),
            type="view", **payload)

    def _label_faces(self, doc, png_path, view):
        """Overlay F<idx> markers at projected face sample points."""
        from PIL import Image, ImageDraw
        right, up = self._VIEW_AXES[view]
        bodies = self._get_bodies(doc)
        all_faces = []
        for body in bodies:
            faces = body.GetFaces()
            if faces:
                all_faces.extend(faces)

        pts = []
        table = []
        for idx, face in enumerate(all_faces):
            s = self._face_sample_point(face)
            pts.append(s)
            entry = {"label": f"F{idx}",
                     "point": {"x": round(s[0], 2), "y": round(s[1], 2),
                               "z": round(s[2], 2)}}
            entry.update(self._feature_fields(self._face_feature_name(face)))
            table.append(entry)
        if not pts:
            return False, []

        def proj(p):
            return (p[0] * right[0] + p[1] * right[1] + p[2] * right[2],
                    p[0] * up[0] + p[1] * up[1] + p[2] * up[2])

        prj = [proj(p) for p in pts]
        # Normalize against the projected BODY BOUNDING BOX corners (com_prop:
        # GetBodyBox binds as a method under late-bound COM).
        corners = []
        for body in bodies:
            try:
                bb = com_prop(body, "GetBodyBox")
                if bb and len(bb) >= 6:
                    lo = [v * 1000.0 for v in bb[:3]]
                    hi = [v * 1000.0 for v in bb[3:6]]
                    for cx in (lo[0], hi[0]):
                        for cy in (lo[1], hi[1]):
                            for cz in (lo[2], hi[2]):
                                corners.append(proj((cx, cy, cz)))
            except Exception:
                pass
        frame_pts = corners or prj
        xs = [p[0] for p in frame_pts]; ys = [p[1] for p in frame_pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1e-6)
        span_y = max(max_y - min_y, 1e-6)

        img = Image.open(png_path).convert("RGB")
        w, h = img.size
        # Self-calibrate: find the rendered silhouette (model pixels are darker
        # than the pale background gradient) and map the projected bbox onto
        # that pixel rect — no assumptions about SolidWorks' fit margins.
        gray = img.convert("L")
        try:
            small = gray.resize((max(1, w // 4), max(1, h // 4)))
            sw_, sh_ = small.size
            px_ = small.load()
            min_ix = min_iy = 10 ** 9
            max_ix = max_iy = -1
            for yy in range(sh_):
                for xx in range(sw_):
                    if px_[xx, yy] < 205:
                        if xx < min_ix: min_ix = xx
                        if xx > max_ix: max_ix = xx
                        if yy < min_iy: min_iy = yy
                        if yy > max_iy: max_iy = yy
            if max_ix < 0:
                raise ValueError("no silhouette")
            sil = (min_ix * 4, min_iy * 4, max_ix * 4, max_iy * 4)
        except Exception:
            sil = (0.12 * w, 0.12 * h, 0.88 * w, 0.88 * h)

        sil_w = max(sil[2] - sil[0], 1)
        sil_h = max(sil[3] - sil[1], 1)
        # Uniform scale (orthographic projection preserves aspect) centered in
        # the silhouette rect — independent x/y scaling skews label placement.
        # A future improvement: exact pixel mapping via IModelView.Scale2 +
        # Translation3 would remove the residual bias from shadow/pale-face
        # silhouette detection.
        scale = min(sil_w / span_x, sil_h / span_y)
        cx_pix = (sil[0] + sil[2]) / 2.0
        cy_pix = (sil[1] + sil[3]) / 2.0
        mid_px = (min_x + max_x) / 2.0
        mid_py = (min_y + max_y) / 2.0
        draw = ImageDraw.Draw(img)
        for (px, py), entry in zip(prj, table):
            ix = cx_pix + (px - mid_px) * scale
            iy = cy_pix - (py - mid_py) * scale
            draw.ellipse([ix - 4, iy - 4, ix + 4, iy + 4],
                         fill=(255, 60, 60), outline=(255, 255, 255))
            draw.text((ix + 6, iy - 7), entry["label"], fill=(255, 60, 60))
        img.save(png_path)
        return True, table

    # --- Helper methods ---

    def _get_bodies(self, doc):
        """Get solid bodies from the active document."""
        doc.ForceRebuild3(True)
        bodies = doc.GetBodies2(0, True)  # 0 = swSolidBody
        if not bodies:
            raise Exception("No solid bodies found in the active document")
        return bodies

    def _face_feature_name(self, face):
        """Name of the feature that created a face (IFace2.GetFeature)."""
        try:
            feat = com_prop(face, "GetFeature")
            return feat.Name if feat else None
        except Exception:
            return None

    def _feature_fields(self, feature_name):
        """Feature name + tracked ID fields to merge into a result dict."""
        if not feature_name:
            return {}
        fields = {"feature": feature_name}
        if self.tracker:
            try:
                fid = self.tracker.get_id_by_sw_name(feature_name)
                if fid:
                    fields["featureId"] = fid
            except Exception:
                pass
        return fields

    def _edge_features(self, edge):
        """Names of the features owning the edge's two adjacent faces.
        (IEdge has no GetFeature late-bound; go through the adjacent faces.)"""
        try:
            faces = com_prop(edge, "GetTwoAdjacentFaces2")  # array of 2 IFace2
            names = []
            for face in (faces or []):
                if face is None:
                    continue
                name = self._face_feature_name(face)
                if name and name not in names:
                    names.append(name)
            return names
        except Exception:
            return []

    def _face_sample_point(self, face):
        """Compute a reliable sample point on a face using UV midpoint evaluation.
        Returns (x_mm, y_mm, z_mm).
        """
        try:
            uv = face.GetUVBounds  # property: (umin, umax, vmin, vmax)
            u_mid = (uv[0] + uv[1]) / 2.0
            v_mid = (uv[2] + uv[3]) / 2.0
            surface = face.GetSurface  # property: ISurface COM object
            result = surface.Evaluate(u_mid, v_mid, 0, 0)  # method: returns (x,y,z,...)
            return (result[0] * 1000.0, result[1] * 1000.0, result[2] * 1000.0)
        except Exception:
            return self._face_centroid_from_edges(face)

    def _face_centroid_from_edges(self, face):
        """Fallback: approximate face centroid by averaging edge vertex positions."""
        edges = face.GetEdges  # property: tuple of edge COM objects
        if not edges:
            return (0.0, 0.0, 0.0)
        pts = []
        for edge in edges:
            for v in (edge.GetStartVertex, edge.GetEndVertex):  # properties
                if v:
                    p = v.GetPoint  # property: (x, y, z) in meters
                    pts.append((p[0], p[1], p[2]))
        if not pts:
            return (0.0, 0.0, 0.0)
        n = len(pts)
        return (
            sum(p[0] for p in pts) / n * 1000.0,
            sum(p[1] for p in pts) / n * 1000.0,
            sum(p[2] for p in pts) / n * 1000.0,
        )

    def _edge_midpoint(self, edge):
        """Compute a selectable midpoint on an edge. Returns (x_mm, y_mm, z_mm)."""
        start_v = edge.GetStartVertex  # property: vertex COM object or None
        end_v = edge.GetEndVertex      # property: vertex COM object or None
        if start_v and end_v:
            sp = start_v.GetPoint  # property: (x, y, z) in meters
            ep = end_v.GetPoint
            mid_x = (sp[0] + ep[0]) / 2.0
            mid_y = (sp[1] + ep[1]) / 2.0
            mid_z = (sp[2] + ep[2]) / 2.0
            # Snap to actual edge for curved edges
            try:
                closest = edge.GetClosestPointOn(mid_x, mid_y, mid_z)  # method
                return (closest[0] * 1000.0, closest[1] * 1000.0, closest[2] * 1000.0)
            except Exception:
                return (mid_x * 1000.0, mid_y * 1000.0, mid_z * 1000.0)
        else:
            # Closed edge (circle etc.) -- use parametric midpoint
            try:
                params = edge.GetCurveParams2  # property: tuple
                t_mid = (params[6] + params[7]) / 2.0
                curve = edge.GetCurve  # property: ICurve COM object
                pt = curve.Evaluate2(t_mid, 0)  # method
                return (pt[0] * 1000.0, pt[1] * 1000.0, pt[2] * 1000.0)
            except Exception:
                try:
                    params = edge.GetCurveParams2
                    return (params[0] * 1000.0, params[1] * 1000.0, params[2] * 1000.0)
                except Exception:
                    return (0.0, 0.0, 0.0)

    def _edge_endpoints(self, edge):
        """Get start and end vertex coordinates.
        Returns ((sx,sy,sz), (ex,ey,ez)) in mm, or None for closed edges.
        """
        start_v = edge.GetStartVertex
        end_v = edge.GetEndVertex
        if start_v and end_v:
            sp = start_v.GetPoint
            ep = end_v.GetPoint
            return (
                (sp[0] * 1000.0, sp[1] * 1000.0, sp[2] * 1000.0),
                (ep[0] * 1000.0, ep[1] * 1000.0, ep[2] * 1000.0),
            )
        return None

    def _edge_length(self, edge):
        """Get edge length in mm."""
        try:
            params = edge.GetCurveParams2  # property
            curve = edge.GetCurve          # property
            length_m = curve.GetLength2(params[6], params[7])  # method
            return length_m * 1000.0
        except Exception:
            return 0.0

    def _edge_type_str(self, edge):
        """Classify edge curve type."""
        start_v = edge.GetStartVertex
        end_v = edge.GetEndVertex

        # Closed edge (no start/end vertex) = circle
        if not start_v or not end_v:
            return "Circle"

        sp = start_v.GetPoint
        ep = end_v.GetPoint
        try:
            params = edge.GetCurveParams2
            curve = edge.GetCurve
            arc_len = curve.GetLength2(params[6], params[7])
            chord_len = ((ep[0] - sp[0])**2 + (ep[1] - sp[1])**2 + (ep[2] - sp[2])**2)**0.5
            if chord_len > 0 and abs(arc_len - chord_len) / chord_len < 1e-6:
                return "Line"
            else:
                return "Arc"
        except Exception:
            return "Line"

    def _is_edge_smooth(self, edge):
        """Check if an edge is smooth (tangent between its two adjacent faces).
        Smooth edges (e.g., fillet/chamfer boundaries) cannot be filleted or chamfered.
        Returns True if smooth, False if sharp or if the check fails.
        """
        try:
            faces = edge.GetTwoAdjacentFaces2  # property: array of 2 IFace2
            if not faces or len(faces) < 2:
                return False

            # Get a point on the edge in meters
            mid_mm = self._edge_midpoint(edge)
            mx, my, mz = mid_mm[0] / 1000.0, mid_mm[1] / 1000.0, mid_mm[2] / 1000.0

            normals = []
            for i in range(2):
                face = faces[i]
                surface = face.GetSurface  # property: ISurface

                # Find UV coordinates of edge point on this surface
                closest = surface.GetClosestPointOn(mx, my, mz)  # method: (x,y,z,u,v,...)
                u, v = closest[3], closest[4]

                # Evaluate surface with 1st-order derivatives
                ev = surface.Evaluate(u, v, 1, 1)  # method: (x,y,z, du_xyz, dv_xyz, ...)
                du = (ev[3], ev[4], ev[5])
                dv = (ev[6], ev[7], ev[8])

                # Surface normal = du x dv
                nx = du[1] * dv[2] - du[2] * dv[1]
                ny = du[2] * dv[0] - du[0] * dv[2]
                nz = du[0] * dv[1] - du[1] * dv[0]
                mag = (nx * nx + ny * ny + nz * nz) ** 0.5
                if mag < 1e-10:
                    return False

                # Flip normal if face sense is reversed relative to surface
                try:
                    if com_prop(face, "FaceInSurfaceSense"):  # bool
                        nx, ny, nz = -nx, -ny, -nz
                except Exception:
                    pass

                normals.append((nx / mag, ny / mag, nz / mag))

            # Dot product of outward normals from both adjacent faces
            dot = (normals[0][0] * normals[1][0] +
                   normals[0][1] * normals[1][1] +
                   normals[0][2] * normals[1][2])

            # Smooth/tangent edges have nearly parallel outward normals (dot close to 1).
            # Sharp edges have diverging normals (dot well below 1).
            return dot > 0.95
        except Exception:
            return False

    def _surface_type_str(self, face):
        """Get human-readable surface type string."""
        try:
            surface = face.GetSurface  # property
            identity = surface.Identity  # property
            return SURFACE_TYPES.get(identity, f"Unknown({identity})")
        except Exception:
            return "Unknown"

    def _surface_identity(self, face):
        """Get raw surface identity integer."""
        try:
            surface = face.GetSurface
            return surface.Identity
        except Exception:
            return -1

    def _surface_details(self, face):
        """Get type-specific surface details (normal for planes, axis+radius for cylinders)."""
        try:
            surface = face.GetSurface
            identity = surface.Identity
            if identity == 4001:  # Plane
                normal = self._face_normal(face)  # outward (sense-corrected)
                if normal:
                    return f"normal=({normal[0]:.2f}, {normal[1]:.2f}, {normal[2]:.2f})"
                return "plane"
            elif identity == 4002:  # Cylinder
                params = surface.CylinderParams  # property: (ox,oy,oz, ax,ay,az, radius)
                r_mm = params[6] * 1000.0
                ax, ay, az = params[3], params[4], params[5]
                return f"axis=({ax:.2f}, {ay:.2f}, {az:.2f}) radius={r_mm:.2f}"
            elif identity == 4003:  # Cone
                return "cone"
            elif identity == 4004:  # Sphere
                try:
                    params = surface.SphereParams
                    r_mm = params[3] * 1000.0
                    return f"radius={r_mm:.2f}"
                except Exception:
                    return "sphere"
            elif identity == 4005:  # Torus
                return "torus"
        except Exception:
            pass
        return ""

    def _count_unique_vertices(self, bodies):
        """Count unique vertices across all bodies."""
        coords = []
        for body in bodies:
            edges = body.GetEdges()  # method
            if not edges:
                continue
            for edge in edges:
                for v in (edge.GetStartVertex, edge.GetEndVertex):  # properties
                    if v:
                        p = v.GetPoint  # property
                        coords.append((p[0] * 1000.0, p[1] * 1000.0, p[2] * 1000.0))
        return len(self._deduplicate_points(coords))

    def _deduplicate_points(self, points, tolerance=1e-4):
        """Deduplicate points by coordinate proximity (tolerance in mm)."""
        unique = []
        for pt in points:
            is_dup = False
            for u in unique:
                if all(abs(a - b) < tolerance for a, b in zip(pt, u)):
                    is_dup = True
                    break
            if not is_dup:
                unique.append(pt)
        return unique

    def _format_edge_line(self, idx, edge):
        """Format a single edge as a compact one-liner."""
        etype = self._edge_type_str(edge)
        endpoints = self._edge_endpoints(edge)
        mid = self._edge_midpoint(edge)
        length = self._edge_length(edge)
        mid_str = f"({mid[0]:.2f}, {mid[1]:.2f}, {mid[2]:.2f})"

        if endpoints:
            s, e = endpoints
            start_str = f"({s[0]:.2f}, {s[1]:.2f}, {s[2]:.2f})"
            end_str = f"({e[0]:.2f}, {e[1]:.2f}, {e[2]:.2f})"
            return f"  [{idx}] {etype} | {start_str}-{end_str} | mid={mid_str} | length={length:.2f}"
        else:
            return f"  [{idx}] {etype} | closed | mid={mid_str} | length={length:.2f}"

    # --- Tool implementations ---

    def get_body_info(self) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        bodies = self._get_bodies(doc)

        total_faces = 0
        total_edges = 0
        bb_min = [float('inf')] * 3
        bb_max = [float('-inf')] * 3

        for body in bodies:
            # Bounding box
            try:
                box = body.GetBodyBox()  # method: returns (xmin,ymin,zmin, xmax,ymax,zmax) in meters
                if box:
                    for i in range(3):
                        bb_min[i] = min(bb_min[i], box[i] * 1000.0)
                        bb_max[i] = max(bb_max[i], box[i + 3] * 1000.0)
            except Exception:
                pass

            faces = body.GetFaces()  # method
            if faces:
                total_faces += len(faces)
            edges = body.GetEdges()  # method
            if edges:
                total_edges += len(edges)

        total_vertices = self._count_unique_vertices(bodies)

        size_x = bb_max[0] - bb_min[0]
        size_y = bb_max[1] - bb_min[1]
        size_z = bb_max[2] - bb_min[2]

        logger.info(f"Body info: {total_faces} faces, {total_edges} edges, {total_vertices} vertices")
        return self._json_result("✓ Body Info", type="body_info",
            boundingBox={
                "min": {"x": round(bb_min[0], 2), "y": round(bb_min[1], 2), "z": round(bb_min[2], 2)},
                "max": {"x": round(bb_max[0], 2), "y": round(bb_max[1], 2), "z": round(bb_max[2], 2)},
            },
            size={"x": round(size_x, 2), "y": round(size_y, 2), "z": round(size_z, 2)},
            faces=total_faces, edges=total_edges, vertices=total_vertices)

    def get_faces(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        bodies = self._get_bodies(doc)
        filter_type = args.get("surfaceType")
        filter_id = SURFACE_TYPE_FILTER.get(filter_type) if filter_type else None

        all_faces = []
        for body in bodies:
            faces = body.GetFaces()  # method
            if faces:
                all_faces.extend(faces)

        # Apply filter
        if filter_id is not None:
            all_faces = [f for f in all_faces if self._surface_identity(f) == filter_id]

        if not all_faces:
            filter_note = f" (filter: {filter_type})" if filter_type else ""
            return self._json_result(f"✓ No faces found{filter_note}.", type="faces", faces=[])

        face_list = []
        for idx, face in enumerate(all_faces):
            type_str = self._surface_type_str(face)
            try:
                area_mm2 = face.GetArea * 1e6
            except Exception:
                area_mm2 = 0.0
            details = self._surface_details(face)
            sample = self._face_sample_point(face)
            try:
                edge_count = face.GetEdgeCount
            except Exception:
                edge_count = 0

            face_data = {
                "index": idx,
                "surfaceType": type_str,
                "area": round(area_mm2, 2),
                "point": {"x": round(sample[0], 2), "y": round(sample[1], 2), "z": round(sample[2], 2)},
                "edges": edge_count,
            }
            face_data.update(self._feature_fields(self._face_feature_name(face)))
            if details:
                face_data["details"] = details
            face_list.append(face_data)

        logger.info(f"get_faces: returned {len(all_faces)} faces")
        return self._json_result(f"✓ {len(all_faces)} faces", type="faces", faces=face_list)

    def get_edges(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        bodies = self._get_bodies(doc)
        filter_type = args.get("edgeType")

        # Map filter to expected edge type string
        edge_type_map = {
            "LINE": "Line",
            "CIRCLE": "Circle",
            "ARC": "Arc",
        }
        filter_str = edge_type_map.get(filter_type) if filter_type else None
        want_feature = args.get("feature")
        if want_feature and want_feature.startswith("feat:"):
            want_feature = want_feature[5:]

        all_edges = []
        for body in bodies:
            edges = body.GetEdges()  # method
            if edges:
                all_edges.extend(edges)

        # Classify and optionally filter
        edge_data = []
        for edge in all_edges:
            etype = self._edge_type_str(edge)
            if filter_str and etype != filter_str:
                continue
            if want_feature:
                feats = self._edge_features(edge) or []
                if want_feature.lower() not in (f.lower() for f in feats):
                    continue
            edge_data.append((edge, etype))

        if not edge_data:
            notes = [n for n in (filter_type, want_feature and f"feature {want_feature}") if n]
            filter_note = f" (filter: {', '.join(notes)})" if notes else ""
            return self._json_result(f"✓ No edges found{filter_note}.", type="edges", edges=[])

        edge_list = []
        for idx, (edge, etype) in enumerate(edge_data):
            endpoints = self._edge_endpoints(edge)
            mid = self._edge_midpoint(edge)
            length = self._edge_length(edge)
            e = {
                "index": idx,
                "edgeType": etype,
                "midpoint": {"x": round(mid[0], 2), "y": round(mid[1], 2), "z": round(mid[2], 2)},
                "length": round(length, 2),
                "smooth": self._is_edge_smooth(edge),
            }
            features = self._edge_features(edge)
            if features:
                e["features"] = features
            if endpoints:
                s, ep = endpoints
                e["start"] = {"x": round(s[0], 2), "y": round(s[1], 2), "z": round(s[2], 2)}
                e["end"] = {"x": round(ep[0], 2), "y": round(ep[1], 2), "z": round(ep[2], 2)}
            else:
                e["closed"] = True
            edge_list.append(e)

        logger.info(f"get_edges: returned {len(edge_data)} edges")
        return self._json_result(f"✓ {len(edge_data)} edges", type="edges", edges=edge_list)

    def get_face_edges(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        x = args["x"]
        y = args["y"]
        z = args["z"]

        # Select the face
        doc.ClearSelection2(True)
        ok = sel.select_face(doc, x, y, z)
        if not ok:
            raise Exception(f"No face found at ({x}, {y}, {z}) mm")

        # Get the selected face object
        sel_mgr = doc.SelectionManager
        face = sel_mgr.GetSelectedObject6(1, -1)
        if not face:
            raise Exception("Could not retrieve the selected face object")

        # Face info
        type_str = self._surface_type_str(face)
        try:
            area_mm2 = face.GetArea * 1e6  # property
        except Exception:
            area_mm2 = 0.0
        details = self._surface_details(face)
        sample = self._face_sample_point(face)
        sample_str = f"({sample[0]:.2f}, {sample[1]:.2f}, {sample[2]:.2f})"

        face_info = {
            "surfaceType": type_str,
            "area": round(area_mm2, 2),
            "point": {"x": round(sample[0], 2), "y": round(sample[1], 2), "z": round(sample[2], 2)},
        }
        face_info.update(self._feature_fields(self._face_feature_name(face)))
        if details:
            face_info["details"] = details

        # Face edges
        edges = face.GetEdges  # property: tuple of edge COM objects
        edge_list = []
        if edges:
            for idx, edge in enumerate(edges):
                endpoints = self._edge_endpoints(edge)
                mid = self._edge_midpoint(edge)
                length = self._edge_length(edge)
                etype = self._edge_type_str(edge)
                e = {
                    "index": idx,
                    "edgeType": etype,
                    "midpoint": {"x": round(mid[0], 2), "y": round(mid[1], 2), "z": round(mid[2], 2)},
                    "length": round(length, 2),
                    "smooth": self._is_edge_smooth(edge),
                }
                if endpoints:
                    s, ep = endpoints
                    e["start"] = {"x": round(s[0], 2), "y": round(s[1], 2), "z": round(s[2], 2)}
                    e["end"] = {"x": round(ep[0], 2), "y": round(ep[1], 2), "z": round(ep[2], 2)}
                else:
                    e["closed"] = True
                edge_list.append(e)

        doc.ClearSelection2(True)

        face_info["edges"] = edge_list
        logger.info(f"get_face_edges at ({x}, {y}, {z}): {type_str}, {len(edge_list)} edges")
        return self._json_result(f"✓ Face at ({x:.2f}, {y:.2f}, {z:.2f})", type="face_edges", face=face_info)

    def get_vertices(self) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        bodies = self._get_bodies(doc)

        coords = []
        for body in bodies:
            edges = body.GetEdges()  # method
            if not edges:
                continue
            for edge in edges:
                for v in (edge.GetStartVertex, edge.GetEndVertex):  # properties
                    if v:
                        p = v.GetPoint  # property
                        coords.append((p[0] * 1000.0, p[1] * 1000.0, p[2] * 1000.0))

        unique = self._deduplicate_points(coords)
        unique.sort(key=lambda p: (p[0], p[1], p[2]))

        if not unique:
            return self._json_result("✓ No vertices found", type="vertices", vertices=[])

        vertex_list = [
            {"index": idx, "x": round(pt[0], 2), "y": round(pt[1], 2), "z": round(pt[2], 2)}
            for idx, pt in enumerate(unique)
        ]

        logger.info(f"get_vertices: {len(unique)} unique vertices")
        return self._json_result(f"✓ {len(unique)} vertices", type="vertices", vertices=vertex_list)
