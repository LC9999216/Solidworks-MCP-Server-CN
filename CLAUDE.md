# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SolidWorks MCP Server bridges Claude AI with SolidWorks CAD via the Model Context Protocol (MCP), enabling natural language creation and manipulation of 3D CAD models. Requires Windows + SolidWorks installed.

## Commands

```powershell
# Install dependencies
pip install -r requirements.txt

# Or install as an editable package (exposes `solidworks` and `server` for import)
pip install -e .

# Run all tests (closes open docs first, then runs all categories)
python test.py

# Interactive CLI test picker — select tests by number, range, or category
python test.py --gui

# Run a single category
python test.py --category "Sketch Tools"
python test.py --category "Feature Tools"
python test.py --category "Integration"

# Run a single test by name
python test.py --test basic_cube
python test.py --test sketch_line

# List all available tests
python test.py --list

# Run the server directly (normally launched by an MCP client such as Claude Desktop)
python server.py

# Dev server with hot reload (requires watchdog)
python dev_server.py

# Close all open SolidWorks documents (standalone utility)
python clean.py
```

## Claude Desktop Configuration

The server is registered in `%APPDATA%\Claude\claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "solidworks": {
      "command": "python",
      "args": ["C:\\path\\to\\solidworks-mcp\\server.py"]
    }
  }
}
```

## Architecture

```
server.py                         # MCP server: registers tools, routes calls via dispatch map
solidworks/
  __init__.py                     # Package exports for all modules
  connection.py                   # COM connection to SolidWorks, template discovery, part creation
  state_tracker.py                # Centralized state tracker: stable IDs for features, sketches, entities
  state_query.py                  # MCP tools for querying tracked state (get_state, get_entity, get_sketch_entities)
  sketching.py                    # 2D sketch tools, dimensioning, and constraints with spatial tracking
  modeling.py                     # Core modeling (new_part, extrusion, cut-extrusion, mass_properties, list_features)
  selection_helpers.py            # Shared selection utilities (edge, face, plane, feature, axis)
  features.py                     # Boss/Base features (revolve, sweep, loft, boundary boss)
  cut_features.py                 # Cut features (cut revolve, cut sweep, cut loft, boundary cut)
  applied_features.py             # Applied features (fillet, chamfer, shell, draft, rib, wrap, intersect)
  patterns.py                     # Patterns (linear pattern, circular pattern, mirror)
  hole_features.py                # Hole features (hole wizard, cosmetic thread)
  reference_geometry.py           # Reference geometry (ref plane, ref axis, ref point, coordinate system)
  geometry_query.py               # Geometry inspection (body info, faces, edges, face edges, vertices) with feature tagging
  document_manager.py             # Document lifecycle (save, open, activate, close, list, capture_views)
  assembly.py                     # Assembly tools (new assembly, insert component, mates, interference, assembly queries)
  configurations.py               # Configurations (variants, per-config dims) and equations
  feature_tree.py                 # Timeline as structured data, renaming, folders
  com_utils.py                    # Shared late-bound COM helpers (com_prop)
test.py                           # Unified test suite with registry, CLI selector (--gui), category/test filters
clean.py                          # Close all open SolidWorks documents (standalone utility)
scripts/install.ps1               # End-user installer: installs uv, downloads latest release, sets up venv, patches Claude Desktop config
```

**Test suite (`test.py`):** Uses a decorator-based test registry with 6 categories (Basic, Sketch Tools, Feature Tools, MCP Tools, Assembly, Integration). Each test is `def test_xxx(sw, template) -> bool`. The runner closes all open docs before starting, and between each test. The Integration category wraps the sequential cut-extrude reliability sub-tests as a single meta-test.

**Data flow:** Claude → MCP tool call → `server.py` → `_route_tool()` (dispatch map) → module → SolidWorks COM API

**Routing:** `server.py` builds a `{tool_name: module}` dispatch map at startup from each module's `get_tool_definitions()`. No static tool lists needed—adding a tool to a module auto-registers it. `server.py` itself defines one extra tool: `solidworks_batch` (up to 25 sequential tool calls in one MCP request; no result chaining; stops on first error unless `stopOnError=false`; cannot nest itself).

**Workflow order:** `new_part` → `create_sketch` → sketch entities → (optional: dimensions/constraints) → `exit_sketch` → feature creation (extrude, revolve, etc.)

## Key Implementation Details

**Units:** All tool inputs/outputs use millimeters. The SolidWorks COM API requires meters, so all values are divided by 1000 internally before API calls. Angles are input in degrees and converted to radians internally.

