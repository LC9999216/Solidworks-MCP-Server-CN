"""
SolidWorks Selection Helpers
Shared utilities for selecting edges, faces, planes, features, and axes.
All coordinate inputs are in millimeters; converted to meters internally.
"""

import logging
import win32com.client
import pythoncom

logger = logging.getLogger(__name__)


def make_callout():
    """Create the standard VT_DISPATCH None callout used in SelectByID2."""
    return win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)


def clear_selection(doc):
    """Clear all selections."""
    doc.ClearSelection2(True)


def _nearest_entity(doc, kind, x_m, y_m, z_m, tol_m=1e-3):
    """Nearest body face/edge COM object within tol_m of a model-space point
    (metres), or None. Pure geometry — no camera involved."""
    best, best_d = None, tol_m
    try:
        bodies = doc.GetBodies2(0, True)
    except Exception:
        return None  # not a part doc (e.g. assembly) — caller falls back
    for body in bodies or []:
        try:
            ents = body.GetFaces() if kind == "face" else body.GetEdges()
        except Exception:
            continue
        for ent in ents or []:
            try:
                cp = ent.GetClosestPointOn(x_m, y_m, z_m)
                d = ((cp[0] - x_m) ** 2 + (cp[1] - y_m) ** 2
                     + (cp[2] - z_m) ** 2) ** 0.5
                if d < best_d:
                    best, best_d = ent, d
            except Exception:
                continue
    return best


def select_entity_object(doc, ent, append=False, mark=0):
    """Select a single entity COM object via IEntity::Select4 with a marked
    SelectData — view-independent. Returns False (without selecting) if a
    marked SelectData can't be created, so callers can fall back to
    SelectByID2 which takes the mark explicitly."""
    import types as _types
    try:
        csd = doc.SelectionManager.CreateSelectData
        sel_data = csd() if isinstance(csd, _types.MethodType) else csd
        sel_data.Mark = mark
    except Exception as e:
        logger.warning(f"CreateSelectData unavailable ({e})")
        return False
    try:
        return bool(ent.Select4(append, sel_data))
    except Exception as e:
        logger.warning(f"Select4 failed: {e}")
        return False


def select_face(doc, x_mm, y_mm, z_mm, append=False, mark=0):
    """Select the face nearest the given point (mm). Returns True/False.

    View-independent: resolves the IFace2 object by geometry (within 1mm)
    and selects it directly, so faces occluded from or edge-on to the
    current camera work. Falls back to a camera-relative SelectByID2 pick
    for coordinates not near any body face (sloppy/off-body input, or
    non-part documents)."""
    x_m, y_m, z_m = x_mm / 1000.0, y_mm / 1000.0, z_mm / 1000.0
    ent = _nearest_entity(doc, "face", x_m, y_m, z_m)
    if ent is not None and select_entity_object(doc, ent, append=append, mark=mark):
        return True
    callout = make_callout()
    ok = doc.Extension.SelectByID2(
        "", "FACE", x_m, y_m, z_m, append, mark, callout, 0
    )
    if not ok:
        logger.warning(f"Failed to select face at ({x_mm}, {y_mm}, {z_mm}) mm")
    return ok


def select_edge(doc, x_mm, y_mm, z_mm, append=False, mark=0):
    """Select the edge nearest the given point (mm). Returns True/False.

    View-independent object selection first (see select_face); SelectByID2
    camera pick as fallback."""
    x_m, y_m, z_m = x_mm / 1000.0, y_mm / 1000.0, z_mm / 1000.0
    ent = _nearest_entity(doc, "edge", x_m, y_m, z_m)
    if ent is not None and select_entity_object(doc, ent, append=append, mark=mark):
        return True
    callout = make_callout()
    ok = doc.Extension.SelectByID2(
        "", "EDGE", x_m, y_m, z_m, append, mark, callout, 0
    )
    if not ok:
        logger.warning(f"Failed to select edge at ({x_mm}, {y_mm}, {z_mm}) mm")
    return ok


def select_entities_directly(doc, entities, mark=0, append_first=False):
    """Select entity COM objects (IEntity::Select4) — view-independent.

    SelectByID2 coordinate picks are resolved against the current camera,
    so occluded geometry is unpickable (no single view sees all 12 edges
    of a box). Selecting the IEntity objects directly bypasses the camera.

    Returns the number of entities successfully selected.
    """
    try:
        import types as _types
        csd = doc.SelectionManager.CreateSelectData
        sel_data = csd() if isinstance(csd, _types.MethodType) else csd
        sel_data.Mark = mark
    except Exception as e:
        # Fail loud: selecting without the requested mark would feed a
        # wrongly-marked selection set to the downstream feature call.
        logger.warning(f"CreateSelectData unavailable ({e}); selecting nothing")
        return 0
    count = 0
    for ent in entities:
        append = append_first or count > 0
        try:
            if ent.Select4(append, sel_data):
                count += 1
            else:
                logger.warning("Direct entity selection returned False")
        except Exception as e:
            logger.warning(f"Direct entity selection failed: {e}")
    return count


def select_multiple_edges(doc, edge_points, mark=1):
    """Select multiple edges from a list of {x, y, z} dicts (mm).

    Args:
        doc: SolidWorks document COM object
        edge_points: list of dicts with x, y, z keys (mm)
        mark: mark value for selection (default 1)
    Returns:
        Number of successfully selected edges
    """
    count = 0
    for i, pt in enumerate(edge_points):
        append = i > 0
        if select_edge(doc, pt["x"], pt["y"], pt["z"], append=append, mark=mark):
            count += 1
    return count


