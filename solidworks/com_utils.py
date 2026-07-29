"""
Shared COM helpers for late-bound (dynamic dispatch) SolidWorks objects.
"""

import logging
import types

logger = logging.getLogger(__name__)


def verify_rebuild(doc):
    """Rebuild and verify no feature is in an error state.

    Returns (ok: bool, problems: list[str]). A dimension change that breaks a
    downstream feature previously returned an unconditional ✓ —
    ForceRebuild3's return and the feature tree's error markers were
    never read.
    """
    problems = []
    try:
        rebuilt = bool(doc.ForceRebuild3(False))
    except Exception:
        try:
            rebuilt = bool(doc.ForceRebuild3(True))
        except Exception as e:
            return False, [f"rebuild call failed: {e}"]
    # Feature-tree error scan. GetErrorCode2 takes a BYREF BOOL variant
    # (probed live 2026-07-11: plain bool/int raise Type mismatch); returns
    # swFeatureError_e, 0 = no error.
    try:
        import pythoncom
        import win32com.client
        feats = doc.FeatureManager.GetFeatures(True)
        for f in feats or []:
            try:
                arg = win32com.client.VARIANT(
                    pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
                code = f.GetErrorCode2(arg)
                if code:
                    problems.append(f"{f.Name}: error code {code}")
            except Exception:
                continue
    except Exception:
        pass
    if not rebuilt and not problems:
        problems.append("ForceRebuild3 returned False (unspecified rebuild error)")
    return (rebuilt and not problems), problems


def exit_active_sketch(doc, tracker=None):
    """Exit sketch-edit mode (if a sketch is active) AND close the sketch in
    the state tracker with the name read back from the feature tree.

    Feature tools used to call InsertSketch(True) directly, which left
    tracker scope.active_sketch set and skipped close_sketch's name
    correction — subsequent entity IDs and sketch lookups desynced.

    Returns the actual sketch name (newest ProfileFeature) or None if no
    sketch was active / the name could not be read back.
    """
    try:
        active = doc.SketchManager.ActiveSketch
    except Exception:
        active = None
    if active is None:
        return None

    doc.ClearSelection2(True)
    doc.SketchManager.InsertSketch(True)

    # Read the REAL name back: newest ProfileFeature in the tree (same
    # authority exit_sketch uses).
    actual = None
    try:
        for feature in reversed(doc.FeatureManager.GetFeatures(True) or []):
            if feature.GetTypeName2 == "ProfileFeature":
                actual = feature.Name
                break
    except Exception as e:
        logger.warning(f"Sketch name read-back failed on implicit exit: {e}")

    if tracker is not None and actual:
        try:
            tracker.close_sketch(actual)
        except Exception as e:
            logger.warning(f"tracker.close_sketch failed on implicit exit: {e}")
    return actual


def resolve_tracked_name(tracker, name_or_id,
                         prefixes=("feat:", "sketch:", "ref:")):
    """Resolve a tracked ID (feat:/sketch:/ref:) to its SolidWorks name via
    the tracker; raw names pass through with a deprecation warning.
    Shared by features/cut_features/patterns (was triplicated)."""
    if tracker and name_or_id.startswith(prefixes):
        return tracker.resolve_name(name_or_id)
    if tracker:
        logger.warning(
            f"Raw SolidWorks name '{name_or_id}' used — consider using tracked ID instead"
        )
    return name_or_id


def com_prop(obj, name):
    """Read a late-bound member that may bind as a property or a 0-arg method.

    win32com dynamic dispatch resolves most 0-arg SolidWorks members as
    property-gets; the ones it can't, it wraps in a bound method that must be
    called. IMPORTANT: do NOT test the result with callable() — CDispatch COM
    objects are themselves callable (invoking their default dispatch method),
    so calling a returned COM object raises 'Member not found'. Only invoke
    when win32com actually returned a bound-method wrapper.
    """
    val = getattr(obj, name)
    if isinstance(val, types.MethodType):
        val = val()
    return val