**State tracking:** A centralized `StateTracker` (`state_tracker.py`) assigns stable IDs to all created objects and maintains them across the session. State is **scoped per document**: each part/assembly gets its own `DocumentScope` (features, sketches, entities, components, mates, spatial tracking), so building multiple parts and an assembly in one session preserves each document's state. `new_part`/`new_assembly` create a fresh scope; `activate_document`/`open_document` switch scopes; `save_document` re-keys the scope to the new title. IDs follow the format:
- Features: `feat:<sw_name>` (e.g., `feat:Boss-Extrude1`)
- Sketches: `sketch:<sw_name>` (e.g., `sketch:Sketch1`)
- Sketch entities: `entity:<sketch>/<type>_<idx>` (e.g., `entity:Sketch1/rect_0`, `entity:Sketch1/line_0`)
- Reference geometry: `ref:<sw_name>` (e.g., `ref:Plane1`)
- Components: `comp:<sw_name>` (e.g., `comp:bracket-1`)
- Mates: `mate:<sw_name>` (e.g., `mate:Coincident1`)

All tools accept both tracked IDs and raw SolidWorks names. When raw names are used, a deprecation warning is logged.

**JSON returns:** All tools return JSON strings with a standard structure: `{"result": "✓ ...", "id": "feat:...", "type": "..."}`. Geometry query tools return structured data (faces/edges/vertices as arrays of objects). Error returns remain plain strings prefixed with `❌`.

**Spatial tracking:** The `StateTracker` maintains a `last_shape` dict with the center, edges, width/height/radius of the most recently drawn shape. This enables Claude to position shapes relative to previous ones without needing to track coordinates itself. Entities that update spatial tracking: rectangle, circle, line, arc, polygon, ellipse, spline, slot. Entities that do NOT update tracking: point, centerline, text.

**Positioning priority** in `sketch_rectangle`/`sketch_circle`/`sketch_polygon` (highest wins):
1. Absolute `centerX`/`centerY`
2. `spacing` from last shape edge
3. Relative `relativeX`/`relativeY` offset from last center
4. Default: origin `(0, 0)`

**Loft workflow:** Lofts require profiles on different planes. The `create_sketch` `plane` parameter accepts both standard planes ("Front", "Top", "Right") and custom reference plane names or IDs ("Plane1", "ref:Plane1"). Typical workflow:
1. `create_sketch(plane="Front")` → draw first profile → `exit_sketch` (returns `{"id": "sketch:Sketch1", ...}`)
2. `ref_plane(type="OFFSET", referencePlane="Front", offset=80)` (returns `{"id": "ref:Plane1", ...}`)
3. `create_sketch(plane="Plane1")` → draw second profile → `exit_sketch` (returns `{"id": "sketch:Sketch2", ...}`)
4. `loft(profileSketches=["sketch:Sketch1", "sketch:Sketch2"])` — accepts both IDs and raw names

**Selection helpers** (`selection_helpers.py`): All geometry selection (edges, faces, planes, features, axes, vertices) is centralized here. Functions accept coordinates in mm and convert to meters. Used by all feature modules. Key functions: `select_edge`, `select_face`, `select_plane`, `select_feature`, `select_sketch`, `select_axis`, `select_vertex`, `select_multiple_edges`, `select_multiple_faces`.

**Module pattern:** Each feature module follows the same structure: class with `__init__(self, connection, tracker=None)`, `get_tool_definitions() -> list[Tool]`, and `execute(tool_name, args) -> str`. Returns are JSON strings. Modules that accept sketch/feature name inputs (features, cut_features, patterns) have a `_resolve_name()` helper that accepts both tracked IDs and raw SolidWorks names.

**Feature ID returns:** All tools that create objects return a JSON string containing the stable ID (e.g., `{"result": "✓ Extrusion ...", "id": "feat:Boss-Extrude1", "type": "extrusion"}`). Agents should use these IDs for subsequent operations. Sketch entity tools also include the parent `sketchId`.

**Extrusion end conditions:** Both `create_extrusion` and `create_cut_extrusion` accept an optional `endCondition` parameter: `"BLIND"` (default, extrudes to specified depth) or `"THROUGH_ALL"` (extrudes through entire body). Through All is especially useful for cut-extrusions where the agent doesn't need to calculate exact depth.

### Sketch Tools

