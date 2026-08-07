"""
SolidWorks Feature Tree Tools
Read the design timeline as structured data, rename features and sketches, and
organise them into folders and subfolders.

Why this module exists: `list_features` returns a flat, human-readable string,
which is fine for a person reading a log but useless for an agent that needs to
reason about build order, nesting, or what is currently suppressed. And every
object carries an auto-generated name (`Boss-Extrude7`, `Sketch12`) that says
nothing about intent, so a model of any size becomes unreadable — to a later
agent, to a reviewer, and to the human who opens the part in SolidWorks.

COM notes (signatures from makepy on sldworks.tlb, SW2025):
  - IFeature::Name is a settable property — renaming is just an assignment.
    Stable IDs embed the name, so the tracker is re-keyed alongside it.
  - IModelDoc2::FirstFeature + IFeature::GetNextFeature walks the timeline in
    order. IFeature::GetFirstSubFeature / GetNextSubFeature descends into
    absorbed children (the sketch consumed by an extrude).
  - A folder reports GetTypeName2 == "FtrFolder"; its contents come from
    IFeature::GetSpecificFeature2() -> IFeatureFolder::GetFeatures().
  - IFeatureManager::InsertFeatureTreeFolder2(swFeatureTreeFolderType_e):
    1 = EmptyBefore (empty folder above the selection), 2 = Containing (folder
    wrapping the current selection).
  - IFeatureManager::MoveToFolder(FolderName, ItemName, MoveAfterFolder).
"""

import json
import logging
from mcp.types import Tool
from . import selection_helpers as sel
from .com_utils import com_prop, exit_active_sketch

logger = logging.getLogger(__name__)

# swFeatureTreeFolderType_e
FOLDER_EMPTY_BEFORE = 1
FOLDER_CONTAINING = 2

# Tree items that are scaffolding rather than design steps. Hidden by default
# so an agent reading the timeline sees the model, not the furniture.
BOILERPLATE_TYPES = {
    "CommentsFolder", "FavoriteFolder", "HistoryFolder", "SelectionSetFolder",
    "SensorFolder", "DocsFolder", "DetailCabinet", "SurfaceBodyFolder",
    "SolidBodyFolder", "EnvFolder", "InkMarkupFolder", "EqnFolder",
    "MaterialFolder", "OriginProfileFeature",
}
# Reference planes are scaffolding in a default part but meaningful once the
# agent has created its own, so they are only hidden when they are the three
# stock planes.
STOCK_PLANES = {"Front Plane", "Top Plane", "Right Plane"}

FOLDER_TYPE = "FtrFolder"

# SolidWorks emits a closing pseudo-feature for every folder in the linear
# walk ("Folder1___EndTag___"). It is not a design step and must never be
# reported, renamed, or used as an anchor.
END_TAG = "___EndTag___"