def select_multiple_faces(doc, face_points, mark=0):
    """Select multiple faces from a list of {x, y, z} dicts (mm).

    Args:
        doc: SolidWorks document COM object
        face_points: list of dicts with x, y, z keys (mm)
        mark: mark value for selection (default 0)
    Returns:
        Number of successfully selected faces
    """
    count = 0
    for i, pt in enumerate(face_points):
        append = i > 0
        if select_face(doc, pt["x"], pt["y"], pt["z"], append=append, mark=mark):
            count += 1
    return count


def select_plane(doc, plane_name):
    """Select a reference plane by name ('Front', 'Top', 'Right', or custom).
    Returns True/False.
    """
    # Map short names to SolidWorks full names
    plane_map = {
        "Front": "Front Plane",
        "Top": "Top Plane",
        "Right": "Right Plane",
        "Front Plane": "Front Plane",
        "Top Plane": "Top Plane",
        "Right Plane": "Right Plane",
    }
    full_name = plane_map.get(plane_name, plane_name)

    feature = doc.FeatureByName(full_name)
    if not feature:
        logger.warning(f"Plane '{full_name}' not found")
        return False
    doc.ClearSelection2(True)
    return feature.Select2(False, 0)


def select_plane_with_mark(doc, plane_name, mark=0, append=False):
    """Select a reference plane by name with a specific mark value.
    Uses FeatureByName + Select2 which works reliably for both
    standard planes (Front/Top/Right) and custom reference planes.
    Returns True/False.
    """
    plane_map = {
        "Front": "Front Plane",
        "Top": "Top Plane",
        "Right": "Right Plane",
        "Front Plane": "Front Plane",
        "Top Plane": "Top Plane",
        "Right Plane": "Right Plane",
    }
    full_name = plane_map.get(plane_name, plane_name)
    feature = doc.FeatureByName(full_name)
    if not feature:
        logger.warning(f"Plane '{full_name}' not found by FeatureByName")
        return False
    if not append:
        doc.ClearSelection2(True)
    ok = feature.Select2(append, mark)
    if not ok:
        logger.warning(f"Failed to select plane '{full_name}' with mark={mark}")
    return ok


def select_feature(doc, feature_name, mark=0, append=False):
    """Select a feature by name in the feature tree.
    Returns True/False.
    """
    callout = make_callout()
    ok = doc.Extension.SelectByID2(
        feature_name, "BODYFEATURE",
        0, 0, 0,
        append, mark, callout, 0
    )
    if not ok:
        logger.warning(f"Failed to select feature '{feature_name}'")
    return ok


def select_multiple_features(doc, feature_names, mark=4):
    """Select multiple features by name.

    Args:
        doc: SolidWorks document COM object
        feature_names: list of feature name strings
        mark: mark value for selection (default 4 for pattern operations)
    Returns:
        Number of successfully selected features
    """
    count = 0
    for i, name in enumerate(feature_names):
        append = i > 0
        if select_feature(doc, name, mark=mark, append=append):
            count += 1
    return count


def select_sketch(doc, sketch_name, mark=0, append=False):
    """Select a sketch by name for sweep/loft operations.
    Returns True/False.
    """
    callout = make_callout()
    ok = doc.Extension.SelectByID2(
        sketch_name, "SKETCH",
        0, 0, 0,
        append, mark, callout, 0
    )
    if not ok:
        logger.warning(f"Failed to select sketch '{sketch_name}'")
    return ok


def select_axis(doc, axis_name, mark=0, append=False):
    """Select a reference axis by name.
    Returns True/False.
    """
    callout = make_callout()
    ok = doc.Extension.SelectByID2(
        axis_name, "AXIS",
        0, 0, 0,
        append, mark, callout, 0
    )
    if not ok:
        logger.warning(f"Failed to select axis '{axis_name}'")
    return ok


def select_axis_by_point(doc, x_mm, y_mm, z_mm, mark=0, append=False):
    """Select an axis by a point near it (mm).
    Returns True/False.
    """
    callout = make_callout()
    ok = doc.Extension.SelectByID2(
        "", "AXIS",
        x_mm / 1000.0, y_mm / 1000.0, z_mm / 1000.0,
        append, mark, callout, 0
    )
    if not ok:
        logger.warning(f"Failed to select axis at ({x_mm}, {y_mm}, {z_mm}) mm")
    return ok


def select_vertex(doc, x_mm, y_mm, z_mm, mark=0, append=False):
    """Select a vertex at the given point (mm).
    Returns True/False.
    """
    callout = make_callout()
    ok = doc.Extension.SelectByID2(
        "", "VERTEX",
        x_mm / 1000.0, y_mm / 1000.0, z_mm / 1000.0,
        append, mark, callout, 0
    )
    if not ok:
        logger.warning(f"Failed to select vertex at ({x_mm}, {y_mm}, {z_mm}) mm")
    return ok


def exit_sketch_and_select(doc, sketch_name):
    """Exit the current sketch and select it by name for feature creation.
    Returns the sketch feature or raises an exception.
    """
    doc.ClearSelection2(True)
    doc.SketchManager.InsertSketch(True)

    sketch_feature = doc.FeatureByName(sketch_name)
    if not sketch_feature:
        raise Exception(f"Sketch '{sketch_name}' not found in feature tree")

    doc.ClearSelection2(True)
    sketch_feature.Select2(False, 0)
    return sketch_feature