`sketch_rectangle`, `sketch_circle`, `sketch_profile` (whole chained LINE/TANGENT_ARC/ARC profile in one call, optional auto-close + corner fillets — preferred over many line/arc calls), `sketch_fillet` (round a sketch corner by vertex with an exact tangent arc), `sketch_offset` (offset existing geometry/chain by a distance; negative flips side), `sketch_line`, `sketch_centerline`, `sketch_arc` (3-point or center-point), `sketch_spline`, `sketch_ellipse`, `sketch_polygon`, `sketch_slot`, `sketch_point`, `sketch_text`, `sketch_dimension` (add smart dimension with optional driving value), `set_dimension_value` (modify existing dimension), `sketch_constraint`, `sketch_toggle_construction`, `create_sketch`, `exit_sketch`, `get_last_shape_info`.

### Modeling Tools

`new_part`, `create_extrusion` (optional `merge: false` creates a separate body for multi-body work), `create_cut_extrusion` (cut direction auto-flips into the body when the first attempt fails — sketches on boundary planes just work), `combine_bodies` (ADD/SUBTRACT/COMMON boolean of a multi-body part; swBodyOperationType_e probed live: 15901=COMMON, 15902=SUBTRACT, 15903=ADD — reverse of common docs), `set_material` (assign a SOLIDWORKS Materials entry, e.g. '6061 Alloy' — required for mass questions; density is default 1000 kg/m³ otherwise), `set_parameter` (set any dimension by name, e.g. 'D1@Boss-Extrude1' — parametric "modify the part" operations), `suppress_feature`, `delete_feature`, `get_mass_properties` (kg + grams; optional `coordinateSystem` reports COM relative to a coordinate-system feature), `list_features`, `list_parameters` (every driving dimension with its addressable name, value, unit, and owning feature — use before `set_parameter`/`set_config_parameter`/equations instead of guessing names).

**Sketch coordinate frames:** `create_sketch` returns `sketchFrame` (origin + X/Y axis directions in model space). Face sketches can have mirrored or rotated axes (back face: sketch X = model −X; top face: sketch Y = model −Z) — convert model targets with `sketch_x = xAxisModel · (target − originModel_mm)`. The sketch ORIGIN on a face is the model origin projected onto the face plane, NOT the face center — face sketches therefore also return `faceCenter` (`model_mm` + `sketch_mm`, from the face bounding box) as the layout datum.

### Configuration & Equation Tools

`add_configuration`, `switch_configuration`, `list_configurations`, `set_config_parameter` (dimension value in ONE configuration only), `add_equation` (e.g. `"D1@Boss-Extrude1" = "D1@Sketch1" / 2` — re-solves automatically when driving dims change), `list_equations`, `delete_equation`.

### Boss/Base Features

`revolve` (requires centerline in sketch), `sweep` (profile + path sketches), `loft` (2+ profile sketches), `boundary_boss` (profiles + optional guide curves).

### Cut Features

`cut_revolve`, `cut_sweep`, `cut_loft`, `boundary_cut`. Same params as boss counterparts but remove material.

### Applied Features

`fillet` (edges + radius), `chamfer` (edges + distance) — both accept a `feature` param that fillets/chamfers every edge of that feature by selecting IEdge objects DIRECTLY via `Select4` (view-independent, includes closed/circular edges; PREFERRED over coordinates), `shell` (faces to remove + thickness), `draft` (neutral plane + faces + angle), `rib` (sketch profile + thickness), `wrap` (emboss/deboss/scribe onto face), `intersect` (overlapping bodies).

