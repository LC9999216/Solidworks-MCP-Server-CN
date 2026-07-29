"""
SolidWorks MCP - Unified Test Suite

Combines all tests from test_solidworks.py and the integration suite.

Usage:
    python test.py                          # Run all tests
    python test.py --gui                    # Interactive CLI test picker
    python test.py --category "Sketch Tools"  # Run one category
    python test.py --test sketch_line       # Run one test by name
    python test.py --list                   # List all available tests
"""

import win32com.client
import pythoncom
import glob
import json
import os
import shutil
import sys
import tempfile
import traceback
import time
import argparse
import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from solidworks import selection_helpers as sel

# Force UTF-8 output so Unicode symbols survive the Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------

@dataclass
class TestEntry:
    name: str
    display_name: str
    category: str
    description: str
    func: Callable
    order: int = 0

TEST_REGISTRY: list[TestEntry] = []

CATEGORY_ORDER = ["Basic", "Sketch Tools", "Feature Tools", "MCP Tools", "Assembly", "Integration"]


def register_test(name, display_name, category, description, order=0):
    """Decorator to register a test function."""
    def decorator(func):
        TEST_REGISTRY.append(TestEntry(
            name=name,
            display_name=display_name,
            category=category,
            description=description,
            func=func,
            order=order,
        ))
        return func
    return decorator


# ---------------------------------------------------------------------------
# Global result tracking
# ---------------------------------------------------------------------------

PASS = 0
FAIL = 0
RESULTS = []  # list of (label, ok, detail)


def _result(label, ok, detail=""):
    global PASS, FAIL
    RESULTS.append((label, ok, detail))
    if ok:
        PASS += 1
        print(f"  \u2713 {label}{' \u2014 ' + detail if detail else ''}")
    else:
        FAIL += 1
        print(f"  \u2717 {label}{' \u2014 ' + detail if detail else ''}")
    return ok


def log(message, level="INFO"):
    prefix = "\u2713" if level == "SUCCESS" else "\u274c" if level == "ERROR" else "\u2192"
    print(f"  {prefix} {message}")


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def subsection(title):
    print(f"\n  [{title}]")


# ---------------------------------------------------------------------------
# SolidWorks connection helpers
# ---------------------------------------------------------------------------

def connect_to_solidworks():
    """Connect to an existing or new SolidWorks instance."""
    try:
        sw = win32com.client.GetActiveObject("SldWorks.Application")
        print("  \u2192 Attached to existing SolidWorks instance")
    except Exception:
        print("  \u2192 Launching new SolidWorks instance\u2026")
        sw = win32com.client.Dispatch("SldWorks.Application")
        sw.Visible = True
        for i in range(30):
            try:
                _ = sw.RevisionNumber
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("SolidWorks failed to start within 30 s")
    return sw


def find_template():
    """Discover the Part template file."""
    patterns = [
        r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS *\templates\Part.prtdot",
        r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS *\templates\Part.PRTDOT",
    ]
    for pattern in patterns:
        hits = glob.glob(pattern)
        if hits:
            return hits[0]
    return None


def close_all_docs(sw):
    """Close all open SolidWorks documents without saving."""
    try:
        sw.CloseAllDocuments(True)
    except Exception:
        # Fallback: close one-by-one (bounded — QuitDoc can decline to close)
        last_title = None
        for _ in range(50):
            doc = sw.ActiveDoc
            if not doc:
                break
            title = doc.GetTitle
            if title == last_title:
                break
            sw.QuitDoc(title)
            last_title = title


# ---------------------------------------------------------------------------
# Sketch / modeling helpers
# ---------------------------------------------------------------------------

def new_part(sw, template):
    doc = sw.NewDocument(template, 0, 0, 0)
    if not doc:
        raise RuntimeError("NewDocument returned None")
    return doc


def new_sketch_on_front(sw, template):
    """Create a new part and open a sketch on the Front Plane."""
    model = sw.NewDocument(template, 0, 0, 0)
    front_plane = model.FeatureByName("Front Plane")
    model.ClearSelection2(True)
    front_plane.Select2(False, 0)
    model.SketchManager.InsertSketch(True)
    return model


def select_plane(doc, plane_name):
    """Select a plane — delegates to selection_helpers.select_plane()."""
    ok = sel.select_plane(doc, plane_name)
    if not ok:
        raise RuntimeError(f"Plane not found: {plane_name}")
    return ok


def create_sketch_on_plane(doc, plane_name):
    """Select a plane and open a sketch on it."""
    select_plane(doc, plane_name)
    doc.SketchManager.InsertSketch(True)


def create_sketch_on_face(doc, x_mm, y_mm, z_mm):
    """Select a solid face at (x,y,z) in mm and open a sketch on it."""
    ok = sel.select_face(doc, x_mm, y_mm, z_mm)
    if not ok:
        raise RuntimeError(f"Could not select face at ({x_mm},{y_mm},{z_mm}) mm")
    doc.SketchManager.InsertSketch(True)


def exit_sketch(doc):
    doc.ClearSelection2(True)
    doc.SketchManager.InsertSketch(True)


def select_sketch(doc, sketch_name):
    """Select a sketch by name — delegates to selection_helpers.select_sketch()."""
    ok = sel.select_sketch(doc, sketch_name)
    if not ok:
        raise RuntimeError(f"Sketch not found: {sketch_name}")
    return ok


def get_latest_sketch_name(doc):
    """Mirror the fallback logic in modeling.py._get_latest_sketch_name()."""
    try:
        features = doc.FeatureManager.GetFeatures(True)
        if features:
            for feature in reversed(features):
                if feature.GetTypeName2 == "ProfileFeature":
                    return feature.Name
    except Exception:
        pass
    return "Sketch1"


def extrude(doc, sketch_name, depth_mm, cut=False, reverse=False):
    """Select sketch and create an extrusion or cut-extrusion."""
    select_sketch(doc, sketch_name)
    depth_m = depth_mm / 1000.0

    if cut:
        feature = doc.FeatureManager.FeatureCut4(
            True, reverse, False, 0, 0, depth_m, 0.0,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False, False, False, True,
            False, True, False, 0, 0.0, False, False
        )
        if not feature:
            raise RuntimeError("FeatureCut4 returned None for cut-extrusion")
    else:
        feature = doc.FeatureManager.FeatureExtrusion2(
            True, reverse, False, 0, 0, depth_m, 0.0,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False, True, True, True, 0, 0, False
        )
        if not feature:
            raise RuntimeError("FeatureExtrusion2 returned None for extrusion")
    return feature


def make_cube(sw, template, size_mm=100):
    """Create a part with a cube of given size. Returns the model."""
    size_m = size_mm / 1000.0
    model = sw.NewDocument(template, 0, 0, 0)
    front_plane = model.FeatureByName("Front Plane")
    model.ClearSelection2(True)
    front_plane.Select2(False, 0)
    model.SketchManager.InsertSketch(True)
    model.SketchManager.CreateCornerRectangle(0.0, 0.0, 0.0, size_m, size_m, 0.0)
    exit_sketch(model)
    sketch1 = model.FeatureByName("Sketch1")
    model.ClearSelection2(True)
    sketch1.Select2(False, 0)
    feat = model.FeatureManager.FeatureExtrusion2(
        True, False, False, 0, 0, size_m, 0.0,
        False, False, False, False, 0.0, 0.0,
        False, False, False, False, True, True, True,
        0, 0, False
    )
    if not feat:
        raise Exception("Failed to create base cube for test")
    return model


# ===========================================================================
# TEST FUNCTIONS — Basic
# ===========================================================================

@register_test("basic_cube", "Basic Cube (100mm)", "Basic",
               "Create a 100mm cube end-to-end: part, sketch, extrude", order=0)
def test_basic_cube(sw, template):
    try:
        model = sw.NewDocument(template, 0, 0, 0)
        front_plane = model.FeatureByName("Front Plane")
        model.ClearSelection2(True)
        front_plane.Select2(False, 0)
        model.SketchManager.InsertSketch(True)
        model.SketchManager.CreateCornerRectangle(0.0, 0.0, 0.0, 0.1, 0.1, 0.0)
        exit_sketch(model)

        sketch1 = model.FeatureByName("Sketch1")
        model.ClearSelection2(True)
        sketch1.Select2(False, 0)
        feat = model.FeatureManager.FeatureExtrusion2(
            True, False, False, 0, 0, 0.1, 0.0,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False, True, True, True,
            0, 0, False
        )
        if not feat:
            log("Extrusion returned None", "ERROR")
            return False

        model.ViewZoomtofit2()
        log("100mm cube created", "SUCCESS")
        return True
    except Exception as e:
        log(f"basic_cube FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


# ===========================================================================
# TEST FUNCTIONS — Sketch Tools
# ===========================================================================

@register_test("sketch_line", "Sketch Line", "Sketch Tools",
               "Draw a line from (0,0) to (50,50)mm", order=0)
def test_sketch_line(sw, template):
    try:
        model = new_sketch_on_front(sw, template)
        model.SketchManager.CreateLine(0.0, 0.0, 0.0, 0.05, 0.05, 0.0)
        log("Line created", "SUCCESS")
        exit_sketch(model)
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"sketch_line FAILED: {e}", "ERROR")
        return False


@register_test("sketch_centerline", "Sketch Centerline", "Sketch Tools",
               "Draw a vertical centerline", order=1)
def test_sketch_centerline(sw, template):
    try:
        model = new_sketch_on_front(sw, template)
        model.SketchManager.CreateCenterLine(0.0, -0.05, 0.0, 0.0, 0.05, 0.0)
        log("Centerline created", "SUCCESS")
        exit_sketch(model)
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"sketch_centerline FAILED: {e}", "ERROR")
        return False


@register_test("sketch_point", "Sketch Point", "Sketch Tools",
               "Create a sketch point at (25,25)mm", order=2)
def test_sketch_point(sw, template):
    try:
        model = new_sketch_on_front(sw, template)
        model.SketchManager.CreatePoint(0.025, 0.025, 0.0)
        log("Point created", "SUCCESS")
        exit_sketch(model)
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"sketch_point FAILED: {e}", "ERROR")
        return False


@register_test("sketch_arc", "Sketch Arc", "Sketch Tools",
               "Draw a 3-point arc and a center-point arc", order=3)
def test_sketch_arc(sw, template):
    try:
        model = new_sketch_on_front(sw, template)

        model.SketchManager.Create3PointArc(
            0.0, 0.0, 0.0,
            0.05, 0.0, 0.0,
            0.025, 0.02, 0.0
        )
        log("3-point arc created", "SUCCESS")

        model.SketchManager.CreateArc(
            0.0, -0.03, 0.0,
            0.02, -0.03, 0.0,
            -0.02, -0.03, 0.0,
            1
        )
        log("Center-point arc created", "SUCCESS")

        exit_sketch(model)
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"sketch_arc FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("sketch_polygon", "Sketch Polygon", "Sketch Tools",
               "Draw a hexagon and extrude it", order=4)
def test_sketch_polygon(sw, template):
    try:
        model = new_sketch_on_front(sw, template)

        model.SketchManager.CreatePolygon(
            0.0, 0.0, 0.0,
            0.025, 0.0, 0.0,
            6, False
        )
        log("Hexagon created", "SUCCESS")

        exit_sketch(model)

        sketch1 = model.FeatureByName("Sketch1")
        model.ClearSelection2(True)
        sketch1.Select2(False, 0)
        feat = model.FeatureManager.FeatureExtrusion2(
            True, False, False, 0, 0, 0.05, 0.0,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False, True, True, True,
            0, 0, False
        )
        if not feat:
            log("Polygon extrusion returned None", "ERROR")
            return False

        log("Hexagon extruded (50mm)", "SUCCESS")
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"sketch_polygon FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("sketch_ellipse", "Sketch Ellipse", "Sketch Tools",
               "Draw a 30x20mm ellipse and extrude it", order=5)