class FeatureTreeTools:
    """Timeline inspection, naming, and folder organisation."""

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
                name="solidworks_get_feature_tree",
                description=(
                    "Read the design timeline as structured data: every feature in "
                    "build order, with its type, tracked ID, suppression state, "
                    "folder nesting, and absorbed sub-features (the sketch consumed "
                    "by an extrude). This is the tool for understanding an existing "
                    "model — your own from earlier in the session, one opened from "
                    "disk, or one recovered by recognize_features. Prefer it over "
                    "list_features, which returns unstructured text."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "includeSubFeatures": {
                            "type": "boolean",
                            "description": "Include absorbed children such as the sketch under an extrude (default true)",
                        },
                        "includeBoilerplate": {
                            "type": "boolean",
                            "description": "Include stock planes, origin and the standard folders (default false)",
                        },
                        "includeSuppressed": {
                            "type": "boolean",
                            "description": "Include suppressed features (default true)",
                        },
                    },
                },
            ),
            Tool(
                name="solidworks_rename_feature",
                description=(
                    "Give a feature, sketch or reference plane a meaningful name. "
                    "DO THIS AS YOU BUILD — name each feature right after creating "
                    "it, describing what it is for ('Mounting Boss', 'M6 Clearance "
                    "Holes', 'Wall Thickness Shell') rather than what it is "
                    "('Boss-Extrude3'). A model whose timeline reads as a "
                    "description of the design is dramatically easier for a later "
                    "agent to modify correctly, and is what a human engineer "
                    "expects to open. Renaming updates the tracked ID too, so the "
                    "returned new ID replaces the old one in later calls."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Current name or tracked ID (e.g. 'Boss-Extrude1', 'feat:Boss-Extrude1', 'Sketch2')",
                        },
                        "newName": {
                            "type": "string",
                            "description": "New name. Must be unique in the document; SolidWorks rejects '@' and some punctuation.",
                        },
                    },
                    "required": ["name", "newName"],
                },
            ),
            Tool(
                name="solidworks_create_feature_folder",
                description=(
                    "Group features into a named folder in the design tree. Use "
                    "this to keep a model of any size navigable — group by function "
                    "('Mounting Features', 'Cooling Passages', 'Cosmetic Fillets'). "
                    "Pass the features to collect and they are moved into a new "
                    "folder; pass none to create an empty folder to fill later with "
                    "move_to_folder. Folders are organisational only: they do not "
                    "change build order or geometry. NOTE: folders are FLAT — "
                    "SolidWorks does not support nesting one design-tree folder "
                    "inside another via the API, so use several well-named "
                    "top-level folders rather than a hierarchy."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "folderName": {
                            "type": "string",
                            "description": "Name for the new folder",
                        },
                        "features": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Feature names or tracked IDs to place in the folder. Omit for an empty folder.",
                        },
                        "parentFolder": {
                            "type": "string",
                            "description": "NOT SUPPORTED by SolidWorks — folder nesting fails. Left in the schema so the failure is reported explicitly rather than silently ignored.",
                        },
                    },
                    "required": ["folderName"],
                },
            ),
            Tool(
                name="solidworks_move_to_folder",
                description=(
                    "Move existing features into an existing design-tree folder. "
                    "KNOWN LIMITATION: IFeatureManager::MoveToFolder is rejected by "
                    "SolidWorks 2025 in testing — into empty folders, into populated "
                    "folders, and for nesting one folder in another, with either "
                    "MoveAfterFolder value. Prefer create_feature_folder with the "
                    "complete `features` list, which does work; that means deciding "
                    "a folder's membership when you create it. This tool is kept so "
                    "the failure is explicit, and because other SolidWorks builds "
                    "may accept the call."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "folderName": {
                            "type": "string",
                            "description": "Destination folder name",
                        },
                        "features": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Feature names, tracked IDs, or a folder name to nest",
                        },
                    },
                    "required": ["folderName", "features"],
                },
            ),
        ]

    def execute(self, tool_name: str, args: dict) -> str:
        self.connection.ensure_connection()
        dispatch = {
            "solidworks_get_feature_tree": lambda: self.get_feature_tree(args),
            "solidworks_rename_feature": lambda: self.rename_feature(args),
            "solidworks_create_feature_folder": lambda: self.create_feature_folder(args),
            "solidworks_move_to_folder": lambda: self.move_to_folder(args),
        }
        handler = dispatch.get(tool_name)
        if not handler:
            raise Exception(f"Unknown feature-tree tool: {tool_name}")
        return handler()

    # --- helpers ---

    def _resolve(self, name_or_id: str) -> str:
        """Accept a tracked ID or a raw SolidWorks name, return the SW name."""
        raw = str(name_or_id).strip()
        if self.tracker:
            try:
                resolved = self.tracker.resolve_name(raw)
                if resolved:
                    return resolved
            except Exception:
                pass
        for prefix in ("feat:", "sketch:", "ref:"):
            if raw.startswith(prefix):
                return raw[len(prefix):]
        return raw

    def _tracked_id(self, sw_name: str):
        if not self.tracker:
            return None
        try:
            return self.tracker.get_id_by_sw_name(sw_name)
        except Exception:
            return None

    def _find_feature(self, doc, sw_name: str):
        """Locate a feature by name anywhere in the tree, including inside
        folders and among absorbed sub-features.

        Deliberately iterative and bounded. Sub-features must be walked with
        GetNextSubFeature — calling GetNextFeature on a sub-feature rejoins the
        top-level chain and the traversal never terminates.
        """
        target = sw_name.lower()

        def matches(feature):
            try:
                return str(com_prop(feature, "Name")).lower() == target
            except Exception:
                return False

        # Folders can nest, so their contents are explored breadth-first from
        # a queue rather than recursively.
        folder_queue = []
        feature = com_prop(doc, "FirstFeature")
        steps = 0
        while feature is not None and steps < 5000:
            steps += 1
            if matches(feature):
                return feature

            sub = self._first_sub(feature)
            sub_steps = 0
            while sub is not None and sub_steps < 200:
                sub_steps += 1
                if matches(sub):
                    return sub
                try:
                    sub = com_prop(sub, "GetNextSubFeature")
                except Exception:
                    break

            kids = self._folder_children(feature)
            if kids:
                folder_queue.extend(kids)

            try:
                feature = com_prop(feature, "GetNextFeature")
            except Exception:
                break

        seen = 0
        while folder_queue and seen < 5000:
            seen += 1
            kid = folder_queue.pop(0)
            if matches(kid):
                return kid
            nested = self._folder_children(kid)
            if nested:
                folder_queue.extend(nested)
        return None

    def _first_sub(self, feature):
        try:
            return com_prop(feature, "GetFirstSubFeature")
        except Exception:
            return None

    def _folder_children(self, feature) -> list:
        """Contents of a folder feature, or [] for anything else."""
        try:
            if str(com_prop(feature, "GetTypeName2")) != FOLDER_TYPE:
                return []
            folder = com_prop(feature, "GetSpecificFeature2")
            if folder is None:
                return []
            return list(com_prop(folder, "GetFeatures") or [])
        except Exception as e:
            logger.warning(f"Could not read folder contents: {e}")
            return []

    def _last_feature(self, doc):
        """The final feature in the timeline — used as an anchor when an empty
        folder has to be inserted somewhere."""
        last = None
        feature = com_prop(doc, "FirstFeature")
        steps = 0
        while feature is not None and steps < 2000:
            steps += 1
            try:
                type_name = str(com_prop(feature, "GetTypeName2"))
            except Exception:
                break
            try:
                name = str(com_prop(feature, "Name"))
            except Exception:
                name = ""
            if (type_name not in BOILERPLATE_TYPES and type_name != "RefPlane"
                    and END_TAG not in name):
                last = feature
            try:
                feature = com_prop(feature, "GetNextFeature")
            except Exception:
                break
        return last

    def _is_suppressed(self, feature) -> bool:
        try:
            return bool(com_prop(feature, "IsSuppressed"))
        except Exception:
            return False

    def _describe(self, feature, index, opts, depth=0):
        """Build the structured record for one tree item, recursing into
        folder contents and absorbed sub-features."""
        try:
            name = str(com_prop(feature, "Name"))
            type_name = str(com_prop(feature, "GetTypeName2"))
        except Exception as e:
            logger.warning(f"Could not read feature at index {index}: {e}")
            return None

        if END_TAG in name:
            return None
        if not opts["boilerplate"]:
            if type_name in BOILERPLATE_TYPES:
                return None
            if type_name == "RefPlane" and name in STOCK_PLANES:
                return None

        suppressed = self._is_suppressed(feature)
        if suppressed and not opts["suppressed"]:
            return None

        node = {
            "name": name,
            "type": type_name,
            "index": index,
            "depth": depth,
        }
        tid = self._tracked_id(name)
        if tid:
            node["id"] = tid
        if suppressed:
            node["suppressed"] = True

        if type_name == FOLDER_TYPE:
            node["isFolder"] = True
            children = []
            for i, kid in enumerate(self._folder_children(feature)):
                child = self._describe(kid, i, opts, depth + 1)
                if child:
                    children.append(child)
            node["children"] = children
            node["childCount"] = len(children)
            return node

        if opts["subfeatures"]:
            subs = []
            sub = self._first_sub(feature)
            i = 0
            while sub is not None and i < 50:
                child = self._describe(sub, i, opts, depth + 1)
                if child:
                    subs.append(child)
                i += 1
                try:
                    sub = com_prop(sub, "GetNextSubFeature")
                except Exception:
                    break
            if subs:
                node["subFeatures"] = subs
        return node

    # --- tool implementations ---

    def get_feature_tree(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")

        opts = {
            "subfeatures": bool(args.get("includeSubFeatures", True)),
            "boilerplate": bool(args.get("includeBoilerplate", False)),
            "suppressed": bool(args.get("includeSuppressed", True)),
        }

        tree = []
        feature = com_prop(doc, "FirstFeature")
        index = 0
        # SolidWorks keeps foldered features AND absorbed sketches in the
        # linear walk, so anything already reported as a folder's contents or
        # as another feature's sub-feature must not be repeated at top level.
        nested = set()
        pending = []
        while feature is not None and index < 2000:
            node = self._describe(feature, index, opts)
            if node:
                pending.append(node)
                for child in node.get("children", []):
                    nested.add(child["name"])
                for child in node.get("subFeatures", []):
                    nested.add(child["name"])
            index += 1
            try:
                feature = com_prop(feature, "GetNextFeature")
            except Exception:
                break

        order = 0
        for node in pending:
            if node.get("isFolder") or node["name"] not in nested:
                node["order"] = order
                order += 1
                tree.append(node)

        def count(nodes):
            total = 0
            for n in nodes:
                total += 1
                total += count(n.get("children", []))
                total += count(n.get("subFeatures", []))
            return total

        title = None
        try:
            title = str(com_prop(doc, "GetTitle"))
        except Exception:
            pass

        unnamed = [n["name"] for n in tree
                   if not n.get("isFolder") and _looks_autogenerated(n["name"])]

        payload = {
            "result": f"✓ {len(tree)} top-level item(s), {count(tree)} total",
            "document": title,
            "topLevelCount": len(tree),
            "totalCount": count(tree),
            "tree": tree,
        }
        if unnamed:
            payload["hint"] = (
                f"{len(unnamed)} feature(s) still carry auto-generated names "
                f"({', '.join(unnamed[:5])}"
                f"{'…' if len(unnamed) > 5 else ''}). Consider rename_feature "
                f"to describe what they are for — it makes the model far easier "
                f"to modify later."
            )
        logger.info(f"Feature tree: {len(tree)} top-level, {count(tree)} total")
        return json.dumps(payload)

    def rename_feature(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")
        exit_active_sketch(doc)

        old_name = self._resolve(args["name"])
        new_name = str(args["newName"]).strip()
        if not new_name:
            raise Exception("newName cannot be empty")
        if "@" in new_name:
            raise Exception(
                "SolidWorks does not allow '@' in feature names (it is the "
                "dimension-address separator, as in 'D1@Boss-Extrude1')."
            )
        if old_name == new_name:
            return self._json_result(
                f"✓ '{new_name}' already has that name (no change)",
                name=new_name, type="rename", changed=False,
            )

        if self._find_feature(doc, new_name) is not None:
            raise Exception(
                f"A feature named '{new_name}' already exists — SolidWorks "
                f"requires unique names within a document."
            )

        feature = self._find_feature(doc, old_name)
        if feature is None:
            raise Exception(
                f"No feature, sketch or reference geometry named '{old_name}' "
                f"was found. Use get_feature_tree to see the exact names."
            )

        type_name = str(com_prop(feature, "GetTypeName2"))
        feature.Name = new_name

        actual = str(com_prop(feature, "Name"))
        if actual != new_name:
            raise Exception(
                f"Rename did not take: asked for '{new_name}', the feature is "
                f"still called '{actual}'. SolidWorks rejects duplicate names "
                f"and some punctuation."
            )

        new_id = None
        if self.tracker:
            new_id = self.tracker.rename_object(old_name, new_name)

        logger.info(f"Renamed {old_name} -> {new_name} ({type_name})")
        return self._json_result(
            f"✓ Renamed '{old_name}' to '{new_name}'",
            name=new_name,
            previousName=old_name,
            id=new_id,
            featureType=type_name,
            type="rename",
            changed=True,
        )

    def _select_features(self, doc, names, mark=0):
        """Select each named feature, or raise naming the ones not found."""
        sel.clear_selection(doc)
        missing = []
        selected = 0
        for name_or_id in names:
            sw_name = self._resolve(name_or_id)
            feature = self._find_feature(doc, sw_name)
            if feature is None:
                missing.append(sw_name)
                continue
            try:
                if feature.Select2(selected > 0, mark):
                    selected += 1
                else:
                    missing.append(sw_name)
            except Exception as e:
                logger.warning(f"Select2 failed for {sw_name}: {e}")
                missing.append(sw_name)
        if missing:
            raise Exception(
                f"Could not select: {', '.join(missing)}. Nothing was changed. "
                f"Use get_feature_tree for the exact names."
            )
        return selected

    def create_feature_folder(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")
        exit_active_sketch(doc)

        folder_name = str(args["folderName"]).strip()
        if not folder_name:
            raise Exception("folderName cannot be empty")
        features = args.get("features") or []
        parent = args.get("parentFolder")

        if self._find_feature(doc, folder_name) is not None:
            raise Exception(
                f"'{folder_name}' already exists in this document — folder and "
                f"feature names share one namespace."
            )

        if features:
            self._select_features(doc, features)
            folder_type = FOLDER_CONTAINING
        else:
            # An EmptyBefore folder is inserted ABOVE the current selection and
            # SolidWorks returns nothing if nothing is selected — so anchor it
            # on the last feature in the tree.
            anchor = self._last_feature(doc)
            if anchor is None:
                raise Exception(
                    "Cannot create an empty folder in a document with no "
                    "features — SolidWorks inserts empty folders above a "
                    "selected feature. Create some geometry first, or pass "
                    "`features` to wrap existing ones."
                )
            sel.clear_selection(doc)
            try:
                anchor.Select2(False, 0)
            except Exception as e:
                raise Exception(
                    f"Could not select an anchor feature for the empty folder: {e}"
                )
            folder_type = FOLDER_EMPTY_BEFORE

        created = doc.FeatureManager.InsertFeatureTreeFolder2(folder_type)
        if created is None:
            raise Exception(
                f"InsertFeatureTreeFolder2 returned nothing — the folder was "
                f"not created. Empty folders are inserted above the current "
                f"selection; a document with no features may not accept one."
            )

        default_name = str(com_prop(created, "Name"))
        try:
            created.Name = folder_name
            actual = str(com_prop(created, "Name"))
        except Exception as e:
            raise Exception(
                f"Folder was created as '{default_name}' but could not be "
                f"renamed to '{folder_name}': {e}"
            )

        nested_into = None
        if parent:
            parent_name = self._resolve(parent)
            if self._find_feature(doc, parent_name) is None:
                raise Exception(
                    f"Folder '{actual}' was created, but the parentFolder "
                    f"'{parent_name}' does not exist — it was left at top level."
                )
            # Verified live: MoveToFolder returns False for a folder child with
            # either MoveAfterFolder value, and IFeatureManager::InsertSubFolder
            # resolves to a property returning None. SolidWorks does not support
            # nesting design-tree folders through the API. The attempt is kept
            # so a future build that does support it starts working for free.
            moved = doc.FeatureManager.MoveToFolder(parent_name, actual, False)
            if not moved:
                raise Exception(
                    f"Folder '{actual}' WAS created at top level, but SolidWorks "
                    f"refused to nest it inside '{parent_name}' — design-tree "
                    f"folders cannot be nested through the API (MoveToFolder "
                    f"returns False for a folder child, and InsertSubFolder is "
                    f"unavailable). Use several well-named top-level folders "
                    f"instead. Nothing needs cleaning up unless you want the "
                    f"folder removed."
                )
            nested_into = parent_name

        logger.info(
            f"Created folder '{actual}' with {len(features)} feature(s)"
            + (f" inside '{nested_into}'" if nested_into else "")
        )
        return self._json_result(
            f"✓ Created folder '{actual}'"
            + (f" containing {len(features)} feature(s)" if features else " (empty)")
            + (f", nested in '{nested_into}'" if nested_into else ""),
            folder=actual,
            type="feature_folder",
            featuresPlaced=len(features),
            parentFolder=nested_into,
        )

    def move_to_folder(self, args: dict) -> str:
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")
        exit_active_sketch(doc)

        folder_name = self._resolve(args["folderName"])
        features = args["features"]
        if isinstance(features, str):
            features = [features]
        if not features:
            raise Exception("No features given to move")

        folder = self._find_feature(doc, folder_name)
        if folder is None:
            raise Exception(
                f"No folder named '{folder_name}'. Create it first with "
                f"create_feature_folder."
            )
        if str(com_prop(folder, "GetTypeName2")) != FOLDER_TYPE:
            raise Exception(
                f"'{folder_name}' is a {com_prop(folder, 'GetTypeName2')}, not "
                f"a folder."
            )

        moved, failed = [], []
        for name_or_id in features:
            sw_name = self._resolve(name_or_id)
            if self._find_feature(doc, sw_name) is None:
                failed.append(f"{sw_name} (not found)")
                continue
            # MoveAfterFolder controls whether the item lands after the folder
            # in build order. Which value SolidWorks accepts depends on where
            # the folder sits relative to the feature, so try both rather than
            # reporting a spurious rejection.
            placed = False
            errors = []
            for after in (False, True):
                try:
                    if doc.FeatureManager.MoveToFolder(folder_name, sw_name, after):
                        placed = True
                        break
                except Exception as e:
                    errors.append(str(e))
            if placed:
                moved.append(sw_name)
            elif errors:
                failed.append(f"{sw_name} ({errors[0]})")
            else:
                failed.append(
                    f"{sw_name} (rejected — SolidWorks refuses moves that would "
                    f"reorder the build; the folder may sit before this feature)"
                )

        if failed and not moved:
            raise Exception(
                f"Could not move anything into '{folder_name}': "
                f"{'; '.join(failed)}"
            )

        logger.info(f"Moved {len(moved)} item(s) into folder '{folder_name}'")
        result = f"✓ Moved {len(moved)} item(s) into '{folder_name}'"
        if failed:
            result += f" ({len(failed)} failed: {'; '.join(failed)})"
        return self._json_result(
            result,
            folder=folder_name,
            moved=moved,
            failed=failed,
            type="move_to_folder",
        )


def _looks_autogenerated(name: str) -> bool:
    """True for SolidWorks default names like 'Boss-Extrude3' or 'Sketch12'."""
    import re
    return bool(re.fullmatch(
        r"(Sketch|Boss-Extrude|Cut-Extrude|Fillet|Chamfer|Shell|Draft|Rib|"
        r"Revolve|Cut-Revolve|Sweep|Cut-Sweep|Loft|Cut-Loft|Plane|Axis|Point|"
        r"LPattern|CirPattern|Mirror|Imported|Move Face|Delete Face)\d*",
        name.strip()))
