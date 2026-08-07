"""
SolidWorks Document Manager Tools
Save, open, activate, close, and list documents. Required for assembly work:
a part must be saved to disk (and open in memory) before it can be inserted
into an assembly with AddComponent5.

COM notes (verified via live probe, SW2025):
  - Save uses IModelDocExtension.SaveAs with options=1 (swSaveAsOptions_Silent),
    which is a TRUE Save As: the open document rebinds to the new path and its
    title changes. Do NOT use options=2 (swSaveAsOptions_Copy) — it writes a
    detached copy and leaves the session document unsaved/untitled.
  - The SAME SaveAs call exports neutral formats when the path carries a
    translator extension (.STEP, .IGS, .X_T, ...). Verified: the session
    document does NOT rebind on a neutral export — the title is unchanged —
    so an export must not touch the tracker's document scope.
  - OpenDoc6 / ActivateDoc3 need VARIANT byref args for errors — handled in
    connection.py.
  - OpenDoc6 CANNOT open neutral formats: on a STEP file it fails with
    swFileLoadError_e 2097152 (swFileRequiresRepairError), which is a
    misleading error — the file is fine, the API is simply wrong. Neutral
    import goes through ISldWorks::LoadFile4(path, "r", importData, err).
  - Document titles may or may not include the file extension depending on
    Windows Explorer settings; the state tracker normalizes scope keys.

Feature recognition (FeatureWorks):
  - Binaries ship with SOLIDWORKS at fworks\\fworks.dll but the add-in is not
    loaded by default. LoadAddIn(dll) then GetAddInObject(
    "FeatureWorks.FeatureWorksApp") returns IFeatureWorksApp. Requires
    SOLIDWORKS Professional/Premium.
  - Recognition needs a DUMB solid, so 3D Interconnect
    (swMultiCAD_Enable3DInterconnect = 691) must be OFF during import.
    With it ON the import lands as an associative "<file>.STEP<1>" [MBimport]
    feature that cannot be recognised.
"""

import json
import logging
from pathlib import Path
import pythoncom
import win32com.client
from mcp.types import Tool
from .com_utils import com_prop

logger = logging.getLogger(__name__)

# swDocumentTypes_e
DOC_TYPE_PART = 1
DOC_TYPE_ASSEMBLY = 2
DOC_TYPE_DRAWING = 3

_EXT_TO_TYPE = {
    ".sldprt": DOC_TYPE_PART,
    ".sldasm": DOC_TYPE_ASSEMBLY,
    ".slddrw": DOC_TYPE_DRAWING,
}

_TYPE_TO_EXT = {
    DOC_TYPE_PART: ".SLDPRT",
    DOC_TYPE_ASSEMBLY: ".SLDASM",
    DOC_TYPE_DRAWING: ".SLDDRW",
}

_TYPE_TO_NAME = {
    DOC_TYPE_PART: "part",
    DOC_TYPE_ASSEMBLY: "assembly",
    DOC_TYPE_DRAWING: "drawing",
}

# Neutral CAD formats. SaveAs exports to these off the extension alone;
# LoadFile4 imports them. Keep the two lists separate — SolidWorks can write
# some formats it cannot read back.
_EXPORT_EXT = {
    ".step", ".stp", ".iges", ".igs", ".x_t", ".x_b", ".sat",
    ".stl", ".3mf", ".obj", ".ply", ".wrl",
}
_IMPORT_EXT = {
    ".step", ".stp", ".iges", ".igs", ".x_t", ".x_b", ".sat", ".stl", ".3mf",
}

# swUserPreferenceToggle_e — values read from swconst.tlb and confirmed live
PREF_3D_INTERCONNECT = 691   # swMultiCAD_Enable3DInterconnect
PREF_DIAG_NEUTRAL = 690      # swImportNeutralRunDiagnostics
PREF_DIAG_AUTO = 291         # swImportAutoRunImportDiagnostics

# FeatureWorks
FWORKS_DLL = r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\fworks\fworks.dll"
FWORKS_PROGID = "FeatureWorks.FeatureWorksApp"