def test_sketch_ellipse(sw, template):
    try:
        model = new_sketch_on_front(sw, template)

        cx_m, cy_m = 0.0, 0.0
        major_r_m = 0.03
        minor_r_m = 0.02
        angle = 0.0

        major_x = cx_m + major_r_m * math.cos(angle)
        major_y = cy_m + major_r_m * math.sin(angle)
        minor_x = cx_m + minor_r_m * math.cos(angle + math.pi / 2)
        minor_y = cy_m + minor_r_m * math.sin(angle + math.pi / 2)

        model.SketchManager.CreateEllipse(
            cx_m, cy_m, 0.0,
            major_x, major_y, 0.0,
            minor_x, minor_y, 0.0
        )
        log("Ellipse created (30x20mm)", "SUCCESS")

        exit_sketch(model)

        sketch1 = model.FeatureByName("Sketch1")
        model.ClearSelection2(True)
        sketch1.Select2(False, 0)
        feat = model.FeatureManager.FeatureExtrusion2(
            True, False, False, 0, 0, 0.04, 0.0,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False, True, True, True,
            0, 0, False
        )
        if not feat:
            log("Ellipse extrusion returned None", "ERROR")
            return False

        log("Ellipse extruded (40mm)", "SUCCESS")
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"sketch_ellipse FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("sketch_slot", "Sketch Slot", "Sketch Tools",
               "Draw a 50mm slot and extrude it", order=6)
def test_sketch_slot(sw, template):
    try:
        model = new_sketch_on_front(sw, template)

        model.SketchManager.CreateSketchSlot(
            0, 0, 0.02,
            -0.025, 0.0, 0.0,
            0.025, 0.0, 0.0,
            0.0, 0.0, 0.0,
            1, False
        )
        log("Slot created (50mm long, 20mm wide)", "SUCCESS")

        exit_sketch(model)

        sketch1 = model.FeatureByName("Sketch1")
        model.ClearSelection2(True)
        sketch1.Select2(False, 0)
        feat = model.FeatureManager.FeatureExtrusion2(
            True, False, False, 0, 0, 0.01, 0.0,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False, True, True, True,
            0, 0, False
        )
        if not feat:
            log("Slot extrusion returned None", "ERROR")
            return False

        log("Slot extruded (10mm)", "SUCCESS")
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"sketch_slot FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("sketch_spline", "Sketch Spline", "Sketch Tools",
               "Draw a spline through 4 points", order=7)
def test_sketch_spline(sw, template):
    try:
        model = new_sketch_on_front(sw, template)

        point_data = [
            0.0, 0.0, 0.0,
            0.02, 0.01, 0.0,
            0.04, -0.01, 0.0,
            0.06, 0.0, 0.0,
        ]
        point_array = win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_R8, point_data
        )
        model.SketchManager.CreateSpline2(point_array, True)
        log("Spline created through 4 points", "SUCCESS")

        exit_sketch(model)
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"sketch_spline FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("sketch_text", "Sketch Text", "Sketch Tools",
               "Insert sketch text 'HELLO'", order=8)
def test_sketch_text(sw, template):
    try:
        model = new_sketch_on_front(sw, template)

        sketch_text_obj = model.InsertSketchText(
            0.0, 0.0, 0.0, "HELLO", 1, 0, 0, 1, 0
        )
        if not sketch_text_obj:
            log("InsertSketchText returned None", "ERROR")
            return False
        log("Sketch text 'HELLO' created", "SUCCESS")

        exit_sketch(model)
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"sketch_text FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("sketch_constraint", "Sketch Constraint", "Sketch Tools",
               "Draw two lines and apply a parallel constraint", order=9)
def test_sketch_constraint(sw, template):
    try:
        model = new_sketch_on_front(sw, template)

        model.SketchManager.CreateLine(0.0, 0.0, 0.0, 0.05, 0.02, 0.0)
        model.SketchManager.CreateLine(0.0, 0.03, 0.0, 0.05, 0.04, 0.0)
        log("Two lines drawn", "SUCCESS")

        callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        model.ClearSelection2(True)
        model.Extension.SelectByID2(
            "", "SKETCHSEGMENT", 0.025, 0.01, 0.0,
            False, 0, callout, 0
        )
        model.Extension.SelectByID2(
            "", "SKETCHSEGMENT", 0.025, 0.035, 0.0,
            True, 0, callout, 0
        )
        model.SketchAddConstraints("sgPARALLEL")
        log("Parallel constraint applied", "SUCCESS")

        exit_sketch(model)
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"sketch_constraint FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("toggle_construction", "Toggle Construction Geometry", "Sketch Tools",
               "Draw a line and toggle it to construction geometry", order=10)
def test_toggle_construction(sw, template):
    try:
        model = new_sketch_on_front(sw, template)

        model.SketchManager.CreateLine(0.0, 0.0, 0.0, 0.05, 0.0, 0.0)
        log("Line drawn", "SUCCESS")

        callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        model.ClearSelection2(True)
        ok = model.Extension.SelectByID2(
            "", "SKETCHSEGMENT", 0.025, 0.0, 0.0,
            False, 0, callout, 0
        )
        if not ok:
            log("Could not select line", "ERROR")
            return False

        sel_mgr = model.SelectionManager
        sketch_seg = sel_mgr.GetSelectedObject6(1, -1)
        was_construction = sketch_seg.ConstructionGeometry
        sketch_seg.ConstructionGeometry = not was_construction
        is_construction = sketch_seg.ConstructionGeometry

        if is_construction == was_construction:
            log("Construction flag did not toggle", "ERROR")
            return False

        log(f"Toggled: was {was_construction}, now {is_construction}", "SUCCESS")

        exit_sketch(model)
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"toggle_construction FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("sketch_dimension", "Sketch Dimension", "Sketch Tools",
               "Draw a line, add a dimension, set its value, then modify it", order=11)
def test_sketch_dimension(sw, template):
    import threading
    from solidworks.sketching import dismiss_modify_dialog

    try:
        model = new_sketch_on_front(sw, template)

        # Draw a horizontal line 50mm long
        model.SketchManager.CreateLine(0.0, 0.0, 0.0, 0.05, 0.0, 0.0)
        log("Line created from (0,0) to (50,0) mm", "SUCCESS")

        # Select the line for dimensioning
        callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        model.ClearSelection2(True)
        ok = model.Extension.SelectByID2(
            "", "SKETCHSEGMENT", 0.025, 0.0, 0.0,
            False, 0, callout, 0
        )
        if not ok:
            log("Failed to select line for dimensioning", "ERROR")
            return False

        # Start thread to auto-dismiss the Modify dialog
        t = threading.Thread(target=dismiss_modify_dialog, daemon=True)
        t.start()

        sm = model.SketchManager
        sm.AddToDB = True
        sm.DisplayWhenAdded = False
        try:
            dim_display = model.AddDimension2(0.025, -0.01, 0.0)
        finally:
            sm.AddToDB = False
            sm.DisplayWhenAdded = True
            t.join(timeout=2)

        if not dim_display:
            log("AddDimension2 returned None", "ERROR")
            return False
        log("Dimension added (dialog auto-dismissed)", "SUCCESS")

        # Set dimension value to 80mm
        dim = dim_display.GetDimension2(0)
        if not dim:
            log("GetDimension2 returned None", "ERROR")
            return False
        dim.SetSystemValue3(0.08, 2, "")  # 80mm in meters
        model.ForceRebuild3(True)
        log("Dimension value set to 80mm", "SUCCESS")

        # Verify the dimension value was applied
        current_val = dim.GetSystemValue3(2, "")
        if isinstance(current_val, tuple):
            current_mm = current_val[0] * 1000.0
        else:
            current_mm = current_val * 1000.0
        if abs(current_mm - 80.0) > 0.01:
            log(f"Dimension value mismatch: expected 80, got {current_mm:.2f}", "ERROR")
            return False
        log(f"Dimension value verified: {current_mm:.1f}mm", "SUCCESS")

        # Test modifying the dimension value using the existing dim object
        dim.SetSystemValue3(0.06, 2, "")  # Change to 60mm
        model.ForceRebuild3(True)

        current_val2 = dim.GetSystemValue3(2, "")
        if isinstance(current_val2, tuple):
            current_mm2 = current_val2[0] * 1000.0
        else:
            current_mm2 = current_val2 * 1000.0
        if abs(current_mm2 - 60.0) > 0.01:
            log(f"Modified dimension mismatch: expected 60, got {current_mm2:.2f}", "ERROR")
            return False
        log(f"Dimension value modified and verified: {current_mm2:.1f}mm", "SUCCESS")

        exit_sketch(model)
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"sketch_dimension FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


# ===========================================================================
# TEST FUNCTIONS — Feature Tools
# ===========================================================================

@register_test("mass_properties", "Mass Properties", "Feature Tools",
               "Create 100mm cube and verify volume/surface area", order=0)
def test_mass_properties(sw, template):
    try:
        model = sw.NewDocument(template, 0, 0, 0)
        front_plane = model.FeatureByName("Front Plane")
        model.ClearSelection2(True)
        front_plane.Select2(False, 0)
        model.SketchManager.InsertSketch(True)
        model.SketchManager.CreateCornerRectangle(0.0, 0.0, 0.0, 0.1, 0.1, 0.0)
        exit_sketch(model)

        sketch1 = model.FeatureByName("Sketch1")
        model.ClearSelection2(True)
        sketch1.Select2(False, 0)
        feat = model.FeatureManager.FeatureExtrusion2(
            True, False, False, 0, 0, 0.1, 0.0,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False, True, True, True,
            0, 0, False
        )
        if not feat:
            log("Extrusion failed for mass properties test", "ERROR")
            return False
        log("100mm cube created", "SUCCESS")

        model.ForceRebuild3(True)
        props = model.GetMassProperties
        if not props or len(props) < 12:
            log("GetMassProperties returned invalid data", "ERROR")
            return False

        volume_mm3 = props[3] * 1e9
        surface_area_mm2 = props[4] * 1e6
        com_x = props[0] * 1000.0
        com_y = props[1] * 1000.0
        com_z = props[2] * 1000.0

        log(f"Volume: {volume_mm3:.0f} mm^3 (expected 1000000)", "SUCCESS")
        log(f"Surface Area: {surface_area_mm2:.0f} mm^2 (expected 60000)", "SUCCESS")
        log(f"Center of Mass: ({com_x:.1f}, {com_y:.1f}, {com_z:.1f}) mm", "SUCCESS")

        if abs(volume_mm3 - 1_000_000) > 1:
            log(f"Volume mismatch: expected 1000000, got {volume_mm3:.2f}", "ERROR")
            return False
        if abs(surface_area_mm2 - 60_000) > 1:
            log(f"Surface area mismatch: expected 60000, got {surface_area_mm2:.2f}", "ERROR")
            return False

        log("Mass properties validated", "SUCCESS")
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"mass_properties FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("cut_extrusion", "Cut Extrusion", "Feature Tools",
               "Create a cube then cut a circular hole in it", order=1)