**Selection pitfall:** `SelectByID2` coordinate picks resolve against the CURRENT CAMERA VIEW — geometry occluded from the camera cannot be picked even with exact on-geometry coordinates (no single view sees all 12 edges of a box), and geometry viewed edge-on can silently hijack a pick meant for its neighbor. Prefer direct object selection (`selection_helpers.select_entities_directly`, used by fillet's `feature` path) for anything enumerable via COM traversal. `create_sketch`'s face path verifies the picked face is within 1mm of the requested point and falls back to nearest-face object selection (`_face_object_at_point`) — both occlusion and edge-on mis-picks self-heal. Other coordinate-based tools warn about this in their error messages.

### Patterns

`linear_pattern` (features + direction + spacing + count, optional 2nd direction; direction accepts `{"axis": "X"|"Y"|"Z"}` — PREFERRED, picks any parallel body edge via object selection — or a coordinate point on an edge), `circular_pattern` (features + axis + count + angle), `mirror` (features + mirror plane).

### Hole Features

`hole_wizard` (FLAGGED: may trigger blocking dialog), `thread` (cosmetic thread on circular edge).

### Reference Geometry

`ref_plane` (offset/angle/through-point), `ref_axis` (two-points/cylindrical-face/edge), `ref_point` (coordinates/arc-center/face-center/on-edge), `coordinate_system` (origin + optional axis edges).

### Geometry Query Tools

`get_body_info` (bounding box, face/edge/vertex counts), `get_faces` (enumerate with type, area, normal, sample point; optional `surfaceType` filter), `get_edges` (enumerate with endpoints, midpoint, length; optional `edgeType` and `feature` filters), `get_face_edges` (edges of a specific face by coordinate), `get_vertices` (all unique vertex coordinates), `find_face` (select a face by DESCRIPTION: orientation +X/−X/.../ANGLED/ANY, creating feature, surface type, and/or area rank — returns sample points ready for `create_sketch`/selection tools; face normals are sense-corrected OUTWARD via `FaceInSurfaceSense`, same as `get_faces` details), `look_at_model` (screenshot of the model returned as image content in the MCP response, with face labels F0/F1/... matching `get_faces` indices; `view='sketch'` captures the active sketch normal-to; labels need Pillow).

**Feature tagging:** every face returned by `get_faces`/`get_face_edges` includes `"feature"` (and `"featureId"` when tracked) — the feature that created it, via `IFace2.GetFeature`. Every edge from `get_edges` includes a `"features"` list (features whose faces meet at that edge, via `GetTwoAdjacentFaces2`). This lets agents select geometry by feature ("fillet the edges of Boss-Extrude2") instead of guessing coordinates.
### Document Tools

`save_document` (true Save As; bare filenames go to `workspace/`; required before inserting a part into an assembly; a neutral extension — .STEP/.STP/.IGS/.X_T/.SAT/.STL/.3MF — **exports** instead, leaving the session document open and unchanged), `open_document` (silent OpenDoc6; neutral formats auto-route to `import_file`), `import_file` (neutral CAD import), `recognize_features` (FeatureWorks), `activate_document` (switch active doc — subsequent tools operate on it), `close_document` (discards unsaved changes), `capture_views` (export standard-view PNGs — default ISOMETRIC/FRONT/TOP — to `workspace/screenshots` or a given `outputDir`), `list_documents`.

**Neutral-format import:** `OpenDoc6` **cannot** open STEP/IGES — it fails with `swFileRequiresRepairError` (2097152), which is misleading; the file is fine. Import goes through `ISldWorks::LoadFile4(path, "r", importData, err)` with `importData` from `GetImportFileData`. `import_file` handles this, and forces 3D Interconnect (`swMultiCAD_Enable3DInterconnect` = **691**) OFF for the duration: with it ON the file lands as an associative `<file>.STEP<1>` `[MBimport]` feature that cannot be feature-recognized or parametrically edited; with it OFF you get a dumb `Imported1` `[BaseBody]` solid. Import diagnostics prefs (690, 291) are suppressed so nothing can raise a blocking dialog. All prefs are restored afterwards. Pass `linked: true` to deliberately keep the associative form.

**Feature recognition (`recognize_features`):** turns an imported dumb solid into a parametric tree. FeatureWorks ships with SOLIDWORKS at `fworks\fworks.dll` but is not loaded by default and needs Professional/Premium — `LoadAddIn(dll)` then `GetAddInObject("FeatureWorks.FeatureWorksApp")` (that exact ProgID; the obvious guesses return `None`). `IFeatureWorksApp` = `RecognizeFeatureAutomatic(mask)` → count, then `CreateFeatures(opts)` → bool. Mask bits: EXTRUDE 1, **VOLUME 2**, REVOLVE 4, HOLES 8, CHAMFER_FILLET 16, RIBS 32.

- **Keep VOLUME in the mask** — it finds the base feature. Measured: a plate with a hole and a fillet recognized 0 features without it, 3 with it.
- Recovered features are genuinely drivable: `set_parameter("D1@Fillet1", …)` rebuilds and moves the volume as expected.
- **Recognized sketches are constrained but NOT dimensioned** — there are no `D<i>@Sketch<n>` dimensions, so cut/boss *profiles* cannot be driven numerically. Change those by editing sketch geometry or by direct face editing.
- Cost: ~6s on a simple part, ~2.5 min on a 435-face one. Volume is preserved to ~0.001%.

### Assembly Tools

`new_assembly`, `insert_component` (pre-opens the part file, re-activates the assembly, AddComponent5; SolidWorks centers the component's **bounding box** at the drop point — the returned `actualPosition` is the component origin; first component is auto-fixed), `add_mate` (COINCIDENT, CONCENTRIC, PERPENDICULAR, PARALLEL, TANGENT, DISTANCE, ANGLE, LOCK; entities are either component planes `{"plane": "Front", "component": "comp:x-1"}` or coordinate picks `{"entityType": "FACE", "x":…, "y":…, "z":…}` in assembly-space mm), `edit_mate` (change a DISTANCE/ANGLE mate's value; rebuilds and returns updated component positions — mate dims are regular dimensions named `D1@<MateName>`), `check_interference` (overlap volumes + components involved), `suppress_component`, `list_components`, `list_mates`, `get_assembly_mass_properties` (kg + grams; optional `coordinateSystem`). `add_mate` also supports GEAR (mateType GEAR + `gearRatioNumerator`/`gearRatioDenominator`). WIDTH mates are not yet implemented.

**Assembly workflow:** build parts → `save_document` each → `new_assembly` → `insert_component` (first is fixed) → position with mates, not coordinates (the Transform2 setter is unavailable via late-bound COM). Coordinates returned by part-level `get_faces` are in PART space — offset them by the component's position from `list_components` when coordinate-picking mate faces.

**Recommended workflow:** After creating geometry, call `get_body_info` for an overview, then `get_faces` or `get_edges` to find exact coordinates for fillet, chamfer, shell, draft, and pattern operations. The sample points and midpoints returned by these tools are guaranteed to be on/near the geometry and can be passed directly to selection-based tools.

### Feature Tree Tools

`get_feature_tree` (the design timeline as structured JSON — build order, type, tracked ID, suppression, folder nesting, and absorbed sub-features such as the sketch consumed by an extrude; prefer it over `list_features`, which returns unstructured text), `rename_feature` (`IFeature.Name` is a settable property; the tracker is re-keyed in the same call so `feat:Boss-Extrude1` becomes `feat:Base Plate` and sketch-entity IDs / consuming features follow), `create_feature_folder`, `move_to_folder`.

**Naming is encouraged, not just possible.** Auto-generated names (`Boss-Extrude7`, `Sketch12`) make a model unreadable to a later agent and to the human who opens it. `rename_feature`'s description tells agents to name each feature as they create it, and `get_feature_tree` returns a `hint` listing features that still carry default names.

**Tree traversal gotchas:** `IModelDoc2::FirstFeature` + `GetNextFeature` walks the timeline, but absorbed sketches and foldered features **also appear in that linear walk**, so they must be de-duplicated against what was already emitted as a sub-feature or folder child. Descend into absorbed children with `GetFirstSubFeature`/**`GetNextSubFeature`** — calling `GetNextFeature` on a sub-feature rejoins the top-level chain and the traversal never terminates (this hung a test run). Folder contents come from `IFeature::GetSpecificFeature2()` → `IFeatureFolder::GetFeatures()`.

**Folders — what works and what does not (measured on SW2025 Student Edition):**

- ✅ `InsertFeatureTreeFolder2(2)` = **Containing** wraps the current selection. This is the only reliable way to group features, so **decide a folder's membership when you create it** and pass the full `features` list.
- ✅ `InsertFeatureTreeFolder2(1)` = **EmptyBefore** creates an empty folder, but it is inserted *above the current selection* and returns `None` if nothing is selected — the tool anchors it on the last feature automatically.
- ❌ `MoveToFolder(folderName, itemName, moveAfterFolder)` returns **False** in every case tested: into an empty folder, into a populated folder, and folder-into-folder, with either `moveAfterFolder` value. `move_to_folder` is kept so the failure is explicit rather than silent.
- ❌ **Folders cannot be nested.** `MoveToFolder` refuses a folder child and `IFeatureManager::InsertSubFolder` resolves to a property returning `None`. Use several well-named top-level folders instead of a hierarchy.

**Folder end tags:** every folder adds a closing pseudo-feature named `<Folder>___EndTag___` to the linear walk. It is not a design step — filter it out of any traversal (`get_feature_tree` does).

### State Query Tools

`get_state` (session state for the active document: tracked features/sketches/entities/refGeo — plus live enrichment: bounding box + face/edge counts, per-sketch `constrainedStatus` (FULLY_DEFINED/UNDER_DEFINED), active configuration, open documents, and components/mates for assemblies; `detail: "full"` adds feature parent/child dependencies; all COM enrichment is best-effort so `get_state` never fails), `get_entity` (detailed info about a single object by its tracked ID), `get_sketch_entities` (list all entities in a specific sketch with their types and coordinates).

**Dimensioning tools:** `sketch_dimension` adds a smart dimension to selected sketch entities (1 entity for length/radius, 2 for between-distance), with an optional `value` parameter to set the driving value (mm for linear dimensions, degrees for angular dimensions). The dimension type is auto-detected via `IDisplayDimension.Type2`; angular values are converted to radians internally, linear values to meters. `set_dimension_value` modifies an existing dimension by selecting it at its text position. `AddDimension2` triggers a blocking "Modify" dialog; this is handled by a background thread that auto-dismisses the dialog via `win32gui` (finds window class `#32770` title "Modify", sends Enter). `AddToDB=True` / `DisplayWhenAdded=False` reduce UI overhead.

**Hole Wizard (flagged):** May trigger a blocking PropertyManager dialog similar to the dimensioning issue. Uses `AddToDB=True` / `DisplayWhenAdded=False` as mitigation. If it fails, use sketch circle + cut-extrude as a workaround.

**SolidWorks COM:** Uses `win32com.client` via `pywin32`. `connection.py` attempts to connect to an already-running SolidWorks instance first, then launches a new one. Template paths are discovered by glob (`C:\ProgramData\SOLIDWORKS\SOLIDWORKS *\templates\Part.prtdot` / `Assembly.asmdot`), preferring the template matching the running SW version (multiple versions' templates can coexist).

**Late-bound COM pitfalls (IMPORTANT):**
- Never test a property result with `callable()` — CDispatch COM objects are ALWAYS callable (calling one invokes its default dispatch method → 'Member not found'). Use `com_utils.com_prop(obj, name)`, which only invokes `types.MethodType` wrappers.
- Save with `Extension.SaveAs(path, 0, 1, VARIANT(VT_DISPATCH, None), errs, warns)` — options **1** = Silent. Options **2** = Copy: writes a detached copy and leaves the session doc untitled (breaks activation/scoping).
- `OpenDoc6`/`ActivateDoc3`/`AddMate5` take `VARIANT(VT_BYREF | VT_I4, 0)` byref error args.
- `AddComponent5` returns None unless the part file is already open in memory.

**Key COM APIs:**
- `FeatureExtrusion2` (23 params) - see `modeling.py`
- `FeatureCut4` (27 params) - see `modeling.py`
- `FeatureRevolve2` (20 params) - see `features.py` / `cut_features.py`
- `InsertProtrusionSwept4` / `InsertCutSwept5` - see `features.py` / `cut_features.py`
- `InsertProtrusionBlend2` (18 params for SW2025) / `InsertCutBlend2` (18 params for SW2025) - see `features.py` / `cut_features.py`
- `FeatureFillet3`, `InsertFeatureChamfer`, `InsertFeatureShell`, `InsertFeatureDraft` - see `applied_features.py`
- `FeatureLinearPattern4` (20 params for SW2025 — 11/12-param forms raise 'Parameter not optional'), `FeatureCircularPattern4`, `InsertMirrorFeature2` - see `patterns.py`
- `InsertRefPlane`, `InsertRefAxis`, `InsertReferencePoint`, `InsertCoordinateSystem` - see `reference_geometry.py`
- `AddComponent5`, `AddMate5` (15 params), `GetComponents`, `IComponent2::Transform2` (getter only), MateGroup sub-feature traversal - see `assembly.py`
- `IModelDocExtension::SaveAs`, `OpenDoc6`, `ActivateDoc3`, `QuitDoc`, `GetDocuments` - see `document_manager.py` / `connection.py`
- `IFace2::GetFeature`, `IFeature::GetParents` / `GetChildren`, `ISketch::GetConstrainedStatus` (3=fully defined, 2=under defined) - see `geometry_query.py` / `state_query.py`
- `IBody2::GetBodyBox`, `IBody2::GetFaces`, `IBody2::GetEdges`, `IFace2::GetArea`, `IFace2::GetUVBounds`, `ISurface::Evaluate`, `IEdge::GetStartVertex`, `IEdge::GetEndVertex`, `IEdge::GetClosestPointOn` - see `geometry_query.py`

**Logging:** Written to `solidworks_mcp.log` in the project root and to stderr (stdout is the MCP transport). Log level is INFO.

## Platform Constraint

This project only runs on Windows with SolidWorks installed. There is no mock/stub for the COM layer—any test or development requires a live SolidWorks instance.