# Automatic-recognition feature types, from FWorks.tlb. fwVolume is what lets
# the recogniser find the BASE feature — without it a simple prismatic part
# recognises nothing (measured: plate with hole+fillet returned 0 features on
# mask 61, 3 features on mask 63).
FW_TYPES = {
    "EXTRUDE": 1, "VOLUME": 2, "REVOLVE": 4, "HOLES": 8,
    "CHAMFER_FILLET": 16, "RIBS": 32,
    "BASE_FLANGE": 64, "SKETCHED_BEND": 128,
    "EDGE_FLANGE": 256, "HEM_FLANGE": 512,
}
FW_DEFAULT_TYPES = ["EXTRUDE", "VOLUME", "REVOLVE", "HOLES", "CHAMFER_FILLET", "RIBS"]
# CreateFeatures options
FW_ADD_CONSTRAINTS = 1
FW_ALLOW_FAIL = 2

# Default directory for documents saved with a bare filename
WORKSPACE_DIR = Path(__file__).parent.parent / "workspace"


def _doc_type(doc) -> int:
    """Get the swDocumentTypes_e of a document (late-bound property)."""
    return int(com_prop(doc, "GetType"))


class DocumentManagerTools:
    """Document lifecycle tools: save, open, activate, close, list."""

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
                name="solidworks_save_document",
                description="Save the active document to disk. Required before a part can be inserted into an assembly. A bare filename (e.g. 'bracket') is saved into the project workspace directory; an absolute path is used as-is. The correct extension (.SLDPRT/.SLDASM) is added automatically based on document type. Giving a neutral-format extension instead (.STEP, .STP, .IGS, .X_T, .SAT, .STL, .3MF) EXPORTS to that format — the SolidWorks document stays open and unchanged, so you can keep modelling after an export.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Filename or absolute path to save to (extension optional for native saves; give .STEP/.STP/.IGS/.X_T/.SAT/.STL to export)"
                        }
                    },
                    "required": ["path"]
                }
            ),
            Tool(
                name="solidworks_open_document",
                description="Open a part, assembly, or drawing document from disk (silently, no dialogs). The opened document becomes active. Neutral CAD files (.STEP/.STP/.IGS/.X_T/.SAT/.STL) are routed to the importer automatically — see solidworks_import_file for the import options.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the .SLDPRT/.SLDASM/.SLDDRW file, or a neutral CAD file to import"
                        }
                    },
                    "required": ["path"]
                }
            ),
            Tool(
                name="solidworks_import_file",
                description="Import a neutral CAD file (STEP/IGES/Parasolid/ACIS/STL) as a new part. By default the file lands as a single dumb solid body ('Imported1') with no feature history — geometry queries, fillets, cuts and direct edits all work on it, but there are no parametric dimensions to drive. Set recognizeFeatures=true to run FeatureWorks afterwards and rebuild a real feature tree. Import takes a few seconds for small parts and ~10s for large ones.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the .STEP/.STP/.IGS/.IGES/.X_T/.X_B/.SAT/.STL file"
                        },
                        "recognizeFeatures": {
                            "type": "boolean",
                            "description": "Run FeatureWorks feature recognition after import (default false). Adds ~1-2 minutes on a complex part."
                        },
                        "linked": {
                            "type": "boolean",
                            "description": "Import via 3D Interconnect as a LINKED, associative body that updates when the source file changes (default false). Linked bodies cannot be feature-recognized or parametrically edited."
                        }
                    },
                    "required": ["path"]
                }
            ),
            Tool(
                name="solidworks_recognize_features",
                description="Run FeatureWorks feature recognition on the active part, converting an imported dumb solid into a parametric feature tree (extrudes, hole-wizard holes, fillets, chamfers, revolves). The recovered features carry drivable dimensions usable with set_parameter (e.g. 'D1@Fillet1'). NOTE: recognized SKETCHES come back constrained but NOT dimensioned, so sketch profiles cannot be driven numerically — change the shape of a recognized cut by editing sketch geometry or by direct face editing instead. Requires SOLIDWORKS Professional/Premium.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "featureTypes": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["EXTRUDE", "VOLUME", "REVOLVE", "HOLES",
                                         "CHAMFER_FILLET", "RIBS", "BASE_FLANGE",
                                         "SKETCHED_BEND", "EDGE_FLANGE", "HEM_FLANGE"]
                            },
                            "description": "Feature types to recognize (default: EXTRUDE, VOLUME, REVOLVE, HOLES, CHAMFER_FILLET, RIBS). Keep VOLUME in the list — it is what finds the base feature; dropping it can make recognition return nothing on simple prismatic parts."
                        },
                        "addConstraints": {
                            "type": "boolean",
                            "description": "Add sketch constraints to recognized profiles (default true)"
                        }
                    }
                }
            ),
            Tool(
                name="solidworks_activate_document",
                description="Switch the active document to another open document by name/title (e.g. 'Part1', 'bracket', 'Assem1'). Subsequent tool calls operate on the activated document.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Title of the open document to activate (extension optional)"
                        }
                    },
                    "required": ["name"]
                }
            ),
            Tool(
                name="solidworks_close_document",
                description="Close an open document WITHOUT saving (unsaved changes are discarded). If no name is given, closes the active document.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Title of the document to close (default: active document)"
                        }
                    }
                }
            ),
            Tool(
                name="solidworks_capture_views",
                description="Export standard-view screenshots (PNG) of the active document. Each view is oriented (ShowNamedView2), zoomed to fit, and saved. Returns the file paths.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "views": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["ISOMETRIC", "TRIMETRIC", "DIMETRIC", "FRONT",
                                         "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM"]
                            },
                            "description": "Views to capture (default: ISOMETRIC, FRONT, TOP)"
                        },
                        "outputDir": {
                            "type": "string",
                            "description": "Directory for the PNGs (default: workspace/screenshots)"
                        },
                        "prefix": {
                            "type": "string",
                            "description": "Filename prefix (default: the document title)"
                        }
                    }
                }
            ),
            Tool(
                name="solidworks_list_documents",
                description="List all open documents with their titles, types, file paths, and which one is active.",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
        ]

    def execute(self, tool_name: str, args: dict) -> str:
        self.connection.ensure_connection()
        dispatch = {
            "solidworks_save_document": lambda: self.save_document(args),
            "solidworks_open_document": lambda: self.open_document(args),
            "solidworks_import_file": lambda: self.import_file(args),
            "solidworks_recognize_features": lambda: self.recognize_features(args),
            "solidworks_activate_document": lambda: self.activate_document(args),
            "solidworks_close_document": lambda: self.close_document(args),
            "solidworks_capture_views": lambda: self.capture_views(args),
            "solidworks_list_documents": lambda: self.list_documents(),
        }
        handler = dispatch.get(tool_name)
        if not handler:
            raise Exception(f"Unknown document tool: {tool_name}")
        return handler()

    # --- Tool implementations ---

    def save_document(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document to save")

        doc_type = _doc_type(doc)
        ext = _TYPE_TO_EXT.get(doc_type, ".SLDPRT")

        raw = args["path"].strip()
        path = Path(raw)
        suffix = path.suffix.lower()
        # A neutral extension means "export", not "save as" — the translator
        # writes the file and leaves the session document alone.
        exporting = suffix in _EXPORT_EXT
        if not exporting and suffix not in _EXT_TO_TYPE:
            path = path.with_name(path.name + ext)
        if not path.is_absolute():
            WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
            path = WORKSPACE_DIR / path
        path.parent.mkdir(parents=True, exist_ok=True)

        if exporting:
            return self._export_document(doc, path, doc_type)

        old_title = doc.GetTitle

        # IModelDocExtension.SaveAs — a TRUE Save As that rebinds the open
        # document to the new path/title. options=1 is swSaveAsOptions_Silent
        # (2 would be swSaveAsOptions_Copy, which saves a detached copy and
        # leaves the session document unsaved — verified live).
        errs = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warns = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        export_data = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        ok = doc.Extension.SaveAs(str(path), 0, 1, export_data, errs, warns)
        if not ok or not path.exists():
            raise Exception(
                f"Save failed for {path} (errors={errs.value}, warnings={warns.value})"
            )

        new_title = doc.GetTitle
        if self.tracker:
            self.tracker.rename_document(old_title, new_title)

        logger.info(f"Saved document: {path}")
        return self._json_result(
            f"✓ Saved {_TYPE_TO_NAME.get(doc_type, 'document')} to {path}",
            path=str(path),
            title=new_title,
            type=_TYPE_TO_NAME.get(doc_type, "document"),
        )

    def _export_document(self, doc, path: Path, doc_type: int) -> str:
        """Export the active document to a neutral format. Unlike a native
        Save As this does NOT rebind the session document (verified live: the
        title is unchanged afterwards), so the tracker scope is left alone."""
        if path.exists():
            path.unlink()

        title_before = str(doc.GetTitle)
        errs = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warns = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        export_data = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        ok = doc.Extension.SaveAs(str(path), 0, 1, export_data, errs, warns)
        if not ok or not path.exists():
            raise Exception(
                f"Export failed for {path} (errors={errs.value}, "
                f"warnings={warns.value}). Check that the format is licensed "
                f"and the extension is spelled correctly."
            )

        title_after = str(doc.GetTitle)
        if title_after != title_before and self.tracker:
            # Not expected for neutral formats, but if a translator ever does
            # rebind the document, keep the tracker scope consistent with it.
            logger.warning(
                f"Export rebound the session document {title_before!r} -> "
                f"{title_after!r}; re-keying tracker scope"
            )
            self.tracker.rename_document(title_before, title_after)

        size = path.stat().st_size
        logger.info(f"Exported {title_before} to {path} ({size} bytes)")
        return self._json_result(
            f"✓ Exported {_TYPE_TO_NAME.get(doc_type, 'document')} to {path}",
            path=str(path),
            format=path.suffix.lstrip(".").upper(),
            bytes=size,
            title=title_after,
            documentStillOpen=True,
        )

    def open_document(self, args: dict) -> str:
        raw = args["path"].strip()
        path = Path(raw)
        if not path.is_absolute():
            candidate = WORKSPACE_DIR / path
            if candidate.exists():
                path = candidate
        if not path.exists():
            raise Exception(f"File not found: {path}")

        # Neutral formats cannot go through OpenDoc6 — route them to LoadFile4.
        if path.suffix.lower() in _IMPORT_EXT:
            return self.import_file({**args, "path": str(path)})

        doc_type = _EXT_TO_TYPE.get(path.suffix.lower())
        if doc_type is None:
            raise Exception(f"Unsupported file type: {path.suffix}")

        doc = self.connection.open_document(str(path), doc_type)
        title = doc.GetTitle
        if self.tracker:
            self.tracker.activate_document(title, _TYPE_TO_NAME.get(doc_type, "unknown"))

        logger.info(f"Opened document: {path}")
        return self._json_result(
            f"✓ Opened {_TYPE_TO_NAME.get(doc_type, 'document')}: {title}",
            title=title,
            path=str(path),
            type=_TYPE_TO_NAME.get(doc_type, "document"),
        )

    # --- neutral-format import + feature recognition ---

    def _set_prefs(self, prefs: dict) -> dict:
        """Set app-level user preference toggles, returning the previous
        values so the caller can restore them. These are global SolidWorks
        settings — leaving them changed would surprise the user."""
        sw = self.connection.app
        previous = {}
        for pref, value in prefs.items():
            try:
                previous[pref] = sw.GetUserPreferenceToggle(pref)
                sw.SetUserPreferenceToggle(pref, value)
            except Exception as e:
                logger.warning(f"Could not set user preference {pref}: {e}")
        return previous

    def _restore_prefs(self, previous: dict):
        sw = self.connection.app
        for pref, value in previous.items():
            try:
                sw.SetUserPreferenceToggle(pref, value)
            except Exception as e:
                logger.warning(f"Could not restore user preference {pref}: {e}")

    def import_file(self, args: dict) -> str:
        raw = args["path"].strip()
        path = Path(raw)
        if not path.is_absolute():
            candidate = WORKSPACE_DIR / path
            if candidate.exists():
                path = candidate
        if not path.exists():
            raise Exception(f"File not found: {path}")
        if path.suffix.lower() not in _IMPORT_EXT:
            raise Exception(
                f"Not an importable neutral format: {path.suffix}. "
                f"Supported: {', '.join(sorted(_IMPORT_EXT))}"
            )

        linked = bool(args.get("linked", False))
        recognize = bool(args.get("recognizeFeatures", False))
        if linked and recognize:
            raise Exception(
                "recognizeFeatures cannot be combined with linked=true — a 3D "
                "Interconnect linked body has no editable feature history to "
                "recognize. Import with linked=false to get a solid body."
            )

        sw = self.connection.app
        # 3D Interconnect ON imports an associative reference instead of a
        # solid body; import diagnostics can raise a blocking dialog.
        previous = self._set_prefs({
            PREF_3D_INTERCONNECT: linked,
            PREF_DIAG_NEUTRAL: False,
            PREF_DIAG_AUTO: False,
        })

        try:
            try:
                import_data = sw.GetImportFileData(str(path))
            except Exception as e:
                logger.info(f"GetImportFileData unavailable for {path.name} ({e}); "
                            f"importing with default options")
                import_data = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)

            err = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
            doc = sw.LoadFile4(str(path), "r", import_data, err)
            if not doc:
                raise Exception(
                    f"Import failed for {path} (error={err.value}). "
                    f"Note that OpenDoc6-style errors do not apply here; a "
                    f"non-zero code usually means an unreadable or unsupported file."
                )
        except Exception:
            self._restore_prefs(previous)
            raise

        try:
            doc = self.connection.get_active_doc()
            title = str(com_prop(doc, "GetTitle"))
            doc_type = _doc_type(doc)
            if self.tracker:
                self.tracker.activate_document(
                    title, _TYPE_TO_NAME.get(doc_type, "part"))

            info = self._imported_body_info(doc)
            logger.info(f"Imported {path.name} -> {title} ({info})")

            result = {
                "result": f"✓ Imported {path.name} as {title}",
                "title": title,
                "path": str(path),
                "type": _TYPE_TO_NAME.get(doc_type, "part"),
                "linked": linked,
                **info,
            }

            if recognize:
                rec = self._run_recognition(
                    doc,
                    args.get("featureTypes") or FW_DEFAULT_TYPES,
                    bool(args.get("addConstraints", True)),
                )
                result["featureRecognition"] = rec
                result["result"] = (
                    f"✓ Imported {path.name} as {title}; "
                    f"recognized {rec.get('featuresRecognized', 0)} feature(s)"
                )
            elif not linked:
                result["hint"] = (
                    "Imported as a dumb solid with no feature history. Geometry "
                    "queries and new features work on it; for parametric "
                    "dimensions call solidworks_recognize_features."
                )

            return json.dumps(result)
        finally:
            self._restore_prefs(previous)

    def _imported_body_info(self, doc) -> dict:
        """Best-effort body/face/edge counts plus the top-level feature names."""
        info = {}
        try:
            bodies = doc.GetBodies2(0, True) or []
            faces = edges = 0
            for body in bodies:
                faces += len(body.GetFaces() or [])
                edges += len(body.GetEdges() or [])
            info.update({"bodies": len(bodies), "faces": faces, "edges": edges})
        except Exception as e:
            logger.warning(f"Could not count imported geometry: {e}")
        try:
            info["features"] = [n for n, _ in self._feature_tree(doc)]
        except Exception as e:
            logger.warning(f"Could not read imported feature tree: {e}")
        return info

    _TREE_BOILERPLATE = {
        "CommentsFolder", "FavoriteFolder", "HistoryFolder", "SelectionSetFolder",
        "SensorFolder", "DocsFolder", "DetailCabinet", "SurfaceBodyFolder",
        "SolidBodyFolder", "EnvFolder", "InkMarkupFolder", "EqnFolder",
        "MaterialFolder", "RefPlane", "OriginProfileFeature",
    }

    def _feature_tree(self, doc, limit: int = 400) -> list:
        """Walk the FeatureManager tree, skipping the standard folders."""
        out = []
        feat = com_prop(doc, "FirstFeature")
        seen = 0
        while feat is not None and seen < limit:
            seen += 1
            try:
                name = str(com_prop(feat, "Name"))
                type_name = str(com_prop(feat, "GetTypeName2"))
            except Exception:
                break
            if type_name not in self._TREE_BOILERPLATE:
                out.append((name, type_name))
            try:
                feat = com_prop(feat, "GetNextFeature")
            except Exception:
                break
        return out

    def _get_featureworks(self):
        """Load the FeatureWorks add-in and return IFeatureWorksApp, or None.
        LoadAddIn returns 0 on a fresh load and 2 when already loaded."""
        sw = self.connection.app
        try:
            status = sw.LoadAddIn(FWORKS_DLL)
            logger.info(f"FeatureWorks LoadAddIn -> {status}")
        except Exception as e:
            logger.warning(f"FeatureWorks LoadAddIn failed: {e}")
        try:
            return sw.GetAddInObject(FWORKS_PROGID)
        except Exception as e:
            logger.warning(f"GetAddInObject({FWORKS_PROGID}) failed: {e}")
            return None

    def _run_recognition(self, doc, feature_types, add_constraints: bool) -> dict:
        unknown = [t for t in feature_types if t.upper() not in FW_TYPES]
        if unknown:
            raise Exception(
                f"Unknown feature type(s): {', '.join(unknown)}. "
                f"Valid: {', '.join(sorted(FW_TYPES))}"
            )
        mask = 0
        for t in feature_types:
            mask |= FW_TYPES[t.upper()]

        fw = self._get_featureworks()
        if fw is None:
            raise Exception(
                "FeatureWorks is not available. It ships with SOLIDWORKS but "
                "requires a Professional or Premium license. Without it an "
                "imported body stays a dumb solid — it can still be measured, "
                "cut, filleted and direct-edited, just not driven by dimensions."
            )

        before = self._feature_tree(doc)
        recognized = fw.RecognizeFeatureAutomatic(mask)
        create_opts = FW_ALLOW_FAIL | (FW_ADD_CONSTRAINTS if add_constraints else 0)
        created = fw.CreateFeatures(create_opts)

        doc = self.connection.get_active_doc()
        after = self._feature_tree(doc)
        logger.info(
            f"FeatureWorks recognized {recognized} feature(s); "
            f"CreateFeatures={created}; tree {len(before)} -> {len(after)}"
        )

        out = {
            "featuresRecognized": int(recognized) if recognized is not None else 0,
            "featuresCreated": bool(created),
            "featureTypes": [t.upper() for t in feature_types],
            "treeBefore": [n for n, _ in before],
            "treeAfter": [{"name": n, "type": t} for n, t in after],
        }
        if not created or not recognized:
            out["hint"] = (
                "Recognition found nothing. Make sure VOLUME is in featureTypes "
                "— it is what identifies the base feature. If it still fails the "
                "geometry may not decompose into machining features; the body is "
                "unchanged and remains directly editable."
            )
        else:
            out["hint"] = (
                "Recognized features carry drivable dimensions (e.g. "
                "'D1@Fillet1') usable with set_parameter and list_parameters. "
                "Recognized SKETCHES are constrained but NOT dimensioned, so "
                "profile shapes cannot be driven numerically."
            )
        return out

    def recognize_features(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document to recognize features on")
        if _doc_type(doc) != DOC_TYPE_PART:
            raise Exception("Feature recognition only works on part documents")

        previous = self._set_prefs({PREF_DIAG_NEUTRAL: False, PREF_DIAG_AUTO: False})
        try:
            rec = self._run_recognition(
                doc,
                args.get("featureTypes") or FW_DEFAULT_TYPES,
                bool(args.get("addConstraints", True)),
            )
        finally:
            self._restore_prefs(previous)

        return json.dumps({
            "result": f"✓ Recognized {rec['featuresRecognized']} feature(s)",
            **rec,
        })

    def activate_document(self, args: dict) -> str:
        name = args["name"].strip()
        doc = self.connection.activate_document(name)
        title = doc.GetTitle
        doc_type = _doc_type(doc)
        if self.tracker:
            self.tracker.activate_document(title, _TYPE_TO_NAME.get(doc_type, "unknown"))

        return self._json_result(
            f"✓ Activated document: {title}",
            title=title,
            type=_TYPE_TO_NAME.get(doc_type, "document"),
        )

    def close_document(self, args: dict) -> str:
        name = args.get("name")
        if name:
            title = name.strip()
        else:
            doc = self.connection.get_active_doc()
            if not doc:
                raise Exception("No active document to close")
            title = doc.GetTitle

        # QuitDoc is a silent no-op on a wrong/stale title — verify the target
        # exists first, and verify it is gone afterwards, before touching the
        # tracker scope.
        if not self._is_doc_open(title):
            raise Exception(
                f"No open document titled '{title}' — nothing was closed. "
                f"Check the exact title with list_documents."
            )

        self.connection.app.QuitDoc(title)

        if self._is_doc_open(title):
            raise Exception(
                f"Document '{title}' is still open — QuitDoc did not close it. "
                f"Check the exact title with list_documents (titles may "
                f"include the file extension). Tracker state preserved."
            )

        if self.tracker:
            self.tracker.remove_document(title)

        logger.info(f"Closed document: {title}")
        return self._json_result(f"✓ Closed document: {title} (unsaved changes discarded)")

    def _is_doc_open(self, title: str) -> bool:
        """Best-effort check whether a document with this title is still open
        (title comparison is extension-insensitive via normalize_doc_key)."""
        from .state_tracker import normalize_doc_key
        target = normalize_doc_key(str(title)).lower()
        try:
            open_docs = com_prop(self.connection.app, "GetDocuments")
            for d in (open_docs or []):
                try:
                    if normalize_doc_key(str(d.GetTitle)).lower() == target:
                        return True
                except Exception:
                    continue
            return False
        except Exception as e:
            logger.warning(f"GetDocuments failed during close verification ({e}); "
                           f"falling back to ActiveDoc title check")
        # Fallback: at least confirm the active doc isn't the one we "closed"
        try:
            active = self.connection.get_active_doc()
            if active is not None:
                return normalize_doc_key(str(active.GetTitle)).lower() == target
        except Exception:
            pass
        return False

    # swStandardViews_e (to be re-verified live; standard documented values)
    STANDARD_VIEWS = {
        "FRONT": 1, "BACK": 2, "LEFT": 3, "RIGHT": 4,
        "TOP": 5, "BOTTOM": 6, "ISOMETRIC": 7, "TRIMETRIC": 8, "DIMETRIC": 9,
    }

    def capture_views(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document to capture")

        views = [v.upper() for v in (args.get("views") or ["ISOMETRIC", "FRONT", "TOP"])]
        out_dir = Path(args.get("outputDir") or (WORKSPACE_DIR / "screenshots"))
        out_dir.mkdir(parents=True, exist_ok=True)

        title = doc.GetTitle
        prefix = args.get("prefix") or Path(str(title)).stem or "model"
        prefix = "".join(c for c in prefix if c.isalnum() or c in "-_")

        captured = []
        for view in views:
            view_id = self.STANDARD_VIEWS.get(view)
            if view_id is None:
                raise Exception(f"Unknown view: {view}")
            doc.ShowNamedView2("", view_id)
            doc.ViewZoomtofit2()
            png = out_dir / f"{prefix}_{view.lower()}.png"
            if png.exists():
                png.unlink()
            # SaveAs to an image extension exports the current viewport
            doc.SaveAs3(str(png), 0, 2)  # options=2 (Copy) is CORRECT here: image
            # export must not rebind the session document to a .png path
            if not png.exists():
                raise Exception(f"View export failed for {view} ({png})")
            captured.append(str(png))

        logger.info(f"Captured {len(captured)} view(s) for {title}")
        return self._json_result(
            f"✓ Captured {len(captured)} view(s): {', '.join(views)}",
            files=captured,
            type="screenshots",
        )

    def list_documents(self) -> str:
        sw = self.connection.app
        active_doc = self.connection.get_active_doc()
        active_title = active_doc.GetTitle if active_doc else None

        docs = []
        try:
            open_docs = com_prop(sw, "GetDocuments")
            for d in (open_docs or []):
                try:
                    docs.append({
                        "title": d.GetTitle,
                        "type": _TYPE_TO_NAME.get(_doc_type(d), "unknown"),
                        "path": d.GetPathName or None,
                        "active": d.GetTitle == active_title,
                    })
                except Exception as e:
                    logger.warning(f"Could not read document info: {e}")
        except Exception as e:
            logger.warning(f"GetDocuments failed ({e}); falling back to tracked scopes")
            if self.tracker:
                for key, scope in self.tracker.scopes.items():
                    if key == "__default__":
                        continue
                    docs.append({
                        "title": key,
                        "type": scope.doc_type,
                        "path": None,
                        "active": key == self.tracker.active_doc_key,
                    })

        return json.dumps({
            "result": f"✓ {len(docs)} open document(s)",
            "documents": docs,
            "activeDocument": active_title,
        })