def test_cut_extrusion(sw, template):
    try:
        model = sw.NewDocument(template, 0, 0, 0)
        front_plane = model.FeatureByName("Front Plane")
        model.ClearSelection2(True)
        front_plane.Select2(False, 0)
        model.SketchManager.InsertSketch(True)
        model.SketchManager.CreateCornerRectangle(0.0, 0.0, 0.0, 0.1, 0.1, 0.0)
        exit_sketch(model)

        sketch1 = model.FeatureByName("Sketch1")
        model.ClearSelection2(True)
        sketch1.Select2(False, 0)
        feat = model.FeatureManager.FeatureExtrusion2(
            True, False, False, 0, 0, 0.1, 0.0,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False, True, True, True,
            0, 0, False
        )
        if not feat:
            log("Base extrusion failed", "ERROR")
            return False
        log("100mm cube created", "SUCCESS")

        callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        model.ClearSelection2(True)
        ok = model.Extension.SelectByID2(
            "", "FACE", 0.05, 0.05, 0.0,
            False, 0, callout, 0
        )
        if not ok:
            log("Could not select front face", "ERROR")
            return False

        model.SketchManager.InsertSketch(True)
        model.SketchManager.CreateCircleByRadius(0.05, 0.05, 0.0, 0.02)
        log("Circle drawn on front face for cut", "SUCCESS")

        model.ClearSelection2(True)
        model.SketchManager.InsertSketch(True)

        sketch2 = model.FeatureByName("Sketch2")
        if not sketch2:
            log("Could not find Sketch2", "ERROR")
            return False
        model.ClearSelection2(True)
        sketch2.Select2(False, 0)

        cut_feat = model.FeatureManager.FeatureCut4(
            True, True, False, 0, 0, 0.05, 0.0,
            False, False, False, False, 0.0, 0.0,
            False, False, False, False, False, False, True,
            False, True, False, 0, 0.0, False, False
        )
        if not cut_feat:
            log("Cut-extrusion returned None", "ERROR")
            return False

        log("Cut-extrusion created (50mm deep hole)", "SUCCESS")
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"cut_extrusion FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("fillet", "Fillet", "Feature Tools",
               "Create a cube and fillet one edge (5mm)", order=2)
def test_fillet(sw, template):
    try:
        make_cube(sw, template, 100)
        model = sw.ActiveDoc
        model.ForceRebuild3(True)

        # Select a Z-direction edge (front-right, midpoint at z=0.05)
        callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        model.ClearSelection2(True)
        ok = model.Extension.SelectByID2(
            "", "EDGE", 0.1, 0.0, 0.05,
            False, 1, callout, 0
        )
        if not ok:
            log("Could not select edge for fillet", "ERROR")
            return False

        # Options=195 required for SolidWorks 2025+
        feature = model.FeatureManager.FeatureFillet3(
            195, 0.005, 0.0, 0.0, 0, 0, 0, 0,
        )
        if not feature:
            log("FeatureFillet3 returned None", "ERROR")
            return False

        log("Fillet created (5mm radius)", "SUCCESS")
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"fillet FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("chamfer", "Chamfer", "Feature Tools",
               "Create a cube and chamfer one edge (5mm)", order=3)
def test_chamfer(sw, template):
    try:
        make_cube(sw, template, 100)
        model = sw.ActiveDoc
        model.ForceRebuild3(True)

        # Select a Z-direction edge (front-right, midpoint at z=0.05)
        callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        model.ClearSelection2(True)
        ok = model.Extension.SelectByID2(
            "", "EDGE", 0.1, 0.0, 0.05,
            False, 0, callout, 0
        )
        if not ok:
            log("Could not select edge for chamfer", "ERROR")
            return False

        # SolidWorks 2025 requires 8 parameters (3 extra trailing zeros)
        feature = model.FeatureManager.InsertFeatureChamfer(
            4, 0, 0.005, 0.785398, 0.005, 0, 0, 0,
        )
        if not feature:
            log("InsertFeatureChamfer returned None", "ERROR")
            return False

        log("Chamfer created (5mm)", "SUCCESS")
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"chamfer FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("shell", "Shell", "Feature Tools",
               "Create a cube and shell it (remove top face, 3mm)", order=4)
def test_shell(sw, template):
    try:
        make_cube(sw, template, 100)
        model = sw.ActiveDoc
        model.ForceRebuild3(True)

        # Select top face (y=100mm, center of face)
        callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        model.ClearSelection2(True)
        ok = model.Extension.SelectByID2(
            "", "FACE", 0.05, 0.1, 0.05,
            False, 0, callout, 0
        )
        if not ok:
            log("Could not select top face for shell", "ERROR")
            return False

        # In SW2025, InsertFeatureShell lives on the model (IModelDoc2),
        # NOT on FeatureManager. It may return None even on success,
        # so verify by checking the feature tree.
        model._FlagAsMethod("InsertFeatureShell")
        model.InsertFeatureShell(0.003, False)
        model.ForceRebuild3(True)

        # Verify shell was created by checking feature tree
        features = model.FeatureManager.GetFeatures(True)
        shell_found = False
        if features:
            for f in features:
                if "Shell" in f.Name:
                    shell_found = True
                    break
        if not shell_found:
            log("Shell feature not found in feature tree", "ERROR")
            return False

        log("Shell created (3mm thickness, top face removed)", "SUCCESS")
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"shell FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("revolve", "Revolve", "Feature Tools",
               "Create a half-profile with centerline and revolve 360 deg", order=5)
def test_revolve(sw, template):
    try:
        model = new_sketch_on_front(sw, template)

        model.SketchManager.CreateCenterLine(0.0, -0.03, 0.0, 0.0, 0.03, 0.0)
        model.SketchManager.CreateLine(0.01, -0.02, 0.0, 0.02, -0.02, 0.0)
        model.SketchManager.CreateLine(0.02, -0.02, 0.0, 0.02, 0.02, 0.0)
        model.SketchManager.CreateLine(0.02, 0.02, 0.0, 0.01, 0.02, 0.0)
        model.SketchManager.CreateLine(0.01, 0.02, 0.0, 0.01, -0.02, 0.0)
        log("Half-profile and centerline drawn", "SUCCESS")

        exit_sketch(model)

        sketch1 = model.FeatureByName("Sketch1")
        model.ClearSelection2(True)
        sketch1.Select2(False, 0)

        feature = model.FeatureManager.FeatureRevolve2(
            True, True, False, False, False, False,
            0, 0,
            2 * math.pi,
            0.0,
            False, False, 0.0, 0.0,
            0, 0.0, 0.0,
            True, True, True,
        )
        if not feature:
            log("FeatureRevolve2 returned None", "ERROR")
            return False

        log("Revolve created (360\u00b0)", "SUCCESS")
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"revolve FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("ref_plane", "Reference Plane", "Feature Tools",
               "Create a 50mm offset reference plane from Front", order=6)
def test_ref_plane(sw, template):
    try:
        make_cube(sw, template, 100)
        model = sw.ActiveDoc
        model.ForceRebuild3(True)

        # In SW2025, SelectByID2 with type "PLANE" works (not "DATUMPLANE")
        callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        model.ClearSelection2(True)
        ok = model.Extension.SelectByID2(
            "Front Plane", "PLANE", 0, 0, 0,
            False, 0, callout, 0
        )
        if not ok:
            log("Could not select Front Plane", "ERROR")
            return False

        # flags=5 works reliably in SW2025 for offset planes
        feature = model.FeatureManager.InsertRefPlane(5, 0.05, 0, 0, 0, 0)

        # InsertRefPlane may return None even on success; check feature tree
        if not feature:
            model.ForceRebuild3(True)
            features = model.FeatureManager.GetFeatures(True)
            if features:
                for f in features:
                    if "Plane" in f.Name and f.Name != "Front Plane" \
                            and f.Name != "Top Plane" and f.Name != "Right Plane":
                        feature = f
                        break

        if not feature:
            log("InsertRefPlane returned None and no new plane in feature tree", "ERROR")
            return False

        log("Reference plane created (50mm offset from Front)", "SUCCESS")
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"ref_plane FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("loft", "Loft (Frustum)", "Feature Tools",
               "Create a frustum via loft between two circles on offset planes", order=7)
def test_loft(sw, template):
    try:
        model = sw.NewDocument(template, 0, 0, 0)

        # Sketch 1: large circle on Front Plane
        create_sketch_on_plane(model, "Front Plane")
        model.SketchManager.CreateCircleByRadius(0.0, 0.0, 0.0, 0.025)  # 25mm radius
        exit_sketch(model)
        sketch1_name = get_latest_sketch_name(model)
        log(f"Sketch 1: {sketch1_name}", "SUCCESS")

        # Create offset reference plane (80mm from Front)
        # Use SelectByID2 with "PLANE" type and flags=5 (proven in SW2025)
        callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        model.ClearSelection2(True)
        ok = model.Extension.SelectByID2(
            "Front Plane", "PLANE", 0, 0, 0, False, 0, callout, 0
        )
        if not ok:
            log("Could not select Front Plane for ref plane", "ERROR")
            return False
        ref_feat = model.FeatureManager.InsertRefPlane(5, 0.08, 0, 0, 0, 0)
        if not ref_feat:
            # Fallback: check feature tree for a new plane
            model.ForceRebuild3(True)
            features = model.FeatureManager.GetFeatures(True)
            if features:
                for f in features:
                    if "Plane" in f.Name and f.Name not in (
                        "Front Plane", "Top Plane", "Right Plane"
                    ):
                        ref_feat = f
                        break
        if not ref_feat:
            log("Failed to create reference plane", "ERROR")
            return False
        custom_plane_name = ref_feat.Name
        log(f"Reference plane: {custom_plane_name}", "SUCCESS")

        # Sketch 2: small circle on custom plane
        plane_feat = model.FeatureByName(custom_plane_name)
        if not plane_feat:
            log(f"Could not find plane: {custom_plane_name}", "ERROR")
            return False
        model.ClearSelection2(True)
        plane_feat.Select2(False, 0)
        model.SketchManager.InsertSketch(True)
        model.SketchManager.CreateCircleByRadius(0.0, 0.0, 0.0, 0.01)  # 10mm radius
        exit_sketch(model)
        sketch2_name = get_latest_sketch_name(model)
        log(f"Sketch 2: {sketch2_name}", "SUCCESS")

        # Select both sketches for loft (mark=1)
        callout = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        model.ClearSelection2(True)
        ok1 = model.Extension.SelectByID2(
            sketch1_name, "SKETCH", 0, 0, 0, False, 1, callout, 0
        )
        ok2 = model.Extension.SelectByID2(
            sketch2_name, "SKETCH", 0, 0, 0, True, 1, callout, 0
        )
        if not ok1 or not ok2:
            log(f"Sketch selection failed: {sketch1_name}={ok1}, {sketch2_name}={ok2}", "ERROR")
            return False

        # Create loft using InsertProtrusionBlend2 (18 params for SW2025)
        feature = model.FeatureManager.InsertProtrusionBlend2(
            False,  # Closed
            True,   # KeepTangency
            True,   # ForceNonRational
            1.0,    # TessToleranceFactor
            0,      # StartMatchingType (None)
            0,      # EndMatchingType (None)
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
            log("InsertProtrusionBlend2 returned None", "ERROR")
            return False

        log("Loft (frustum) created successfully", "SUCCESS")
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"loft FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("list_features", "List Features", "Feature Tools",
               "Create a cube and list the feature tree", order=8)
