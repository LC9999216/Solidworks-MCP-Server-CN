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
  - OpenDoc6 / ActivateDoc3 need VARIANT byref args for errors — handled in
    connection.py.
  - Document titles may or may not include the file extension depending on
    Windows Explorer settings; the state tracker normalizes scope keys.
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
                description="Save the active document to disk. Required before a part can be inserted into an assembly. A bare filename (e.g. 'bracket') is saved into the project workspace directory; an absolute path is used as-is. The correct extension (.SLDPRT/.SLDASM) is added automatically based on document type.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Filename or absolute path to save to (extension optional)"
                        }
                    },
                    "required": ["path"]
                }
            ),
            Tool(
                name="solidworks_open_document",
                description="Open a part, assembly, or drawing document from disk (silently, no dialogs). The opened document becomes active.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the .SLDPRT/.SLDASM/.SLDDRW file"
                        }
                    },
                    "required": ["path"]
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
        if path.suffix.lower() not in _EXT_TO_TYPE:
            path = path.with_name(path.name + ext)
        if not path.is_absolute():
            WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
            path = WORKSPACE_DIR / path
        path.parent.mkdir(parents=True, exist_ok=True)

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

    def open_document(self, args: dict) -> str:
        raw = args["path"].strip()
        path = Path(raw)
        if not path.is_absolute():
            candidate = WORKSPACE_DIR / path
            if candidate.exists():
                path = candidate
        if not path.exists():
            raise Exception(f"File not found: {path}")

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