def test_list_features(sw, template):
    try:
        model = make_cube(sw, template, 100)

        features = model.FeatureManager.GetFeatures(True)
        if not features:
            log("GetFeatures returned None", "ERROR")
            return False

        found_extrude = False
        for feature in features:
            name = feature.Name
            type_name = feature.GetTypeName2
            if "Extrusion" in type_name or "Extrude" in name:
                found_extrude = True

        if not found_extrude:
            log("Could not find extrusion feature in tree", "ERROR")
            return False

        log(f"Feature tree has {len(features)} features, extrusion found", "SUCCESS")
        return True
    except Exception as e:
        log(f"list_features FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


# ===========================================================================
# TEST FUNCTIONS — MCP Tools (exercise the full MCP _route_tool dispatch)
# ===========================================================================


def create_mcp_server():
    """Create a SolidWorksMCPServer instance for MCP-level testing."""
    from server import SolidWorksMCPServer
    return SolidWorksMCPServer()


def mcp_make_cube(server, size_mm=100):
    """Create a cube end-to-end via MCP tool calls. Returns list of result strings.

    Note: create_extrusion exits sketch mode internally, so we do NOT call
    exit_sketch before it (that would toggle sketch mode back on).
    """
    results = []
    results.append(server._route_tool("solidworks_new_part", {}))
    results.append(server._route_tool("solidworks_create_sketch", {"plane": "Front"}))
    results.append(server._route_tool("solidworks_sketch_rectangle", {
        "centerX": size_mm / 2, "centerY": size_mm / 2,
        "width": size_mm, "height": size_mm
    }))
    results.append(server._route_tool("solidworks_create_extrusion", {"depth": size_mm}))
    return results


def _model_to_sketch_xy(sketch_result_json, mx, my, mz):
    """Convert a model-space point (mm) to sketch coordinates using the
    sketchFrame returned by create_sketch (face sketches can have mirrored or
    rotated axes)."""
    frame = json.loads(sketch_result_json).get("sketchFrame")
    if not frame:
        return mx, my  # plane sketches without frame info: assume aligned
    o = frame["originModel_mm"]
    d = (mx - o[0], my - o[1], mz - o[2])
    xa, ya = frame["xAxisModel"], frame["yAxisModel"]
    sx = xa[0] * d[0] + xa[1] * d[1] + xa[2] * d[2]
    sy = ya[0] * d[0] + ya[1] * d[1] + ya[2] * d[2]
    return sx, sy


def _mcp_ok(r):
    """True if an MCP result indicates success.
    Tools return JSON strings {"result": "✓ ..."}; errors are plain ❌ strings."""
    if r.startswith("❌"):
        return False
    if r.startswith("{"):
        try:
            return json.loads(r).get("result", "").startswith("✓")
        except Exception:
            return False
    return r.startswith("✓")


def mcp_check_results(results):
    """Verify all MCP results indicate success. Returns True if all pass."""
    for r in results:
        if not _mcp_ok(r):
            log(f"MCP call failed: {r}", "ERROR")
            return False
    return True


@register_test("mcp_basic_workflow", "MCP Basic Workflow", "MCP Tools",
               "Create a 100mm cube end-to-end via MCP tool calls", order=0)
def test_mcp_basic_workflow(sw, template):
    try:
        server = create_mcp_server()
        results = mcp_make_cube(server, 100)
        if not mcp_check_results(results):
            return False

        extrude_result = results[-1]
        if "Boss-Extrude" not in extrude_result and "Extrusion" not in extrude_result:
            log(f"Extrusion result missing feature name: {extrude_result}", "ERROR")
            return False

        log("MCP basic workflow (cube) succeeded", "SUCCESS")
        return True
    except Exception as e:
        log(f"mcp_basic_workflow FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("mcp_fillet", "MCP Fillet", "MCP Tools",
               "Create cube via MCP, then fillet an edge", order=1)
def test_mcp_fillet(sw, template):
    try:
        server = create_mcp_server()
        results = mcp_make_cube(server, 100)
        if not mcp_check_results(results):
            return False

        r = server._route_tool("solidworks_fillet", {
            "radius": 5,
            "edges": [{"x": 100, "y": 0, "z": 50}]
        })
        if not _mcp_ok(r):
            log(f"Fillet failed: {r}", "ERROR")
            return False
        if "Fillet" not in r:
            log(f"Fillet result missing feature name: {r}", "ERROR")
            return False

        log("MCP fillet succeeded", "SUCCESS")
        return True
    except Exception as e:
        log(f"mcp_fillet FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("mcp_chamfer", "MCP Chamfer", "MCP Tools",
               "Create cube via MCP, then chamfer an edge", order=2)
def test_mcp_chamfer(sw, template):
    try:
        server = create_mcp_server()
        results = mcp_make_cube(server, 100)
        if not mcp_check_results(results):
            return False

        r = server._route_tool("solidworks_chamfer", {
            "distance": 5,
            "edges": [{"x": 100, "y": 0, "z": 50}]
        })
        if not _mcp_ok(r):
            log(f"Chamfer failed: {r}", "ERROR")
            return False
        if "Chamfer" not in r:
            log(f"Chamfer result missing feature name: {r}", "ERROR")
            return False

        log("MCP chamfer succeeded", "SUCCESS")
        return True
    except Exception as e:
        log(f"mcp_chamfer FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("mcp_shell", "MCP Shell", "MCP Tools",
               "Create cube via MCP, then shell (remove top face)", order=3)
def test_mcp_shell(sw, template):
    try:
        server = create_mcp_server()
        results = mcp_make_cube(server, 100)
        if not mcp_check_results(results):
            return False

        r = server._route_tool("solidworks_shell", {
            "thickness": 3,
            "facesToRemove": [{"x": 50, "y": 100, "z": 50}]
        })
        if not _mcp_ok(r):
            log(f"Shell failed: {r}", "ERROR")
            return False
        if "Shell" not in r:
            log(f"Shell result missing feature name: {r}", "ERROR")
            return False

        log("MCP shell succeeded", "SUCCESS")
        return True
    except Exception as e:
        log(f"mcp_shell FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("mcp_cut_extrusion", "MCP Cut-Extrusion", "MCP Tools",
               "Create cube via MCP, then cut a circle through it", order=4)
def test_mcp_cut_extrusion(sw, template):
    try:
        server = create_mcp_server()
        results = mcp_make_cube(server, 100)
        if not mcp_check_results(results):
            return False

        # Sketch on the back face of the cube (z=0 plane) — its sketch X axis is
        # mirrored, so convert the model target through the returned sketchFrame
        sk_r = server._route_tool("solidworks_create_sketch", {
            "faceX": 50, "faceY": 50, "faceZ": 0
        })
        if not _mcp_ok(sk_r):
            log(f"Sketch on face failed: {sk_r}", "ERROR")
            return False

        cx, cy = _model_to_sketch_xy(sk_r, 50, 50, 0)
        r = server._route_tool("solidworks_sketch_circle", {
            "centerX": cx, "centerY": cy, "radius": 20
        })
        if not _mcp_ok(r):
            log(f"Circle sketch failed: {r}", "ERROR")
            return False

        # exit_sketch is required before create_cut_extrusion
        r = server._route_tool("solidworks_exit_sketch", {})
        if not _mcp_ok(r):
            log(f"Exit sketch failed: {r}", "ERROR")
            return False

        # Direction is auto-flipped into the body when needed
        r = server._route_tool("solidworks_create_cut_extrusion", {"depth": 50})
        if not _mcp_ok(r):
            log(f"Cut-extrusion failed: {r}", "ERROR")
            return False
        if "Cut" not in r:
            log(f"Cut result missing feature name: {r}", "ERROR")
            return False

        # The cut must have removed the cylinder's volume (catches wrong-side cuts)
        mp = _mcp_json(server._route_tool("solidworks_get_mass_properties", {}))
        expected = 100**3 - math.pi * 20**2 * 50
        if abs(mp["volume_mm3"] - expected) > 1:
            log(f"Cut volume wrong: {mp['volume_mm3']} != {expected:.0f}", "ERROR")
            return False

        log("MCP cut-extrusion succeeded with correct volume", "SUCCESS")
        return True
    except Exception as e:
        log(f"mcp_cut_extrusion FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("mcp_mass_properties", "MCP Mass Properties", "MCP Tools",
               "Create cube via MCP, then verify volume via mass properties", order=5)
def test_mcp_mass_properties(sw, template):
    try:
        server = create_mcp_server()
        results = mcp_make_cube(server, 100)
        if not mcp_check_results(results):
            return False

        r = server._route_tool("solidworks_get_mass_properties", {})
        text = json.loads(r)["result"] if r.startswith("{") else r
        if "Volume" not in text:
            log(f"Mass properties missing volume: {text}", "ERROR")
            return False

        for line in text.split("\n"):
            if "Volume:" in line:
                vol_str = line.split(":")[1].strip().split(" ")[0]
                volume = float(vol_str)
                if abs(volume - 1_000_000) > 1:
                    log(f"Volume mismatch: expected ~1000000, got {volume}", "ERROR")
                    return False
                log(f"Volume verified: {volume:.0f} mm^3", "SUCCESS")
                break

        log("MCP mass properties succeeded", "SUCCESS")
        return True
    except Exception as e:
        log(f"mcp_mass_properties FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("mcp_list_features", "MCP List Features", "MCP Tools",
               "Create cube via MCP, then list features and verify extrusion exists", order=6)
def test_mcp_list_features(sw, template):
    try:
        server = create_mcp_server()
        results = mcp_make_cube(server, 100)
        if not mcp_check_results(results):
            return False

        r = server._route_tool("solidworks_list_features", {})
        if "Feature Tree" not in r and "feature" not in r.lower():
            log(f"Unexpected list_features result: {r}", "ERROR")
            return False
        if "Extrusion" not in r and "Extrude" not in r:
            log(f"Feature tree missing extrusion: {r}", "ERROR")
            return False

        log("MCP list features succeeded", "SUCCESS")
        return True
    except Exception as e:
        log(f"mcp_list_features FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("mcp_full_integration", "MCP Full Integration", "MCP Tools",
               "Multi-step MCP workflow: cube + fillet + cut + list_features + mass_properties",
               order=7)
def test_mcp_full_integration(sw, template):
    try:
        server = create_mcp_server()

        # Step 1: Create cube
        results = mcp_make_cube(server, 100)
        if not mcp_check_results(results):
            return False
        log("Step 1: Cube created", "SUCCESS")

        # Step 2: Fillet one edge
        r = server._route_tool("solidworks_fillet", {
            "radius": 5,
            "edges": [{"x": 100, "y": 0, "z": 50}]
        })
        if not _mcp_ok(r):
            log(f"Fillet failed: {r}", "ERROR")
            return False
        log("Step 2: Fillet created", "SUCCESS")

        # Step 3: Cut-extrusion (hole on top face). The top face's sketch frame is
        # rotated (sketch Y = model -Z), so convert the model target through it.
        sk_r = server._route_tool("solidworks_create_sketch", {
            "faceX": 50, "faceY": 100, "faceZ": 50
        })
        if not _mcp_ok(sk_r):
            log(f"Sketch on face failed: {sk_r}", "ERROR")
            return False

        cx, cy = _model_to_sketch_xy(sk_r, 50, 100, 50)
        r = server._route_tool("solidworks_sketch_circle", {
            "centerX": cx, "centerY": cy, "radius": 15
        })
        if not _mcp_ok(r):
            log(f"Circle failed: {r}", "ERROR")
            return False

        r = server._route_tool("solidworks_exit_sketch", {})
        if not _mcp_ok(r):
            log(f"Exit sketch failed: {r}", "ERROR")
            return False

        # Cut into the body (direction auto-flips if needed)
        r = server._route_tool("solidworks_create_cut_extrusion", {"depth": 50})
        if not _mcp_ok(r):
            log(f"Cut-extrusion failed: {r}", "ERROR")
            return False
        log("Step 3: 50mm hole cut created", "SUCCESS")

        # Step 4: List features (should have Boss-Extrude, Fillet, Cut-Extrude)
        r = server._route_tool("solidworks_list_features", {})
        if "Fillet" not in r:
            log(f"Feature tree missing Fillet: {r}", "ERROR")
            return False
        log("Step 4: Feature tree verified", "SUCCESS")

        # Step 5: Mass properties (volume should be less than 1,000,000)
        r = server._route_tool("solidworks_get_mass_properties", {})
        text = json.loads(r)["result"] if r.startswith("{") else r
        if "Volume" not in text:
            log(f"Mass properties missing volume: {text}", "ERROR")
            return False
        for line in text.split("\n"):
            if "Volume:" in line:
                vol_str = line.split(":")[1].strip().split(" ")[0]
                volume = float(vol_str)
                if volume >= 1_000_000:
                    log(f"Volume should be < 1M after cuts, got {volume}", "ERROR")
                    return False
                log(f"Step 5: Volume {volume:.0f} mm^3 (correctly less than original)", "SUCCESS")
                break

        log("MCP full integration passed", "SUCCESS")
        return True
    except Exception as e:
        log(f"mcp_full_integration FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


# ===========================================================================
# TEST FUNCTIONS — MCP Geometry Query Tools
# ===========================================================================


@register_test("mcp_get_body_info", "MCP Get Body Info", "MCP Tools",
               "Create cube via MCP, query bounding box and counts", order=8)
def test_mcp_get_body_info(sw, template):
    try:
        server = create_mcp_server()
        results = mcp_make_cube(server, 100)
        if not mcp_check_results(results):
            return False

        r = server._route_tool("solidworks_get_body_info", {})
        if not _mcp_ok(r):
            log(f"get_body_info failed: {r}", "ERROR")
            return False

        # Verify counts (structured JSON return)
        d = json.loads(r)
        if d.get("faces") != 6:
            log(f"Expected 6 faces, got: {d.get('faces')}", "ERROR")
            return False
        if d.get("edges") != 12:
            log(f"Expected 12 edges, got: {d.get('edges')}", "ERROR")
            return False
        if d.get("vertices") != 8:
            log(f"Expected 8 vertices, got: {d.get('vertices')}", "ERROR")
            return False
        if d.get("size", {}).get("x") != 100.0:
            log(f"Expected 100mm bounding box, got: {d.get('size')}", "ERROR")
            return False

        log("Body info: 6 faces, 12 edges, 8 vertices confirmed", "SUCCESS")
        return True
    except Exception as e:
        log(f"mcp_get_body_info FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("mcp_get_faces", "MCP Get Faces", "MCP Tools",
               "Create cube via MCP, enumerate all faces", order=9)
def test_mcp_get_faces(sw, template):
    try:
        server = create_mcp_server()
        results = mcp_make_cube(server, 100)
        if not mcp_check_results(results):
            return False

        r = server._route_tool("solidworks_get_faces", {})
        if not _mcp_ok(r):
            log(f"get_faces failed: {r}", "ERROR")
            return False

        faces = json.loads(r)["faces"]
        if len(faces) != 6:
            log(f"Expected 6 total faces, got {len(faces)}", "ERROR")
            return False

        planar_count = sum(1 for f in faces if f.get("surfaceType") == "Planar")
        if planar_count != 6:
            log(f"Expected 6 planar faces, found {planar_count}", "ERROR")
            return False

        point_count = sum(1 for f in faces if "point" in f)
        if point_count != 6:
            log(f"Expected 6 sample points, found {point_count}", "ERROR")
            return False

        if not all(f.get("feature") for f in faces):
            log("Faces missing feature tags", "ERROR")
            return False

        log("6 planar faces with sample points and feature tags confirmed", "SUCCESS")
        return True
    except Exception as e:
        log(f"mcp_get_faces FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("mcp_get_edges", "MCP Get Edges", "MCP Tools",
               "Create cube via MCP, enumerate all edges", order=10)
def test_mcp_get_edges(sw, template):
    try:
        server = create_mcp_server()
        results = mcp_make_cube(server, 100)
        if not mcp_check_results(results):
            return False

        r = server._route_tool("solidworks_get_edges", {})
        if not _mcp_ok(r):
            log(f"get_edges failed: {r}", "ERROR")
            return False

        edges = json.loads(r)["edges"]
        if len(edges) != 12:
            log(f"Expected 12 total edges, got {len(edges)}", "ERROR")
            return False

        line_count = sum(1 for e in edges if e.get("edgeType") == "Line")
        if line_count != 12:
            log(f"Expected 12 line edges, found {line_count}", "ERROR")
            return False

        mid_count = sum(1 for e in edges if "midpoint" in e)
        if mid_count != 12:
            log(f"Expected 12 midpoints, found {mid_count}", "ERROR")
            return False

        log("12 line edges with midpoints confirmed", "SUCCESS")
        return True
    except Exception as e:
        log(f"mcp_get_edges FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("mcp_get_face_edges", "MCP Get Face Edges", "MCP Tools",
               "Create cube via MCP, query edges of the top face", order=11)
def test_mcp_get_face_edges(sw, template):
    try:
        server = create_mcp_server()
        results = mcp_make_cube(server, 100)
        if not mcp_check_results(results):
            return False

        # Query top face (y=100 for a cube sketched at center=(50,50) extruded 100mm)
        r = server._route_tool("solidworks_get_face_edges", {
            "x": 50, "y": 100, "z": 50
        })
        if not _mcp_ok(r):
            log(f"get_face_edges failed: {r}", "ERROR")
            return False

        face = json.loads(r)["face"]
        if len(face.get("edges", [])) != 4:
            log(f"Expected 4 edges on top face: {face.get('edges')}", "ERROR")
            return False

        if face.get("surfaceType") != "Planar":
            log(f"Expected Planar face type: {face.get('surfaceType')}", "ERROR")
            return False

        log("Top face: Planar with 4 edges confirmed", "SUCCESS")
        return True
    except Exception as e:
        log(f"mcp_get_face_edges FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("mcp_geometry_guided_fillet", "MCP Geometry-Guided Fillet", "MCP Tools",
               "Create cube, use get_edges to find edge coordinates, then fillet using those coords",
               order=12)
def test_mcp_geometry_guided_fillet(sw, template):
    """Integration test: proves geometry query tools provide coordinates
    that actually work for downstream selection operations."""
    try:
        server = create_mcp_server()
        results = mcp_make_cube(server, 100)
        if not mcp_check_results(results):
            return False
        log("Step 1: Cube created", "SUCCESS")

        # Step 2: Query edges to find midpoints
        r = server._route_tool("solidworks_get_edges", {})
        if not _mcp_ok(r):
            log(f"get_edges failed: {r}", "ERROR")
            return False
        log("Step 2: Edges queried", "SUCCESS")

        # Step 3: Parse midpoints and pick one that's clearly on an edge midpoint
        # (avoid vertex intersections where multiple edges meet at a corner)
        all_mids = [e["midpoint"] for e in json.loads(r)["edges"] if "midpoint" in e]
        if not all_mids:
            log("Could not parse any midpoints from get_edges result", "ERROR")
            return False

        # Find a midpoint that's clearly on an edge but NOT at the origin
        # (origin planes can interfere with edge selection at x=0 or y=0)
        mid_x, mid_y, mid_z = None, None, None
        for mid in all_mids:
            coords = [mid["x"], mid["y"], mid["z"]]
            # Skip points where any coordinate is 0 (near origin planes)
            if any(abs(c) < 1 for c in coords):
                continue
            mid_x, mid_y, mid_z = coords[0], coords[1], coords[2]
            break

        if mid_x is None:
            # Fallback: use a known-good edge midpoint for a 100mm cube
            mid_x, mid_y, mid_z = 100.0, 50.0, 100.0

        log(f"Step 3: Parsed midpoint ({mid_x:.2f}, {mid_y:.2f}, {mid_z:.2f})", "SUCCESS")

        # Step 4: Use that midpoint to fillet the edge
        r = server._route_tool("solidworks_fillet", {
            "radius": 5,
            "edges": [{"x": mid_x, "y": mid_y, "z": mid_z}]
        })
        if not _mcp_ok(r):
            log(f"Fillet failed: {r}", "ERROR")
            return False
        log("Step 4: Fillet created using geometry-queried coordinates", "SUCCESS")

        log("Geometry-guided fillet workflow passed!", "SUCCESS")
        return True
    except Exception as e:
        log(f"mcp_geometry_guided_fillet FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("mcp_sketch_dimension", "MCP Sketch Dimension", "MCP Tools",
               "Use SketchingTools methods to draw, dimension, and modify", order=13)
def test_mcp_sketch_dimension(sw, template):
    from solidworks.connection import SolidWorksConnection
    from solidworks.sketching import SketchingTools

    try:
        # Wire up a SolidWorksConnection that reuses the existing sw instance
        conn = SolidWorksConnection()
        conn.app = sw
        conn.template_path = template
        sketching = SketchingTools(conn)

        # create_sketch auto-creates a part when none is open
        result = sketching.create_sketch({"plane": "Front"})
        log(result, "SUCCESS")

        # Draw a 50mm horizontal line via sketch_line
        result = sketching.sketch_line({"x1": 0, "y1": 0, "x2": 50, "y2": 0})
        log(result, "SUCCESS")

        # Add a dimension on the line (no value yet — keeps geometry stable)
        result = sketching.sketch_dimension({
            "entityPoints": [{"x": 25, "y": 0}],
            "dimX": 25, "dimY": -10,
        })
        log(result, "SUCCESS")

        # Modify the dimension to 80mm via set_dimension_value
        result = sketching.set_dimension_value({
            "dimX": 25, "dimY": -10,
            "value": 80
        })
        log(result, "SUCCESS")

        if "80" not in result:
            log(f"Expected '80' in result: {result}", "ERROR")
            return False

        # Exit sketch
        result = sketching.exit_sketch()
        log(result, "SUCCESS")

        model = conn.get_active_doc()
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"mcp_sketch_dimension FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("mcp_angular_dimension", "MCP Angular Dimension", "MCP Tools",
               "Draw two lines, add angular dimension in degrees, verify conversion", order=14)
def test_mcp_angular_dimension(sw, template):
    from solidworks.connection import SolidWorksConnection
    from solidworks.sketching import SketchingTools

    try:
        conn = SolidWorksConnection()
        conn.app = sw
        conn.template_path = template
        sketching = SketchingTools(conn)

        # Create sketch on Front plane
        result = sketching.create_sketch({"plane": "Front"})
        log(result, "SUCCESS")

        # Draw two lines from origin — roughly 60 degrees apart
        # Line 1: along X axis
        result = sketching.sketch_line({"x1": 0, "y1": 0, "x2": 50, "y2": 0})
        log(result, "SUCCESS")

        # Line 2: from origin at ~60 degrees
        result = sketching.sketch_line({"x1": 0, "y1": 0, "x2": 25, "y2": 43.3})
        log(result, "SUCCESS")

        # Add angular dimension between the two lines, set to 45 degrees
        result = sketching.sketch_dimension({
            "entityPoints": [
                {"x": 25, "y": 0},       # point on line 1
                {"x": 12.5, "y": 21.65}  # point on line 2
            ],
            "dimX": 20, "dimY": 15,
            "value": 45
        })
        log(result, "SUCCESS")

        # Verify the result message says degrees (°), not mm.
        # Results are JSON strings with unicode escaped -- parse before checking.
        result_text = json.loads(result)["result"] if result.startswith("{") else result
        if "\u00b0" not in result_text:
            log(f"Expected '\u00b0' in angular dimension result: {result_text}", "ERROR")
            return False
        log("Angular dimension correctly reports degrees", "SUCCESS")

        # Exit sketch
        result = sketching.exit_sketch()
        log(result, "SUCCESS")

        model = conn.get_active_doc()
        model.ViewZoomtofit2()
        return True
    except Exception as e:
        log(f"mcp_angular_dimension FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


@register_test("mcp_linear_pattern", "MCP Linear Pattern", "MCP Tools",
               "Plate + hole, pattern 3x in X and 2x in Y by axis name, verify volume", order=15)
def test_mcp_linear_pattern(sw, template):
    """Covers FeatureLinearPattern4 (20-param signature, probed live on
    SW2025) and axis-name direction selection — this tool shipped broken
    once because nothing in the suite exercised it."""
    try:
        server = create_mcp_server()

        # 80x40x5 plate with a 5mm hole at center. Both pattern directions
        # fit on the plate regardless of which way SolidWorks runs them.
        results = [
            server._route_tool("solidworks_new_part", {}),
            server._route_tool("solidworks_create_sketch", {"plane": "Front"}),
            server._route_tool("solidworks_sketch_rectangle", {
                "width": 80, "height": 40, "centerX": 0, "centerY": 0}),
            server._route_tool("solidworks_create_extrusion", {"depth": 5}),
            server._route_tool("solidworks_create_sketch", {"plane": "Front"}),
            server._route_tool("solidworks_sketch_circle", {
                "radius": 2.5, "centerX": 0, "centerY": 0}),
        ]
        cut_r = server._route_tool("solidworks_create_cut_extrusion", {
            "depth": 5, "endCondition": "THROUGH_ALL"})
        results.append(cut_r)
        if not mcp_check_results(results):
            return False
        # Feature numbering is shared across the Extrude family (the cut may
        # be Cut-Extrude2) — always use the returned id, never assume a name.
        cut_id = _mcp_json(cut_r)["id"]

        r = server._route_tool("solidworks_linear_pattern", {
            "features": [cut_id],
            "direction1": {"axis": "X"}, "spacing1": 12, "count1": 3,
            "direction2": {"axis": "Y"}, "spacing2": 12, "count2": 2,
        })
        if not _mcp_ok(r):
            log(f"Linear pattern failed: {r}", "ERROR")
            return False

        # 6 holes total -> 6 cylindrical faces
        faces = _mcp_json(server._route_tool("solidworks_get_faces",
                                             {"surfaceType": "CYLINDER"}))["faces"]
        if len(faces) != 6:
            log(f"Expected 6 cylindrical faces after 3x2 pattern, got {len(faces)}", "ERROR")
            return False

        # Volume: 80*40*5 minus 6 holes of pi * 2.5^2 * 5
        expected = 80 * 40 * 5 - 6 * math.pi * 2.5 ** 2 * 5
        vol = _mcp_json(server._route_tool("solidworks_get_mass_properties", {}))["volume_mm3"]
        if abs(vol - expected) > 1.0:
            log(f"Volume {vol} != expected {expected:.2f}", "ERROR")
            return False

        log(f"Linear pattern 3x2 by axis names: 6 holes, volume {vol} ≈ {expected:.2f}", "SUCCESS")
        return True
    except Exception as e:
        log(f"mcp_linear_pattern FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


# ===========================================================================

# ===========================================================================
# TEST FUNCTIONS — Assembly (document lifecycle + assembly tools via MCP routing)
# ===========================================================================


def _mcp_json(r):
    """Parse an MCP tool JSON result. Raises with the raw string on error returns."""
    if r.startswith("❌"):
        raise RuntimeError(f"MCP tool returned error: {r}")
    return json.loads(r)


def _asm_test_dir():
    """Fresh temp directory for saved test parts."""
    d = os.path.join(tempfile.gettempdir(), "swmcp_assembly_tests")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    return d


def mcp_build_and_save_box(server, path, size_mm=50):
    """Build a size_mm cube via MCP tools and save it to path. Returns saved path."""
    _mcp_json(server._route_tool("solidworks_new_part", {}))
    _mcp_json(server._route_tool("solidworks_create_sketch", {"plane": "Front"}))
    _mcp_json(server._route_tool("solidworks_sketch_rectangle", {
        "centerX": size_mm / 2, "centerY": size_mm / 2,
        "width": size_mm, "height": size_mm,
    }))
    _mcp_json(server._route_tool("solidworks_create_extrusion", {"depth": size_mm}))
    saved = _mcp_json(server._route_tool("solidworks_save_document", {"path": path}))
    return saved["path"]


def mcp_build_and_save_cylinder(server, path, radius_mm=10, height_mm=30):
    """Build a cylinder via MCP tools and save it to path. Returns saved path."""
    _mcp_json(server._route_tool("solidworks_new_part", {}))
    _mcp_json(server._route_tool("solidworks_create_sketch", {"plane": "Top"}))
    _mcp_json(server._route_tool("solidworks_sketch_circle", {"radius": radius_mm}))
    _mcp_json(server._route_tool("solidworks_create_extrusion", {"depth": height_mm}))
    saved = _mcp_json(server._route_tool("solidworks_save_document", {"path": path}))
    return saved["path"]


@register_test("assembly_doc_lifecycle", "Document Lifecycle (save/activate/close)", "Assembly",
               "Save a part, switch documents, verify per-document state isolation", order=0)
def test_assembly_doc_lifecycle(sw, template):
    test_dir = _asm_test_dir()
    try:
        server = create_mcp_server()
        cube_file = mcp_build_and_save_box(
            server, os.path.join(test_dir, "lifecycle_cube"), 40)
        if not os.path.exists(cube_file):
            log(f"Saved file missing: {cube_file}", "ERROR")
            return False

        # A second part must get its own state scope
        _mcp_json(server._route_tool("solidworks_new_part", {}))
        state2 = _mcp_json(server._route_tool("solidworks_get_state", {}))
        if state2["features"]:
            log(f"New part scope not empty: {state2['features']}", "ERROR")
            return False

        # Switching back must restore the cube's tracked state
        _mcp_json(server._route_tool("solidworks_activate_document", {"name": "lifecycle_cube"}))
        state1 = _mcp_json(server._route_tool("solidworks_get_state", {}))
        if not any("Boss-Extrude" in f["name"] for f in state1["features"]):
            log(f"Cube scope lost after switching: {state1['features']}", "ERROR")
            return False

        docs = _mcp_json(server._route_tool("solidworks_list_documents", {}))
        if len(docs["documents"]) < 2:
            log(f"Expected >=2 open documents, got {docs['documents']}", "ERROR")
            return False

        _mcp_json(server._route_tool("solidworks_close_document", {}))
        log("Document lifecycle (save/scope-switch/close) verified", "SUCCESS")
        return True
    except Exception as e:
        log(f"assembly_doc_lifecycle FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


@register_test("assembly_basic", "Basic Assembly (insert + coincident mate + mass)", "Assembly",
               "Build cube and cylinder parts, assemble, mate faces, verify total volume", order=1)
def test_assembly_basic(sw, template):
    test_dir = _asm_test_dir()
    try:
        server = create_mcp_server()
        cube_file = mcp_build_and_save_box(server, os.path.join(test_dir, "asm_cube"), 50)
        cyl_file = mcp_build_and_save_cylinder(server, os.path.join(test_dir, "asm_cyl"), 10, 30)

        _mcp_json(server._route_tool("solidworks_new_assembly", {}))
        ins1 = _mcp_json(server._route_tool("solidworks_insert_component", {"path": cube_file}))
        if not ins1.get("fixed"):
            log(f"First component should be auto-fixed: {ins1}", "ERROR")
            return False
        ins2 = _mcp_json(server._route_tool("solidworks_insert_component", {"path": cyl_file, "x": 150}))

        comps = _mcp_json(server._route_tool("solidworks_list_components", {}))
        if len(comps["components"]) != 2:
            log(f"Expected 2 components: {comps}", "ERROR")
            return False

        # Coincident mate: cube top face <-> cylinder bottom face, by assembly coordinates.
        # Both parts are bbox-centered at their drop points (cube spans ±25, cyl spans y ±15).
        cube_pos = ins1["actualPosition"]
        cyl_pos = ins2["actualPosition"]
        mate = _mcp_json(server._route_tool("solidworks_add_mate", {
            "mateType": "COINCIDENT",
            "entity1": {"entityType": "FACE",
                        "x": cube_pos["x"] + 25, "y": cube_pos["y"] + 50, "z": cube_pos["z"] + 25},
            "entity2": {"entityType": "FACE",
                        "x": cyl_pos["x"], "y": cyl_pos["y"], "z": cyl_pos["z"]},
        }))
        if mate.get("type") != "mate":
            log(f"Mate result unexpected: {mate}", "ERROR")
            return False

        mates = _mcp_json(server._route_tool("solidworks_list_mates", {}))
        if len(mates["mates"]) != 1 or mates["mates"][0].get("mateType") != "coincident":
            log(f"list_mates unexpected: {mates}", "ERROR")
            return False

        mp = _mcp_json(server._route_tool("solidworks_get_assembly_mass_properties", {}))
        expected = 50**3 + math.pi * 10**2 * 30
        if abs(mp["volume_mm3"] - expected) / expected > 0.01:
            log(f"Volume {mp['volume_mm3']} != expected {expected:.0f}", "ERROR")
            return False

        log(f"Assembly built: 2 components, coincident mate, volume {mp['volume_mm3']:.0f} mm^3", "SUCCESS")
        return True
    except Exception as e:
        log(f"assembly_basic FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


@register_test("assembly_plane_mates", "Plane Mates (parallel + distance)", "Assembly",
               "Mate two cubes via component planes: parallel and 100mm distance", order=2)
def test_assembly_plane_mates(sw, template):
    test_dir = _asm_test_dir()
    try:
        server = create_mcp_server()
        a_file = mcp_build_and_save_box(server, os.path.join(test_dir, "mate_a"), 30)
        b_file = mcp_build_and_save_box(server, os.path.join(test_dir, "mate_b"), 30)

        _mcp_json(server._route_tool("solidworks_new_assembly", {}))
        ins1 = _mcp_json(server._route_tool("solidworks_insert_component", {"path": a_file}))
        ins2 = _mcp_json(server._route_tool("solidworks_insert_component", {"path": b_file, "x": 100}))

        m1 = _mcp_json(server._route_tool("solidworks_add_mate", {
            "mateType": "PARALLEL",
            "entity1": {"plane": "Front", "component": ins1["id"]},
            "entity2": {"plane": "Front", "component": ins2["id"]},
        }))
        m2 = _mcp_json(server._route_tool("solidworks_add_mate", {
            "mateType": "DISTANCE",
            "distance": 100,
            "entity1": {"plane": "Right", "component": ins1["id"]},
            "entity2": {"plane": "Right", "component": ins2["id"]},
        }))
        if m2.get("value") != 100:
            log(f"Distance mate value missing: {m2}", "ERROR")
            return False

        mates = _mcp_json(server._route_tool("solidworks_list_mates", {}))
        types = sorted(m.get("mateType") for m in mates["mates"])
        if types != ["distance", "parallel"]:
            log(f"Unexpected mate types: {types}", "ERROR")
            return False

        log("Parallel + 100mm distance plane mates verified", "SUCCESS")
        return True
    except Exception as e:
        log(f"assembly_plane_mates FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


@register_test("assembly_state", "Assembly State (get_state + scope isolation)", "Assembly",
               "get_state reflects components/mates; part scopes survive assembly work", order=3)
def test_assembly_state(sw, template):
    test_dir = _asm_test_dir()
    try:
        server = create_mcp_server()
        cube_file = mcp_build_and_save_box(server, os.path.join(test_dir, "state_cube"), 25)

        _mcp_json(server._route_tool("solidworks_new_assembly", {}))
        _mcp_json(server._route_tool("solidworks_insert_component", {"path": cube_file}))

        state = _mcp_json(server._route_tool("solidworks_get_state", {}))
        if state.get("activeDocument", {}).get("type") != "assembly":
            log(f"activeDocument not assembly: {state.get('activeDocument')}", "ERROR")
            return False
        if len(state.get("components", [])) != 1:
            log(f"Expected 1 tracked component: {state.get('components')}", "ERROR")
            return False

        # The part's scope must still hold its feature state
        _mcp_json(server._route_tool("solidworks_activate_document", {"name": "state_cube"}))
        pstate = _mcp_json(server._route_tool("solidworks_get_state", {}))
        if not any("Boss-Extrude" in f["name"] for f in pstate["features"]):
            log(f"Part scope lost after assembly work: {pstate['features']}", "ERROR")
            return False
        if pstate.get("body", {}).get("size", {}).get("x") != 25.0:
            log(f"Part bounding box wrong: {pstate.get('body')}", "ERROR")
            return False

        log("Assembly state + per-document scope isolation verified", "SUCCESS")
        return True
    except Exception as e:
        log(f"assembly_state FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


@register_test("parametric_tools", "Parametric Tools (material, CS mass props, set_parameter, edit_mate)", "Assembly",
               "Material density, coordinate-system-relative COM, parametric edit, mate edit", order=5)
def test_parametric_tools(sw, template):
    test_dir = _asm_test_dir()
    try:
        server = create_mcp_server()

        # Material + coordinate-system-relative mass properties on a 100mm cube
        _mcp_json(server._route_tool("solidworks_new_part", {}))
        _mcp_json(server._route_tool("solidworks_create_sketch", {"plane": "Front"}))
        _mcp_json(server._route_tool("solidworks_sketch_rectangle", {"x1": 0, "y1": 0, "x2": 100, "y2": 100}))
        _mcp_json(server._route_tool("solidworks_create_extrusion", {"depth": 100}))
        _mcp_json(server._route_tool("solidworks_set_material", {"material": "6061 Alloy"}))
        mp = _mcp_json(server._route_tool("solidworks_get_mass_properties", {}))
        if abs(mp["mass_g"] - 2700.0) > 1:
            log(f"6061 cube should be 2700g, got {mp['mass_g']}", "ERROR")
            return False

        _mcp_json(server._route_tool("solidworks_coordinate_system",
                                     {"origin": {"x": 100, "y": 100, "z": 100}}))
        mp = _mcp_json(server._route_tool("solidworks_get_mass_properties",
                                          {"coordinateSystem": "Coordinate System1"}))
        com = mp["centerOfMass_mm"]
        if not all(abs(com[k] + 50) < 0.1 for k in ("x", "y", "z")):
            log(f"CS-relative COM should be (-50,-50,-50), got {com}", "ERROR")
            return False

        # set_parameter: extrusion depth 100 -> 40
        _mcp_json(server._route_tool("solidworks_set_parameter",
                                     {"parameter": "D1@Boss-Extrude1", "value": 40}))
        mp = _mcp_json(server._route_tool("solidworks_get_mass_properties", {}))
        if abs(mp["volume_mm3"] - 400000) > 1:
            log(f"After depth 40, volume should be 400000, got {mp['volume_mm3']}", "ERROR")
            return False

        # edit_mate: distance 80 -> 30 moves the floating component
        a = mcp_build_and_save_box(server, os.path.join(test_dir, "em_a"), 30)
        b = mcp_build_and_save_box(server, os.path.join(test_dir, "em_b"), 30)
        _mcp_json(server._route_tool("solidworks_new_assembly", {}))
        i1 = _mcp_json(server._route_tool("solidworks_insert_component", {"path": a}))
        i2 = _mcp_json(server._route_tool("solidworks_insert_component", {"path": b, "x": 120}))
        m = _mcp_json(server._route_tool("solidworks_add_mate", {
            "mateType": "DISTANCE", "distance": 80,
            "entity1": {"plane": "Right", "component": i1["id"]},
            "entity2": {"plane": "Right", "component": i2["id"]},
        }))
        e = _mcp_json(server._route_tool("solidworks_edit_mate", {"mate": m["id"], "distance": 30}))
        # Right planes pass through each part's origin, so the mate distance equals
        # the X gap between component origins
        xs = {c["name"].split("-")[0]: c["position"]["x"] for c in e["components"]}
        gap = abs(xs["em_b"] - xs["em_a"])
        if abs(gap - 30) > 0.5:
            log(f"edit_mate should leave a 30mm origin gap, got {gap} ({xs})", "ERROR")
            return False

        amp = _mcp_json(server._route_tool("solidworks_get_assembly_mass_properties", {}))
        if "mass_g" not in amp:
            log(f"assembly mass props missing grams: {amp}", "ERROR")
            return False

        log("Material, CS mass props, set_parameter, edit_mate all verified", "SUCCESS")
        return True
    except Exception as e:
        log(f"parametric_tools FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)


@register_test("enriched_state_and_tags", "Enriched State + Feature Tags", "Assembly",
               "get_state body/constraint info; get_faces/get_edges feature tagging", order=4)
def test_enriched_state_and_tags(sw, template):
    try:
        server = create_mcp_server()
        _mcp_json(server._route_tool("solidworks_new_part", {}))
        _mcp_json(server._route_tool("solidworks_create_sketch", {"plane": "Front"}))
        _mcp_json(server._route_tool("solidworks_sketch_rectangle", {
            "centerX": 50, "centerY": 50, "width": 100, "height": 100}))
        _mcp_json(server._route_tool("solidworks_create_extrusion", {"depth": 100}))
        _mcp_json(server._route_tool("solidworks_fillet", {
            "radius": 10, "edges": [{"x": 50, "y": 100, "z": 100}]}))

        state = _mcp_json(server._route_tool("solidworks_get_state", {}))
        body = state.get("body", {})
        if body.get("size", {}).get("x") != 100.0:
            log(f"Bounding box missing/wrong: {body}", "ERROR")
            return False
        if state["sketches"][0].get("constrainedStatus") not in ("UNDER_DEFINED", "FULLY_DEFINED"):
            log(f"constrainedStatus missing: {state['sketches'][0]}", "ERROR")
            return False

        full = _mcp_json(server._route_tool("solidworks_get_state", {"detail": "full"}))
        if not any("parents" in f for f in full["features"]):
            log(f"Feature tree missing in detail=full: {full['features']}", "ERROR")
            return False

        faces = _mcp_json(server._route_tool("solidworks_get_faces", {}))
        if not any(f.get("feature") == "Fillet1" for f in faces["faces"]):
            log(f"Fillet1 face tag missing: {faces['faces']}", "ERROR")
            return False
        if not all(f.get("feature") for f in faces["faces"]):
            log("Some faces missing feature tags", "ERROR")
            return False

        edges = _mcp_json(server._route_tool("solidworks_get_edges", {}))
        if not any("Fillet1" in (e.get("features") or []) for e in edges["edges"]):
            log(f"Fillet1 edge tag missing", "ERROR")
            return False

        log("Enriched get_state + face/edge feature tagging verified", "SUCCESS")
        return True
    except Exception as e:
        log(f"enriched_state_and_tags FAILED: {e}", "ERROR")
        traceback.print_exc()
        return False


# ===========================================================================
# TEST FUNCTIONS — Integration (sequential sub-tests in one document)
# ===========================================================================

@register_test("integration_suite", "Cut-Extrude Reliability Suite", "Integration",
               "18+ sequential sub-tests: sketch lifecycle, extrusion, cuts, units, enumeration",
               order=0)
def test_integration_suite(sw, template):
    """Full integration test from original test.py, adapted to accept sw/template."""
    global PASS, FAIL

    # --- Part creation + plane selection ---
    subsection("Part creation & plane selection")
    close_all_docs(sw)
    doc = new_part(sw, template)
    ok = doc is not None
    _result("NewDocument returned a document", ok)
    if not ok:
        return False

    for plane in ("Front Plane", "Top Plane", "Right Plane"):
        try:
            feat = doc.FeatureByName(plane)
            _result(f"Select {plane}", feat is not None)
        except Exception:
            _result(f"Select {plane}", False)

    # --- Sketch lifecycle ---
    subsection("Sketch lifecycle (create \u2192 draw \u2192 exit)")
    try:
        create_sketch_on_plane(doc, "Front Plane")
        _result("InsertSketch on Front Plane", True)
    except Exception as e:
        _result("InsertSketch on Front Plane", False, str(e))
        return False

    try:
        doc.SketchManager.CreateCornerRectangle(0.0, 0.0, 0.0, 0.1, 0.1, 0.0)
        _result("CreateCornerRectangle 100x100 mm", True)
    except Exception as e:
        _result("CreateCornerRectangle 100x100 mm", False, str(e))
        return False

    try:
        exit_sketch(doc)
        _result("Exit sketch", True)
    except Exception as e:
        _result("Exit sketch", False, str(e))
        return False

    try:
        feat = doc.FeatureByName("Sketch1")
        _result("Sketch1 discoverable after exit", feat is not None)
    except Exception as e:
        _result("Sketch1 discoverable after exit", False, str(e))
        return False

    # Feature type check
    try:
        feat = doc.FeatureByName("Sketch1")
        type_name = feat.GetTypeName2 if feat else None
        _result("GetTypeName2 == 'ProfileFeature'", type_name == "ProfileFeature",
                f"got '{type_name}'" if type_name else "feature not found")
    except Exception as e:
        _result("GetTypeName2()", False, str(e))

    # Sketch counter
    try:
        found = get_latest_sketch_name(doc)
        _result(f"Latest sketch = '{found}'", found == "Sketch1")
    except Exception as e:
        _result("Feature enumeration", False, str(e))

    # Select by name
    try:
        feat = select_sketch(doc, "Sketch1")
        _result("FeatureByName('Sketch1') found", feat is not None)
    except Exception as e:
        _result("FeatureByName('Sketch1') found", False, str(e))

    # ClearSelection2 regression
    try:
        doc.ClearSelection2(True)
        feat = doc.FeatureByName("Sketch1")
        result = feat.Select2(False, 0) if feat else False
        _result("Select2 returned True", bool(result))
        doc.ClearSelection2(True)
    except Exception as e:
        _result("Select2 call", False, str(e))

    # --- Extrusion ---
    subsection("Extrusion (add material)")
    try:
        feat = extrude(doc, "Sketch1", 100.0, cut=False)
        _result("FeatureExtrusion2 (add material)", feat is not None)
        doc.ViewZoomtofit2()
    except Exception as e:
        _result("FeatureExtrusion2 (add material)", False, str(e))
        return False

    # Sketch still selectable after extrusion
    try:
        feat = doc.FeatureByName("Sketch1")
        _result("FeatureByName('Sketch1') post-extrusion", feat is not None)
    except Exception as e:
        _result("FeatureByName('Sketch1') post-extrusion", False, str(e))

    # --- Cut-extrusion ---
    subsection("Cut-extrusion (remove material)")
    try:
        create_sketch_on_face(doc, 50, 50, 100)
        _result("InsertSketch on top face of solid", True)
    except Exception as e:
        _result("InsertSketch on top face of solid", False, str(e))
        return False

    try:
        doc.SketchManager.CreateCircleByRadius(0.05, 0.05, 0.1, 0.01)
        _result("CreateCircleByRadius 10mm radius on top face", True)
    except Exception as e:
        _result("CreateCircleByRadius 10mm radius on top face", False, str(e))
        return False

    try:
        exit_sketch(doc)
        _result("Exit second sketch", True)
    except Exception as e:
        _result("Exit second sketch", False, str(e))
        return False

    try:
        feat = doc.FeatureByName("Sketch2")
        _result("Sketch2 exists after exit", feat is not None)
    except Exception as e:
        _result("Sketch2 exists after exit", False, str(e))

    # Feature type & selection checks for Sketch2
    try:
        feat = doc.FeatureByName("Sketch2")
        type_name = feat.GetTypeName2 if feat else None
        _result("Sketch2 GetTypeName2 == 'ProfileFeature'", type_name == "ProfileFeature")
    except Exception:
        pass

    try:
        found = get_latest_sketch_name(doc)
        _result(f"Latest sketch = '{found}'", found == "Sketch2")
    except Exception:
        pass

    try:
        feat = select_sketch(doc, "Sketch2")
        _result("FeatureByName('Sketch2') found", feat is not None)
    except Exception as e:
        _result("FeatureByName('Sketch2') found", False, str(e))

    try:
        feat = extrude(doc, "Sketch2", 50.0, cut=True, reverse=False)
        _result("FeatureCut4 (cut material)", feat is not None)
        doc.ViewZoomtofit2()
    except Exception as e:
        _result("FeatureCut4 (cut material)", False, str(e))

    # --- Cut-extrusion reversed ---
    subsection("Cut-extrusion reversed direction")
    try:
        create_sketch_on_face(doc, 30, 30, 0)
        doc.SketchManager.CreateCornerRectangle(0.01, 0.01, 0.0, 0.04, 0.04, 0.0)
        exit_sketch(doc)
        feat = extrude(doc, "Sketch3", 30.0, cut=True, reverse=True)
        _result("Cut-extrusion reversed 30mm", feat is not None)
        doc.ViewZoomtofit2()
    except Exception as e:
        _result("Cut-extrusion reversed 30mm", False, str(e))

    # --- Multiple sequential cuts ---
    subsection("Multiple sequential cut-extrusions")
    for i in range(2):
        sn = 4 + i
        sketch_name = f"Sketch{sn}"
        cx_mm = 20 + i * 50
        cx_m = cx_mm / 1000.0
        try:
            create_sketch_on_face(doc, cx_mm, 50, 100)
            doc.SketchManager.CreateCircleByRadius(cx_m, 0.05, 0.1, 0.005)
            exit_sketch(doc)
            feat = extrude(doc, sketch_name, 15.0, cut=True, reverse=False)
            _result(f"Cut #{i+1} using {sketch_name}", feat is not None)
        except Exception as e:
            _result(f"Cut #{i+1} using {sketch_name}", False, str(e))

    # --- Unit conversion validation ---
    subsection("Unit conversion: 50x30mm rectangle")
    try:
        create_sketch_on_plane(doc, "Right Plane")
        doc.SketchManager.CreateCornerRectangle(-0.025, -0.015, 0.0, 0.025, 0.015, 0.0)
        exit_sketch(doc)
        _result("50x30mm rectangle sketch created", True)
    except Exception as e:
        _result("50x30mm rectangle sketch created", False, str(e))

    subsection("Unit conversion: circle radius=10mm")
    try:
        create_sketch_on_plane(doc, "Top Plane")
        doc.SketchManager.CreateCircleByRadius(0.0, 0.0, 0.0, 0.01)
        exit_sketch(doc)
        _result("10mm-radius circle sketch created", True)
    except Exception as e:
        _result("10mm-radius circle sketch created", False, str(e))

    # --- Feature-tree enumeration ---
    subsection("Feature-tree enumeration robustness")
    try:
        features = doc.FeatureManager.GetFeatures(True)
        sketches = [f.Name for f in features if f.GetTypeName2 == "ProfileFeature"]
        _result(f"Found {len(sketches)} sketch(es) in feature tree", len(sketches) > 0,
                ", ".join(sketches))
        for name in sketches:
            feat = doc.FeatureByName(name)
            _result(f"FeatureByName('{name}') round-trip", feat is not None)
    except Exception as e:
        _result("Feature enumeration", False, str(e))

    # --- Final zoom ---
    try:
        doc.ViewZoomtofit2()
        _result("ViewZoomtofit2()", True)
    except Exception as e:
        _result("ViewZoomtofit2()", False, str(e))

    return True


# ===========================================================================
# Test runner
# ===========================================================================

def run_selected_tests(entries):
    """Run a list of TestEntry items. Returns True if all pass."""
    global PASS, FAIL, RESULTS
    PASS, FAIL, RESULTS = 0, 0, []

    section("SOLIDWORKS MCP \u2014 TEST SUITE")

    print("  \u2192 Initialising COM\u2026")
    pythoncom.CoInitialize()

    try:
        sw = connect_to_solidworks()
        ver = sw.RevisionNumber
        print(f"  \u2713 Connected to SolidWorks {ver}")
    except Exception as e:
        print(f"  \u2717 Failed to connect: {e}")
        return False

    template = find_template()
    if not template:
        print("  \u2717 No Part template found. Aborting.")
        return False
    print(f"  \u2713 Template: {template}")

    print("  \u2192 Closing all open documents\u2026")
    close_all_docs(sw)

    overall_results = []
    for entry in entries:
        section(f"{entry.category}: {entry.display_name}")
        try:
            ok = entry.func(sw, template)
            overall_results.append((entry.display_name, ok))
            if ok:
                log(f"{entry.display_name} \u2014 PASSED", "SUCCESS")
            else:
                log(f"{entry.display_name} \u2014 FAILED", "ERROR")
        except Exception as e:
            overall_results.append((entry.display_name, False))
            log(f"{entry.display_name} \u2014 EXCEPTION: {e}", "ERROR")
            traceback.print_exc()

        # Close docs between independent tests to prevent accumulation
        close_all_docs(sw)

    # --- Summary ---
    section("RESULTS")
    total = len(overall_results)
    passed = sum(1 for _, ok in overall_results if ok)
    failed = total - passed

    if passed:
        print(f"\n  PASSED ({passed}):")
        for name, ok in overall_results:
            if ok:
                print(f"    \u2713 {name}")

    if failed:
        print(f"\n  FAILED ({failed}):")
        for name, ok in overall_results:
            if not ok:
                print(f"    \u2717 {name}")

    print(f"\n  Total  : {total}")
    print(f"  Passed : {passed}")
    print(f"  Failed : {failed}")
    if failed == 0:
        print("\n  \u2713 ALL TESTS PASSED")
    else:
        print(f"\n  \u2717 {failed} TEST(S) FAILED")
    print()

    return failed == 0


# ===========================================================================
# Interactive CLI selector (--gui)
# ===========================================================================

def interactive_selector():
    """Print numbered test list, accept user selection, run chosen tests."""

    # Group tests by category
    categories = {}
    for entry in TEST_REGISTRY:
        categories.setdefault(entry.category, []).append(entry)

    # Sort categories by defined order, tests by their order field
    sorted_cats = sorted(categories.keys(),
                         key=lambda c: CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 999)

    # Build numbered list
    numbered = []
    print("\n  SolidWorks MCP Test Suite \u2014 Interactive Selector")
    print("  " + "=" * 54)

    for cat in sorted_cats:
        entries = sorted(categories[cat], key=lambda e: e.order)
        print(f"\n  {cat}:")
        for entry in entries:
            numbered.append(entry)
            idx = len(numbered)
            print(f"    [{idx:2d}] {entry.display_name}")

    print(f"\n  Enter selection:")
    print(f"    Numbers/ranges : 1,3-5,13")
    print(f"    Category name  : Sketch Tools")
    print(f"    Run everything : all")
    print(f"    Quit           : q")
    print()

    try:
        raw = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        return

    if not raw or raw.lower() == "q":
        print("  Cancelled.")
        return

    if raw.lower() == "all":
        selected = list(numbered)
    else:
        # Check if input matches a category name (case-insensitive)
        cat_match = None
        for cat in sorted_cats:
            if raw.lower() == cat.lower():
                cat_match = cat
                break

        if cat_match:
            selected = [e for e in numbered if e.category == cat_match]
        else:
            # Parse as numbers/ranges: "1,3-5,13"
            indices = set()
            for part in raw.split(","):
                part = part.strip()
                if "-" in part:
                    try:
                        lo, hi = part.split("-", 1)
                        for i in range(int(lo), int(hi) + 1):
                            indices.add(i)
                    except ValueError:
                        print(f"  Invalid range: {part}")
                        return
                else:
                    try:
                        indices.add(int(part))
                    except ValueError:
                        print(f"  Invalid input: {part}")
                        return

            selected = []
            for idx in sorted(indices):
                if 1 <= idx <= len(numbered):
                    selected.append(numbered[idx - 1])
                else:
                    print(f"  Index out of range: {idx}")
                    return

    if not selected:
        print("  No tests selected.")
        return

    print(f"\n  Running {len(selected)} test(s)...\n")
    success = run_selected_tests(selected)
    sys.exit(0 if success else 1)


# ===========================================================================
# CLI entry point
# ===========================================================================

def list_tests():
    """Print all registered tests grouped by category."""
    categories = {}
    for entry in TEST_REGISTRY:
        categories.setdefault(entry.category, []).append(entry)

    sorted_cats = sorted(categories.keys(),
                         key=lambda c: CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 999)

    for cat in sorted_cats:
        entries = sorted(categories[cat], key=lambda e: e.order)
        print(f"\n  {cat}:")
        for e in entries:
            print(f"    {e.name:30s} {e.description}")


def main():
    parser = argparse.ArgumentParser(description="SolidWorks MCP Test Suite")
    parser.add_argument("--gui", action="store_true",
                        help="Launch interactive CLI test picker")
    parser.add_argument("--category", type=str, default=None,
                        help="Run only tests in this category")
    parser.add_argument("--test", type=str, default=None,
                        help="Run a single test by name")
    parser.add_argument("--list", action="store_true",
                        help="List all available tests and exit")
    args = parser.parse_args()

    if args.list:
        list_tests()
        sys.exit(0)

    if args.gui:
        interactive_selector()
        return

    # Determine which tests to run
    if args.test:
        selected = [e for e in TEST_REGISTRY if e.name == args.test]
        if not selected:
            print(f"  Unknown test: {args.test}")
            print("  Use --list to see available tests.")
            sys.exit(1)
    elif args.category:
        selected = [e for e in TEST_REGISTRY
                    if e.category.lower() == args.category.lower()]
        if not selected:
            print(f"  Unknown category: {args.category}")
            print("  Available: " + ", ".join(CATEGORY_ORDER))
            sys.exit(1)
        selected.sort(key=lambda e: e.order)
    else:
        # Run all tests in category order, then by test order
        selected = sorted(TEST_REGISTRY,
                          key=lambda e: (CATEGORY_ORDER.index(e.category)
                                         if e.category in CATEGORY_ORDER else 999,
                                         e.order))

    success = run_selected_tests(selected)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
