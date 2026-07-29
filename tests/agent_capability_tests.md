# SolidWorks MCP Agent Capability Tests

These tests evaluate an AI agent's ability to use the SolidWorks MCP server tools. Each test is self-contained and can be copy-pasted into a fresh Claude session connected to the MCP server. Tests are ordered from basic to advanced.

**How to use:** Copy a single test block (everything between the horizontal rules) into a new Claude conversation that has the SolidWorks MCP server connected. Verify the result in SolidWorks matches the expected outcome.

**Prerequisites:** SolidWorks must be running on the machine. The MCP server must be registered in Claude Desktop's config.

**Conventions:**
- Every test that produces a solid body starts with `solidworks_new_part` for consistency.
- Every test that produces a solid body ends with `solidworks_get_mass_properties` and reports the expected volume so the result can be verified numerically.

---

## Test 1: Basic Cube (Fundamental Workflow)

**What it tests:** The core workflow — creating a new part, opening a sketch, drawing a rectangle, and extruding.

**Prompt:**

```
Create a new part in SolidWorks. On the Front plane, sketch a 100mm x 100mm rectangle centered at the origin, then extrude it 100mm to create a cube. After creating the solid, report the volume using mass properties.
```

**Expected outcome:**
- A new part document is created
- A sketch is opened on the Front plane
- A 100mm x 100mm rectangle is drawn centered at (0, 0)
- An extrusion of 100mm depth is created
- Result: a cube visible in SolidWorks
- **Expected volume: 1,000,000 mm^3**

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_rectangle` with width=100, height=100, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=100
5. `solidworks_get_mass_properties`

---

## Test 2: Circle Extrusion (Cylinder)

**What it tests:** Drawing a circle and extruding it into a cylinder.

**Prompt:**

```
Create a new part. Draw a cylinder with a diameter of 50mm and a height of 75mm. Use the Top plane for the sketch. Report the volume using mass properties.
```

**Expected outcome:**
- A circle with radius 25mm is sketched on the Top plane
- Extruded 75mm to form a cylinder
- **Expected volume: ~147,262 mm^3** (pi x 25^2 x 75)

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Top"
3. `solidworks_sketch_circle` with radius=25
4. `solidworks_create_extrusion` with depth=75
5. `solidworks_get_mass_properties`

---

## Test 3: Hexagonal Prism (Polygon + Extrusion)

**What it tests:** Using the polygon tool to create a regular hexagon and extruding it.

**Prompt:**

```
Create a new part. On the Front plane, draw a regular hexagon with a circumscribed radius of 30mm (center to vertex) and extrude it 40mm tall. Report the volume.
```

**Expected outcome:**
- A 6-sided polygon with radius 30mm at the origin
- Extruded 40mm
- Result: a hexagonal prism
- **Expected volume: ~93,531 mm^3** (3*sqrt(3)/2 x 30^2 x 40)

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_polygon` with radius=30, numSides=6
4. `solidworks_create_extrusion` with depth=40
5. `solidworks_get_mass_properties`

---

## Test 4: Elliptical Disc

**What it tests:** Drawing an ellipse and extruding it into a thin disc.

**Prompt:**

```
Create a new part. Draw an ellipse with a semi-major axis of 40mm and a semi-minor axis of 25mm, centered at the origin on the Front plane. Extrude it 5mm thick. Report the volume.
```

**Expected outcome:**
- An ellipse centered at (0, 0) with majorRadius=40, minorRadius=25
- Extruded 5mm
- Result: a flat elliptical disc
- **Expected volume: ~15,708 mm^3** (pi x 40 x 25 x 5)

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_ellipse` with centerX=0, centerY=0, majorRadius=40, minorRadius=25
4. `solidworks_create_extrusion` with depth=5
5. `solidworks_get_mass_properties`

---

## Test 5: Slot Feature

**What it tests:** Drawing a slot shape and extruding it.

**Prompt:**

```
Create a new part. Draw a slot that runs horizontally from (-30, 0) to (30, 0) with a total width of 20mm on the Front plane. Extrude it 10mm. Report the volume.
```

**Expected outcome:**
- A straight slot from (-30, 0) to (30, 0) with width=20
- Extruded 10mm
- Result: a stadium/slot-shaped solid
- **Expected volume: ~15,142 mm^3** (rectangle 60x20 + two semicircles of radius 10, times 10mm depth)

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_slot` with x1=-30, y1=0, x2=30, y2=0, width=20
4. `solidworks_create_extrusion` with depth=10
5. `solidworks_get_mass_properties`

---

## Test 6: Two Rectangles with Spacing (Spatial Awareness)

**What it tests:** The spatial positioning system — drawing a second shape relative to the first using the `spacing` parameter.

**Prompt:**

```
On the Front plane, draw two rectangles side by side. The first rectangle should be 40mm x 30mm centered at the origin. The second rectangle should be 40mm x 30mm placed 10mm to the right of the first one (10mm gap between them). Do not extrude, just create the sketch.
```

**Expected outcome:**
- First rectangle: 40x30mm at (0, 0)
- Second rectangle: 40x30mm positioned with a 10mm gap to the right of the first
  - The second rectangle's center should be at approximately (50, 0) — first right edge at 20, plus 10mm gap, plus 20mm half-width = center at 50
- Both shapes visible in the sketch

**Tools that must be called:**
1. `solidworks_create_sketch` with plane "Front"
2. `solidworks_sketch_rectangle` with width=40, height=30, centerX=0, centerY=0
3. `solidworks_sketch_rectangle` with width=40, height=30, spacing=10

---

## Test 7: Relative Positioning (Circle Offset from Rectangle)

**What it tests:** Using `relativeX`/`relativeY` to place a circle relative to a previous rectangle.

**Prompt:**

```
On the Front plane, draw a 60mm x 40mm rectangle at the origin. Then draw a circle with radius 15mm offset 80mm to the right and 20mm above the rectangle's center. Don't extrude.
```

**Expected outcome:**
- Rectangle: 60x40mm at (0, 0)
- Circle: radius 15mm at position (80, 20) — offset from rectangle center
- Both shapes in the sketch

**Tools that must be called:**
1. `solidworks_create_sketch` with plane "Front"
2. `solidworks_sketch_rectangle` with width=60, height=40, centerX=0, centerY=0
3. `solidworks_sketch_circle` with radius=15, relativeX=80, relativeY=20

---

## Test 8: Query Last Shape Info

**What it tests:** Using `solidworks_get_last_shape_info` to inspect the spatial tracking data.

**Prompt:**

```
On the Front plane, draw a 50mm x 30mm rectangle centered at (10, 20). Then tell me the exact bounding box and position information of that rectangle using the shape info tool.
```

**Expected outcome:**
- Rectangle drawn at (10, 20)
- Agent calls `solidworks_get_last_shape_info` and reports back:
  - Center: (10.0, 20.0)
  - Left: -15.0, Right: 35.0, Bottom: 5.0, Top: 35.0
  - Size: 50mm x 30mm

**Tools that must be called:**
1. `solidworks_create_sketch` with plane "Front"
2. `solidworks_sketch_rectangle` with width=50, height=30, centerX=10, centerY=20
3. `solidworks_get_last_shape_info`

---

## Test 9: Lines and Arcs

**What it tests:** Drawing lines and arcs with explicit coordinates.

**Prompt:**

```
On the Front plane, create a sketch with:
1. A straight line from (0, 0) to (50, 0)
2. A 3-point arc starting at (50, 0), ending at (50, 40), with the midpoint of the arc at (70, 20)
3. A straight line from (50, 40) back to (0, 40)
4. A straight line from (0, 40) back to (0, 0) to close the profile

Don't extrude yet.
```

**Expected outcome:**
- Four sketch entities forming a closed profile
- A rectangular-ish shape with one side replaced by an arc bulging outward
- All coordinates in mm

**Tools that must be called:**
1. `solidworks_create_sketch` with plane "Front"
2. `solidworks_sketch_line` with x1=0, y1=0, x2=50, y2=0
3. `solidworks_sketch_arc` with mode="3point", x1=50, y1=0, x2=50, y2=40, x3=70, y3=20
4. `solidworks_sketch_line` with x1=50, y1=40, x2=0, y2=40
5. `solidworks_sketch_line` with x1=0, y1=40, x2=0, y2=0

---

## Test 10: Spline Curve

**What it tests:** Creating a spline through multiple points.

**Prompt:**

```
On the Front plane, draw a smooth spline curve through these points (all in mm):
(0, 0), (20, 15), (40, -10), (60, 5), (80, 0)

Don't extrude. Just create the sketch with the spline.
```

**Expected outcome:**
- A smooth spline passing through all 5 points
- Visible as a wavy/smooth curve in the sketch

**Tools that must be called:**
1. `solidworks_create_sketch` with plane "Front"
2. `solidworks_sketch_spline` with points array containing the 5 points

---

## Test 11: Sketch Text

**What it tests:** Inserting text into a sketch.

**Prompt:**

```
On the Front plane, create a sketch and insert the text "SOLIDWORKS" at position (0, 0) with a font height of 10mm.
```

**Expected outcome:**
- Sketch text reading "SOLIDWORKS" placed at origin
- Text height set to 10mm

**Tools that must be called:**
1. `solidworks_create_sketch` with plane "Front"
2. `solidworks_sketch_text` with x=0, y=0, text="SOLIDWORKS", height=10

---

## Test 12: Construction Geometry

**What it tests:** Drawing a centerline (auto-construction) and toggling a normal line to construction.

**Prompt:**

```
On the Front plane, create a sketch with:
1. A vertical centerline from (0, -50) to (0, 50)
2. A horizontal line from (-30, 0) to (30, 0)
3. Toggle that horizontal line to construction geometry

Don't extrude.
```

**Expected outcome:**
- A vertical centerline (dashed, construction by default)
- A horizontal line that is toggled to construction geometry (also dashed)
- Neither line would form part of an extrusion profile

**Tools that must be called:**
1. `solidworks_create_sketch` with plane "Front"
2. `solidworks_sketch_centerline` with x1=0, y1=-50, x2=0, y2=50
3. `solidworks_sketch_line` with x1=-30, y1=0, x2=30, y2=0
4. `solidworks_sketch_toggle_construction` with x=0, y=0 (point on the line)

---

## Test 13: Sketch Constraint (Parallel Lines)

**What it tests:** Drawing two lines and applying a geometric constraint.

**Prompt:**

```
On the Front plane, draw two lines:
1. Line from (0, 0) to (50, 10)
2. Line from (0, 30) to (50, 25)

Then apply a PARALLEL constraint between them. Don't extrude.
```

**Expected outcome:**
- Two lines drawn
- After the parallel constraint is applied, both lines should become parallel
- SolidWorks adjusts the second line to match the angle of the first (or vice versa)

**Tools that must be called:**
1. `solidworks_create_sketch` with plane "Front"
2. `solidworks_sketch_line` with x1=0, y1=0, x2=50, y2=10
3. `solidworks_sketch_line` with x1=0, y1=30, x2=50, y2=25
4. `solidworks_sketch_constraint` with constraintType="PARALLEL" and entityPoints on both lines

---

## Test 14: Block with a Hole (Extrude + Cut-Extrude)

**What it tests:** The full additive + subtractive workflow — creating a solid body, then cutting a hole through it.

**Prompt:**

```
Create a new part. Make a rectangular block that is 80mm wide, 60mm tall, and 30mm deep. Then cut a circular hole through the center of the front face. The hole should have a diameter of 20mm and go 30mm deep (all the way through). Report the volume.
```

**Expected outcome:**
- A rectangular block (80x60mm sketch on Front plane, extruded 30mm)
- A circular hole (radius 10mm) cut through the center of the front face
- The cut should go all the way through (30mm deep)
- **Expected volume: ~134,575 mm^3** (80x60x30 - pi x 10^2 x 30)

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_rectangle` with width=80, height=60, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=30
5. `solidworks_create_sketch` with faceX=0, faceY=0, faceZ=0
6. `solidworks_sketch_circle` with radius=10, centerX=0, centerY=0
7. `solidworks_create_cut_extrusion` with depth=30
8. `solidworks_get_mass_properties`

---

## Test 15: Mass Properties Verification

**What it tests:** Creating a known geometry and querying its mass properties with exact expected values.

**Prompt:**

```
Create a new part. Make a 100mm x 100mm x 100mm cube (sketch on Front plane, centered at origin, extruded 100mm). Then get the mass properties. Report the volume, surface area, and center of mass.
```

**Expected outcome:**
- A 100mm cube is created
- Mass properties are retrieved and reported
- **Expected volume: 1,000,000 mm^3**
- **Expected surface area: 60,000 mm^2**
- **Expected center of mass: approximately (50, 50, 50) mm**

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_rectangle` with width=100, height=100, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=100
5. `solidworks_get_mass_properties`

---

## Test 16: Right Plane Sketch

**What it tests:** Using a non-default reference plane.

**Prompt:**

```
Create a new part. Sketch a 40mm radius circle on the Right plane and extrude it 60mm. Report the volume.
```

**Expected outcome:**
- Sketch created on the Right plane (YZ plane)
- Circle with radius 40mm
- Extruded 60mm along the X axis
- Result: a cylinder oriented along X
- **Expected volume: ~301,593 mm^3** (pi x 40^2 x 60)

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Right"
3. `solidworks_sketch_circle` with radius=40
4. `solidworks_create_extrusion` with depth=60
5. `solidworks_get_mass_properties`

---

## Test 17: Pentagon with Inscribed Radius

**What it tests:** Polygon with the `inscribed` flag set to true.

**Prompt:**

```
Create a new part. On the Front plane, draw a regular pentagon with an inscribed circle radius of 25mm (the radius should measure to the midpoint of each side, not to a vertex). Center it at the origin. Extrude 15mm. Report the volume.
```

**Expected outcome:**
- A 5-sided regular polygon with inscribed=true and radius=25
- Centered at origin
- Extruded 15mm
- **Expected volume: ~34,057 mm^3** (5 x 25^2 x tan(pi/5) x 15)

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_polygon` with numSides=5, radius=25, inscribed=true
4. `solidworks_create_extrusion` with depth=15
5. `solidworks_get_mass_properties`

---

## Test 18: Center-Point Arc

**What it tests:** Using the arc tool in center-point mode.

**Prompt:**

```
On the Front plane, draw an arc using center-point mode. The arc center should be at (0, 0), with the start point at (30, 0) and the end point at (0, 30). Don't extrude.
```

**Expected outcome:**
- A quarter-circle arc with radius 30mm
- Centered at origin, sweeping from (30, 0) to (0, 30) counter-clockwise
- Visible as a 90-degree arc in the sketch

**Tools that must be called:**
1. `solidworks_create_sketch` with plane "Front"
2. `solidworks_sketch_arc` with mode="center", centerX=0, centerY=0, x1=30, y1=0, x2=0, y2=30

---

## Test 19: Rotated Ellipse

**What it tests:** Creating an ellipse with a rotation angle.

**Prompt:**

```
On the Front plane, draw an ellipse centered at the origin with a semi-major axis of 50mm and semi-minor axis of 20mm, rotated 45 degrees counterclockwise. Don't extrude.
```

**Expected outcome:**
- An ellipse at (0, 0)
- Major axis 50mm, minor axis 20mm
- Tilted 45 degrees from the horizontal
- The long axis should run from bottom-left to upper-right

**Tools that must be called:**
1. `solidworks_create_sketch` with plane "Front"
2. `solidworks_sketch_ellipse` with centerX=0, centerY=0, majorRadius=50, minorRadius=20, angle=45

---

## Test 20: Multi-Shape Sketch with Mixed Positioning

**What it tests:** Combining absolute and relative positioning in a single sketch with multiple shape types.

**Prompt:**

```
On the Front plane, create a sketch with three shapes in a horizontal row:
1. A 30mm x 30mm square centered at (-50, 0)
2. A circle with radius 15mm, placed 10mm to the right of the square (10mm gap)
3. A regular hexagon with radius 15mm, placed 10mm to the right of the circle (10mm gap)

Don't extrude. Just create the sketch with all three shapes.
```

**Expected outcome:**
- Square at (-50, 0): 30x30mm
- Circle 10mm to the right of the square's right edge, same vertical center
  - Square right edge = -35, so circle center at -35 + 10 + 15 = -10, y = 0
- Hexagon 10mm to the right of the circle's right edge, same vertical center
  - Circle right edge = 5, so hexagon center at 5 + 10 + 15 = 30, y = 0
- Three shapes in a neat row with equal gaps

**Tools that must be called:**
1. `solidworks_create_sketch` with plane "Front"
2. `solidworks_sketch_rectangle` with width=30, height=30, centerX=-50, centerY=0
3. `solidworks_sketch_circle` with radius=15, spacing=10
4. `solidworks_sketch_polygon` with radius=15, numSides=6, spacing=10

---

## Test 21: Sketch Point as Reference

**What it tests:** Creating sketch points for reference purposes.

**Prompt:**

```
On the Front plane, place three sketch points at (0, 0), (25, 25), and (50, 0). Then draw a line connecting (0, 0) to (50, 0). Don't extrude.
```

**Expected outcome:**
- Three sketch points visible at the specified coordinates
- A line from (0, 0) to (50, 0)
- The sketch points at (0, 0) and (50, 0) should visually coincide with the line endpoints

**Tools that must be called:**
1. `solidworks_create_sketch` with plane "Front"
2. `solidworks_sketch_point` with x=0, y=0
3. `solidworks_sketch_point` with x=25, y=25
4. `solidworks_sketch_point` with x=50, y=0
5. `solidworks_sketch_line` with x1=0, y1=0, x2=50, y2=0

---

## Test 22: Reverse Extrusion Direction

**What it tests:** Using the `reverse` flag on extrusion.

**Prompt:**

```
Create a new part. On the Front plane, draw a 40mm x 40mm square centered at the origin. Extrude it 50mm in the reverse direction (behind the Front plane). Report the volume.
```

**Expected outcome:**
- A 40x40mm rectangle on the Front plane
- Extruded 50mm in the reverse direction (negative Z)
- The solid should extend behind the Front plane
- **Expected volume: 80,000 mm^3** (40 x 40 x 50)

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_rectangle` with width=40, height=40, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=50, reverse=true
5. `solidworks_get_mass_properties`

---

## Test 23: Corner-Defined Rectangle

**What it tests:** Defining a rectangle by two corner points instead of center + dimensions.

**Prompt:**

```
Create a new part. On the Front plane, draw a rectangle with one corner at (10, 10) and the opposite corner at (60, 40). Extrude it 20mm. Report the volume.
```

**Expected outcome:**
- A rectangle from corner (10, 10) to corner (60, 40)
- Width: 50mm, Height: 30mm
- Extruded 20mm
- **Expected volume: 30,000 mm^3** (50 x 30 x 20)

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_rectangle` with x1=10, y1=10, x2=60, y2=40
4. `solidworks_create_extrusion` with depth=20
5. `solidworks_get_mass_properties`

---

## Test 24: Complex Profile — Bracket Shape

**What it tests:** Agent's ability to decompose a real-world shape description into individual sketch entities and produce a closed profile.

**Prompt:**

```
Create a new part. Make an L-shaped bracket in SolidWorks. The vertical arm should be 60mm tall and 15mm wide. The horizontal arm should extend 40mm to the right and be 15mm wide. The overall shape looks like a capital "L". Sketch it on the Front plane using lines, then extrude it 10mm. Report the volume.

Use these coordinates for the outline:
- Start at (0, 0)
- Right to (40, 0)
- Up to (40, 15)
- Left to (15, 15)
- Up to (15, 60)
- Left to (0, 60)
- Down back to (0, 0)
```

**Expected outcome:**
- An L-shaped closed profile made of 6 lines
- Extruded 10mm to form a 3D L-bracket
- Profile should be fully closed for the extrusion to succeed
- **Expected volume: 12,750 mm^3** ((40x15 + 15x45) x 10)

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. Six `solidworks_sketch_line` calls forming the closed L-shape
4. `solidworks_create_extrusion` with depth=10
5. `solidworks_get_mass_properties`

---

## Test 25: Multiple Constraints

**What it tests:** Applying multiple different constraint types in a single sketch.

**Prompt:**

```
On the Front plane:
1. Draw a horizontal line from (0, 0) to (50, 5) — note it's slightly angled
2. Draw a vertical line from (60, 0) to (65, 40) — also slightly off-vertical
3. Apply a HORIZONTAL constraint to the first line
4. Apply a VERTICAL constraint to the second line

Don't extrude.
```

**Expected outcome:**
- After applying HORIZONTAL, the first line should become perfectly horizontal (both endpoints at the same Y)
- After applying VERTICAL, the second line should become perfectly vertical (both endpoints at the same X)
- SolidWorks will snap the endpoints to satisfy the constraints

**Tools that must be called:**
1. `solidworks_create_sketch` with plane "Front"
2. `solidworks_sketch_line` (first line)
3. `solidworks_sketch_line` (second line)
4. `solidworks_sketch_constraint` with constraintType="HORIZONTAL" and entityPoints on the first line
5. `solidworks_sketch_constraint` with constraintType="VERTICAL" and entityPoints on the second line

---

## Test 26: Washer (Concentric Circles + Extrude + Cut)

**What it tests:** A practical part requiring additive extrusion followed by a subtractive cut to create a washer/ring shape.

**Prompt:**

```
Create a new part. Make a washer (flat ring):
1. On the Front plane, sketch a circle with outer radius 20mm centered at the origin. Extrude it 3mm.
2. Then create a sketch on the front face of the disc (at z=0) and draw a circle with radius 8mm centered at the origin. Cut-extrude it 3mm through the disc to create the hole.

Report the final volume.
```

**Expected outcome:**
- A flat disc (outer radius 20mm, 3mm thick)
- A through-hole in the center (radius 8mm)
- Result: a washer shape
- **Expected volume: ~3,167 mm^3** (pi x (20^2 - 8^2) x 3)

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_circle` with radius=20, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=3
5. `solidworks_create_sketch` with faceX=0, faceY=0, faceZ=0
6. `solidworks_sketch_circle` with radius=8, centerX=0, centerY=0
7. `solidworks_create_cut_extrusion` with depth=3
8. `solidworks_get_mass_properties`

---

## Test 27: Explicit New Part on Top Plane

**What it tests:** Using `solidworks_new_part` explicitly and sketching on a non-Front plane.

**Prompt:**

```
Create a new blank part document. Then open a sketch on the Top plane, draw a 35mm x 35mm square at the origin, and extrude it 35mm to make a cube. Report the volume.
```

**Expected outcome:**
- `solidworks_new_part` is called first
- Sketch on Top plane
- 35mm cube created
- **Expected volume: 42,875 mm^3** (35 x 35 x 35)

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Top"
3. `solidworks_sketch_rectangle` with width=35, height=35, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=35
5. `solidworks_get_mass_properties`

---

## Test 28: Exit Sketch Explicitly

**What it tests:** Using `solidworks_exit_sketch` independently (not as part of extrusion).

**Prompt:**

```
On the Front plane, draw a 50mm radius circle at the origin. Exit the sketch without extruding. Then tell me you've exited the sketch successfully.
```

**Expected outcome:**
- Circle drawn in sketch
- `solidworks_exit_sketch` called explicitly
- Agent confirms sketch was exited
- No extrusion is performed

**Tools that must be called:**
1. `solidworks_create_sketch` with plane "Front"
2. `solidworks_sketch_circle` with radius=50
3. `solidworks_exit_sketch`

---

## Test 29: Describe-and-Build (Natural Language Comprehension)

**What it tests:** Agent's ability to interpret a natural language description (no explicit coordinates) and choose appropriate tool parameters.

**Prompt:**

```
Create a new part. I need a simple phone stand. Create a rectangular base that's about 80mm wide, 50mm deep, and 5mm thick. Then add a vertical wall on one end that's about 80mm wide, 30mm tall, and 5mm thick — this wall will prop up the phone. Report the final volume.
```

**Expected outcome:**
- The agent should figure out the coordinate system and tool calls on its own
- A base plate created as an extrusion (e.g., 80x50mm rectangle, extruded 5mm)
- A vertical wall attached to one end (a second sketch on a face of the base, extruded upward)
- The result should look like a simple L-shaped phone stand
- **Expected volume: ~32,000 mm^3** (80x50x5 base + 80x30x5 wall = 20,000 + 12,000)

**Evaluation criteria:**
- Does the agent plan a reasonable multi-step approach?
- Does it choose correct planes/faces for each feature?
- Are the dimensions roughly matching the request?
- Does the final shape function as described?
- Does the reported volume approximate the expected value?

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_sketch` (base)
3. `solidworks_sketch_rectangle` (base profile)
4. `solidworks_create_extrusion` (base)
5. `solidworks_create_sketch` (wall — on a face)
6. `solidworks_sketch_rectangle` (wall profile)
7. `solidworks_create_extrusion` (wall)
8. `solidworks_get_mass_properties`

---

## Test 30: Error Recovery

**What it tests:** Agent's ability to handle and recover from errors (e.g., trying to extrude without a sketch).

**Prompt:**

```
Create a new part. Immediately try to extrude 50mm without creating a sketch first. After that fails, properly create a sketch on the Front plane with a 30mm x 30mm rectangle and extrude it 50mm. Report the volume.
```

**Expected outcome:**
- First extrusion attempt should fail (no sketch to extrude)
- Agent recognizes the error and recovers
- Agent creates a proper sketch with a rectangle
- Second extrusion succeeds
- Final result: a 30x30x50mm rectangular block
- **Expected volume: 45,000 mm^3** (30 x 30 x 50)

**Evaluation criteria:**
- Does the agent attempt the extrusion as requested?
- Does it handle the error gracefully?
- Does it successfully recover and complete the part?
- Does the reported volume match the expected value?

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_extrusion` with depth=50 (this should fail)
3. `solidworks_create_sketch` with plane "Front"
4. `solidworks_sketch_rectangle` with width=30, height=30, centerX=0, centerY=0
5. `solidworks_create_extrusion` with depth=50
6. `solidworks_get_mass_properties`

---

## Test 31: Comprehensive 2D Sketch (Every Sketch Tool)

**What it tests:** Every 2D sketch entity tool, every positioning mode, constraints, construction geometry, and shape info queries — all in one sketch. This is the ultimate sketch capability test.

**Prompt:**

```
Create a new part and open a sketch on the Front plane. Build the following sketch step by step. Do NOT extrude — this is a 2D sketch test only.

1. Draw a 60mm x 40mm rectangle centered at (-80, 0). This is the main reference shape.

2. Query the last shape info to confirm the rectangle's bounding box.

3. Draw a circle with radius 15mm, spaced 10mm to the right of the rectangle (use the spacing parameter).

4. Draw a regular octagon (8 sides) with radius 12mm, spaced 10mm to the right of the circle.

5. Draw an ellipse centered at (80, 0) with semi-major axis 25mm, semi-minor axis 12mm, rotated 30 degrees.

6. Draw a slot from (-80, -50) to (-30, -50) with width 12mm.

7. Draw a line from (0, -50) to (50, -50).

8. Draw a second line from (0, -65) to (50, -58) — intentionally slightly angled.

9. Apply a PARALLEL constraint between the two lines (step 7 and step 8).

10. Draw a 3-point arc from (60, -50) to (100, -50) with midpoint at (80, -35).

11. Draw a center-point arc with center (80, -70), start (95, -70), end (80, -55).

12. Draw a spline through these points: (-80, 50), (-60, 65), (-40, 55), (-20, 70), (0, 50).

13. Draw a vertical centerline from (40, 30) to (40, 70).

14. Draw a horizontal line from (20, 50) to (60, 50).

15. Toggle that horizontal line (step 14) to construction geometry.

16. Place a sketch point at (0, 0) as a reference origin marker.

17. Insert the text "TEST" at position (-80, 80) with a height of 8mm.

18. Draw a 50mm x 20mm rectangle positioned 15mm to the right of the ellipse from step 5 (use relativeX=15 to offset from the ellipse's center).

19. Query the last shape info to confirm the final rectangle's position.

After all entities are drawn, exit the sketch.
```

**Expected outcome:**

This sketch should contain ALL of the following entity types:
- **Rectangle** (steps 1, 18) — absolute positioning and relative positioning
- **Circle** (step 3) — spacing-based positioning
- **Polygon** (step 4) — spacing-based positioning, 8 sides
- **Ellipse** (step 5) — with rotation angle
- **Slot** (step 6) — explicit coordinates
- **Line** (steps 7, 8, 14) — explicit coordinates
- **Constraint** (step 9) — PARALLEL between two lines
- **3-point arc** (step 10) — explicit coordinates
- **Center-point arc** (step 11) — center + endpoints
- **Spline** (step 12) — 5 control points
- **Centerline** (step 13) — construction geometry
- **Toggle construction** (step 15) — convert normal line to construction
- **Point** (step 16) — reference point
- **Text** (step 17) — sketch annotation
- **get_last_shape_info** (steps 2, 19) — spatial tracking queries
- **exit_sketch** (final step) — explicit sketch exit

**Positioning modes covered:**
- Absolute centerX/centerY (steps 1, 5)
- Spacing from last shape (steps 3, 4)
- relativeX/relativeY offset (step 18)
- Explicit x1,y1,x2,y2 coordinates (steps 6, 7, 8, 10, 11, 13, 14)

**Detailed position verification:**
- Step 1 rectangle: center (-80, 0), bounds [-110, -50] x [-20, 20]
- Step 3 circle: right edge of rectangle is -50, so circle center = -50 + 10 + 15 = -25, y = 0
- Step 4 octagon: right edge of circle is -10, so octagon center = -10 + 10 + 12 = 12, y = 0
- Step 18 rectangle: ellipse center is (80, 0), so rect center = (80 + 15, 0) = (95, 0)

**Tools that must be called:**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_rectangle` — centerX=-80, centerY=0, width=60, height=40
4. `solidworks_get_last_shape_info`
5. `solidworks_sketch_circle` — radius=15, spacing=10
6. `solidworks_sketch_polygon` — numSides=8, radius=12, spacing=10
7. `solidworks_sketch_ellipse` — centerX=80, centerY=0, majorRadius=25, minorRadius=12, angle=30
8. `solidworks_sketch_slot` — x1=-80, y1=-50, x2=-30, y2=-50, width=12
9. `solidworks_sketch_line` — x1=0, y1=-50, x2=50, y2=-50
10. `solidworks_sketch_line` — x1=0, y1=-65, x2=50, y2=-58
11. `solidworks_sketch_constraint` — constraintType="PARALLEL", entityPoints on both lines
12. `solidworks_sketch_arc` — mode="3point", x1=60, y1=-50, x2=100, y2=-50, x3=80, y3=-35
13. `solidworks_sketch_arc` — mode="center", centerX=80, centerY=-70, x1=95, y1=-70, x2=80, y2=-55
14. `solidworks_sketch_spline` — 5 points
15. `solidworks_sketch_centerline` — x1=40, y1=30, x2=40, y2=70
16. `solidworks_sketch_line` — x1=20, y1=50, x2=60, y2=50
17. `solidworks_sketch_toggle_construction` — x=40, y=50
18. `solidworks_sketch_point` — x=0, y=0
19. `solidworks_sketch_text` — x=-80, y=80, text="TEST", height=8
20. `solidworks_sketch_rectangle` — relativeX=15, width=50, height=20
21. `solidworks_get_last_shape_info`
22. `solidworks_exit_sketch`

---

## Test 32: Revolve — Solid Cylinder (Boss/Base Features)

**What it tests:** Creating a solid of revolution using a closed profile and a centerline axis.

**Prompt:**

```
Create a new part. On the Front plane, draw a closed rectangular profile using 4 lines: (0, -25) to (20, -25), (20, -25) to (20, 25), (20, 25) to (0, 25), (0, 25) to (0, -25). Then draw a vertical centerline from (0, -50) to (0, 50). Revolve the sketch 360 degrees to create a solid cylinder. Report the volume.
```

**Expected outcome:**
- A closed rectangle from x=0..20, y=-25..25 drawn with 4 lines
- A vertical centerline along the Y-axis
- Full 360° revolve creates a solid cylinder of radius 20mm and height 50mm
- **Expected volume: ~62,832 mm^3** (pi x 20^2 x 50)

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_line` with x1=0, y1=-25, x2=20, y2=-25
4. `solidworks_sketch_line` with x1=20, y1=-25, x2=20, y2=25
5. `solidworks_sketch_line` with x1=20, y1=25, x2=0, y2=25
6. `solidworks_sketch_line` with x1=0, y1=25, x2=0, y2=-25
7. `solidworks_sketch_centerline` with x1=0, y1=-50, x2=0, y2=50
8. `solidworks_revolve` (angle=360)
9. `solidworks_get_mass_properties`

---

## Test 33: Sweep — Circular Rod (Boss/Base Features)

**What it tests:** Sweeping a profile sketch along a path sketch on a different plane.

**Prompt:**

```
Create a new part. On the Front plane, draw a circle with radius 8mm centered at the origin — this is the sweep profile. Exit the sketch. Then open a new sketch on the Right plane and draw a straight line from (0, 0) to (80, 0) — this is the sweep path. Sweep the profile (Sketch1) along the path (Sketch2) to create a rod. Report the volume.
```

**Expected outcome:**
- Sketch1 on Front plane: circle R=8 (profile cross-section)
- Sketch2 on Right plane: 80mm line (path, extends along world Z-axis)
- Sweep creates a cylindrical rod 80mm long with circular cross-section R=8
- **Expected volume: ~16,085 mm^3** (pi x 8^2 x 80)

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_circle` with radius=8, centerX=0, centerY=0
4. `solidworks_exit_sketch`
5. `solidworks_create_sketch` with plane "Right"
6. `solidworks_sketch_line` with x1=0, y1=0, x2=80, y2=0
7. `solidworks_sweep` with profileSketch="Sketch1", pathSketch="Sketch2"
8. `solidworks_get_mass_properties`

---

## Test 34: Loft — Truncated Cone (Boss/Base Features)

**What it tests:** Creating a lofted solid between two profiles on parallel planes (`create_sketch` accepts standard planes, custom reference planes like "Plane1"/"ref:Plane1", and model faces).

**Prompt:**

```
Create a new part. This test creates a truncated cone (frustum) using a loft.

Step 1 — Helper rod: On the Front plane, draw a circle with radius 1mm at the origin and extrude it 80mm. This gives us a face at z=80 for sketching.

Step 2 — First profile: On the Front plane, draw a circle with radius 30mm at the origin. Exit the sketch without extruding (this becomes Sketch2).

Step 3 — Second profile: Open a sketch on the back face of the helper rod at coordinates (0, 0, 80). Draw a circle with radius 10mm centered at (0, 0). Exit the sketch without extruding (this becomes Sketch3).

Step 4 — Loft: Create a loft between Sketch2 and Sketch3.

Report the volume.
```

**Expected outcome:**
- Helper rod: 1mm radius cylinder, 80mm long (fully contained within the final loft shape)
- Loft profile 1 (Sketch2): circle R=30 at z=0 on Front plane
- Loft profile 2 (Sketch3): circle R=10 at z=80 on the rod's back face
- Loft merges with the helper rod; since the rod (R=1) is fully inside the cone (narrowest R=10), the merged volume equals the cone volume
- Result: truncated cone from R=30 to R=10 over 80mm
- **Expected volume: ~108,909 mm^3** (pi x h/3 x (R1^2 + R1 x R2 + R2^2) = pi x 80/3 x (900 + 300 + 100))

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_circle` with radius=1, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=80
5. `solidworks_create_sketch` with plane "Front"
6. `solidworks_sketch_circle` with radius=30, centerX=0, centerY=0
7. `solidworks_exit_sketch`
8. `solidworks_create_sketch` with faceX=0, faceY=0, faceZ=80
9. `solidworks_sketch_circle` with radius=10, centerX=0, centerY=0
10. `solidworks_exit_sketch`
11. `solidworks_loft` with profileSketches=["Sketch2", "Sketch3"]
12. `solidworks_get_mass_properties`

---

## Test 35: Fillet — Rounded Cube Edges (Applied Features)

**What it tests:** Applying a constant-radius fillet to multiple edges selected by 3D coordinates.

**Prompt:**

```
Create a new part. On the Front plane, draw a 100mm x 100mm rectangle centered at the origin and extrude it 100mm to create a cube. Then apply a 10mm radius fillet to all 4 vertical edges (the edges running along the Z-axis at the corners). The 4 vertical edge midpoints are at (50, 50, 50), (-50, 50, 50), (-50, -50, 50), and (50, -50, 50). Report the volume.
```

**Expected outcome:**
- 100mm cube from (-50, -50, 0) to (50, 50, 100)
- 4 vertical edges filleted with R=10mm
- Each fillet removes a corner and replaces it with a quarter-cylinder: volume removed per edge = (R^2 - pi x R^2 / 4) x length = (100 - 78.54) x 100 = 2,146 mm^3
- **Expected volume: ~991,416 mm^3** (1,000,000 - 4 x 2,146)

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_rectangle` with width=100, height=100, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=100
5. `solidworks_fillet` with radius=10, edges=[{x:50, y:50, z:50}, {x:-50, y:50, z:50}, {x:-50, y:-50, z:50}, {x:50, y:-50, z:50}]
6. `solidworks_get_mass_properties`

---

## Test 36: Chamfer — Beveled Block Edge (Applied Features)

**What it tests:** Applying an equal-distance chamfer to a single edge.

**Prompt:**

```
Create a new part. On the Front plane, draw an 80mm x 60mm rectangle centered at the origin and extrude it 40mm. Then apply an 8mm equal-distance chamfer to the top-front edge — the horizontal edge where y=30 meets z=0, running along X. Select it at coordinate (0, 30, 0). Report the volume.
```

**Expected outcome:**
- Block from (-40, -30, 0) to (40, 30, 40)
- One 80mm-long edge chamfered with 8mm equal distance
- Triangular prism removed: 0.5 x 8 x 8 x 80 = 2,560 mm^3
- **Expected volume: 189,440 mm^3** (192,000 - 2,560)

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_rectangle` with width=80, height=60, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=40
5. `solidworks_chamfer` with distance=8, edges=[{x:0, y:30, z:0}]
6. `solidworks_get_mass_properties`

---

## Test 37: Shell — Hollow Box (Applied Features)

**What it tests:** Hollowing out a solid by removing a face and creating uniform wall thickness.

**Prompt:**

```
Create a new part. On the Front plane, draw a 50mm x 50mm rectangle centered at the origin and extrude it 50mm to create a cube. Then shell it with 5mm wall thickness, removing the back face at (0, 0, 50) to create an open-back hollow box. Report the volume.
```

**Expected outcome:**
- 50mm cube from (-25, -25, 0) to (25, 25, 50)
- Back face at z=50 removed, 5mm walls on all other sides
- Inner cavity: 40mm x 40mm x 45mm (5mm walls on sides, 5mm on front, open at back)
- **Expected volume: 53,000 mm^3** (125,000 - 72,000)

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_rectangle` with width=50, height=50, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=50
5. `solidworks_shell` with thickness=5, facesToRemove=[{x:0, y:0, z:50}]
6. `solidworks_get_mass_properties`

---

## Test 38: Draft — Tapered Block (Applied Features)

**What it tests:** Applying a draft angle to side faces using a neutral plane, causing the part to taper.

**Prompt:**

```
Create a new part. On the Front plane, draw a 40mm x 40mm rectangle centered at the origin and extrude it 50mm. Then apply a 10-degree draft to the left face and right face, using the Front plane as the neutral plane. The left face is at (-20, 0, 25) and the right face is at (20, 0, 25). Report the volume.
```

**Expected outcome:**
- Block from (-20, -20, 0) to (20, 20, 50)
- Draft inward from Front plane (z=0): at z=0 faces stay at x=±20; at z=50 they taper inward by tan(10°) x 50 ≈ 8.82mm each side
- Cross-section width at z=50: 40 - 2 x 8.82 = 22.37mm; Y-dimension unchanged at 40mm
- **Expected volume: ~62,365 mm^3** (integral of tapered cross-sections over 50mm depth)

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_rectangle` with width=40, height=40, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=50
5. `solidworks_draft` with angle=10, neutralPlane="Front", facesToDraft=[{x:-20, y:0, z:25}, {x:20, y:0, z:25}]
6. `solidworks_get_mass_properties`

---

## Test 39: Linear Pattern — Row of Holes (Patterns)

**What it tests:** Creating a linear pattern of a cut feature along an edge direction, with feature name discovery via list_features.

**Prompt:**

```
Create a new part. On the Front plane, draw a 120mm x 60mm rectangle centered at the origin and extrude it 10mm to create a flat plate. Then create a sketch on the front face at (-45, 0, 0) and draw a circle with radius 5mm centered at (-45, 0). Cut-extrude 10mm to make a through-hole. Use list_features to find the cut feature name. Then create a linear pattern of the cut feature with 4 total instances, 30mm spacing, using the bottom-front edge at (0, -30, 0) as the pattern direction. Report the volume.
```

**Expected outcome:**
- Plate: 120x60x10mm from (-60, -30, 0) to (60, 30, 10)
- Through-hole R=5 at (-45, 0)
- Linear pattern creates 4 equally spaced holes at x = -45, -15, 15, 45 — all within the plate
- **Expected volume: ~68,858 mm^3** (72,000 - 4 x pi x 25 x 10)

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_rectangle` with width=120, height=60, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=10
5. `solidworks_create_sketch` with faceX=-45, faceY=0, faceZ=0
6. `solidworks_sketch_circle` with radius=5, centerX=-45, centerY=0
7. `solidworks_create_cut_extrusion` with depth=10
8. `solidworks_list_features`
9. `solidworks_linear_pattern` with features=["Cut-Extrude1"], direction1={x:0, y:-30, z:0}, spacing1=30, count1=4
10. `solidworks_get_mass_properties`

---

## Test 40: Circular Pattern — Bolt Circle (Patterns)

**What it tests:** Creating a circular pattern of a cut feature around a reference axis, including reference axis creation from a cylindrical face.

**Prompt:**

```
Create a new part. On the Front plane, draw a circle with radius 40mm at the origin and extrude it 10mm to create a disc. Create a reference axis from the outer cylindrical face at (40, 0, 5). Then create a sketch on the front face at (25, 0, 0) and draw a circle with radius 4mm centered at (25, 0). Cut-extrude 10mm to create a through-hole. Use list_features to find the cut feature name. Create a circular pattern of the cut with 6 total instances over 360 degrees around Axis1. Report the volume.
```

**Expected outcome:**
- Disc: R=40, 10mm thick from z=0 to z=10
- Reference axis through the center of the cylindrical face
- Through-hole R=4 at radial offset of 25mm from center
- Circular pattern: 6 equally spaced holes at r=25 from center (60° apart)
- **Expected volume: ~47,250 mm^3** (pi x 40^2 x 10 - 6 x pi x 4^2 x 10)

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_circle` with radius=40, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=10
5. `solidworks_ref_axis` with type="CYLINDRICAL_FACE", face={x:40, y:0, z:5}
6. `solidworks_create_sketch` with faceX=25, faceY=0, faceZ=0
7. `solidworks_sketch_circle` with radius=4, centerX=25, centerY=0
8. `solidworks_create_cut_extrusion` with depth=10
9. `solidworks_list_features`
10. `solidworks_circular_pattern` with features=["Cut-Extrude1"], axis="Axis1", count=6, angle=360
11. `solidworks_get_mass_properties`

---

## Test 41: Mirror — Symmetric Cut (Patterns)

**What it tests:** Mirroring a cut feature across a standard reference plane to create symmetric geometry.

**Prompt:**

```
Create a new part. On the Front plane, draw a 100mm x 60mm rectangle centered at the origin and extrude it 30mm. Then create a sketch on the front face at (25, 0, 0) and draw a circle with radius 8mm centered at (25, 0). Cut-extrude 30mm to create a through-hole on the right side. Use list_features to find the cut feature name. Mirror the cut across the Right plane to create a matching hole on the left side at (-25, 0). Report the volume.
```

**Expected outcome:**
- Block: 100x60x30mm from (-50, -30, 0) to (50, 30, 30)
- Through-hole R=8 at (25, 0)
- Mirror creates a symmetric hole at (-25, 0)
- **Expected volume: ~167,936 mm^3** (180,000 - 2 x pi x 64 x 30)

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_rectangle` with width=100, height=60, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=30
5. `solidworks_create_sketch` with faceX=25, faceY=0, faceZ=0
6. `solidworks_sketch_circle` with radius=8, centerX=25, centerY=0
7. `solidworks_create_cut_extrusion` with depth=30
8. `solidworks_list_features`
9. `solidworks_mirror` with features=["Cut-Extrude1"], mirrorPlane="Right"
10. `solidworks_get_mass_properties`

---

## Test 42: Reference Plane + List Features (Reference Geometry)

**What it tests:** Creating an offset reference plane and verifying it appears in the feature tree.

**Prompt:**

```
Create a new part. On the Front plane, draw a 60mm x 60mm rectangle centered at the origin and extrude it 60mm to create a cube. Then create a reference plane offset 30mm from the Front plane. Use list_features to verify that a reference plane (Plane1 or similar) appears in the feature tree. Report the volume.
```

**Expected outcome:**
- 60mm cube from (-30, -30, 0) to (30, 30, 60)
- Reference plane created 30mm from Front plane
- Feature tree includes the new plane (e.g., "Plane1")
- Volume is unchanged by the reference plane
- **Expected volume: 216,000 mm^3** (60^3)

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_rectangle` with width=60, height=60, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=60
5. `solidworks_ref_plane` with type="OFFSET", referencePlane="Front", offset=30
6. `solidworks_list_features`
7. `solidworks_get_mass_properties`

---

## Test 43: Cut Revolve — Stepped Shaft (Cut Features)

**What it tests:** Using a cut revolve to machine a step in a cylindrical shaft, creating a two-diameter shaft.

**Prompt:**

```
Create a new part. On the Top plane, draw a circle with radius 30mm at the origin and extrude it 60mm to create a cylinder (its axis runs along Y from y=0 to y=60). Then on the Front plane, draw a vertical centerline from (0, -40) to (0, 60) and a closed rectangular cut profile using 4 lines: (25, 30) to (30, 30), (30, 30) to (30, 60), (30, 60) to (25, 60), (25, 60) to (25, 30). Cut-revolve 360 degrees to create a stepped shaft. The result should be R=30 from y=0 to y=30, and R=25 from y=30 to y=60. Report the volume.
```

**Expected outcome:**
- Cylinder R=30, 60mm tall along Y-axis (extruded from Top plane)
- Cut revolve removes ring R=25..30 from y=30 to y=60
- Lower section (y=0..30): pi x 30^2 x 30 = 84,823 mm^3
- Upper section (y=30..60): pi x 25^2 x 30 = 58,905 mm^3
- **Expected volume: ~143,728 mm^3**

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Top"
3. `solidworks_sketch_circle` with radius=30, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=60
5. `solidworks_create_sketch` with plane "Front"
6. `solidworks_sketch_centerline` with x1=0, y1=-40, x2=0, y2=60
7. `solidworks_sketch_line` with x1=25, y1=30, x2=30, y2=30
8. `solidworks_sketch_line` with x1=30, y1=30, x2=30, y2=60
9. `solidworks_sketch_line` with x1=30, y1=60, x2=25, y2=60
10. `solidworks_sketch_line` with x1=25, y1=60, x2=25, y2=30
11. `solidworks_cut_revolve` with angle=360
12. `solidworks_get_mass_properties`

---

## Test 44: Cosmetic Thread (Hole Features)

**What it tests:** Applying a cosmetic thread annotation to a cylindrical edge. Cosmetic threads are visual only and do not change the solid geometry.

**Prompt:**

```
Create a new part. On the Front plane, draw a circle with radius 10mm at the origin and extrude it 30mm to create a cylinder. Apply a cosmetic thread to the front circular edge at (10, 0, 0) with a thread depth of 25mm and minor diameter of 8mm. Report the volume — it should be unchanged since cosmetic threads are annotation-only.
```

**Expected outcome:**
- Cylinder R=10, 30mm deep along Z from z=0 to z=30
- Cosmetic thread applied to the front circular edge (visual annotation only)
- No material is added or removed
- **Expected volume: ~9,425 mm^3** (pi x 10^2 x 30)

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_circle` with radius=10, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=30
5. `solidworks_thread` with edge={x:10, y:0, z:0}, depth=25, diameter=8
6. `solidworks_get_mass_properties`

---

## Test 45: Ref Axis + Ref Point (Reference Geometry)

**What it tests:** Creating a reference axis from a cylindrical face, a reference point at arbitrary 3D coordinates, and verifying both appear in the feature tree.

**Prompt:**

```
Create a new part. On the Front plane, draw a circle with radius 20mm at the origin and extrude it 40mm to create a cylinder. Create a reference axis from the cylindrical outer face at (20, 0, 20). Create a reference point at coordinates (30, 30, 30). List all features to verify that Axis1 and Point1 appear in the feature tree. Report the volume.
```

**Expected outcome:**
- Cylinder R=20, 40mm deep along Z from z=0 to z=40
- Reference axis created along the cylinder's center axis
- Reference point created at (30, 30, 30) in 3D space
- Feature tree includes Axis1 and Point1 (or similar names)
- Volume is unchanged by reference geometry
- **Expected volume: ~50,265 mm^3** (pi x 20^2 x 40)

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_circle` with radius=20, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=40
5. `solidworks_ref_axis` with type="CYLINDRICAL_FACE", face={x:20, y:0, z:20}
6. `solidworks_ref_point` with type="COORDINATES", x=30, y=30, z=30
7. `solidworks_list_features`
8. `solidworks_get_mass_properties`

---

## Test 46: Comprehensive 3D Feature Workflow (Multi-Feature)

**What it tests:** Combining cut-extrusion, mirror, fillet, and list_features in a single multi-step workflow. This tests the agent's ability to chain advanced 3D operations and discover feature names.

**Prompt:**

```
Create a new part. On the Front plane, draw a 100mm x 60mm rectangle centered at the origin and extrude it 30mm. Then:

1. Create a through-hole: sketch a circle with radius 8mm at (30, 0) on the front face (z=0) and cut-extrude 30mm.
2. Use list_features to find the cut feature name.
3. Mirror the cut across the Right plane to create a symmetric hole at (-30, 0).
4. Apply a 5mm radius fillet to all 4 vertical depth edges. The edge midpoints are at (50, 30, 15), (-50, 30, 15), (-50, -30, 15), and (50, -30, 15).

Report the final volume.
```

**Expected outcome:**
- Block: 100x60x30mm from (-50, -30, 0) to (50, 30, 30)
- Two symmetric through-holes R=8 at (30, 0) and (-30, 0)
- 4 vertical depth edges filleted with R=5mm
- Block volume: 180,000 mm^3
- 2 holes remove: 2 x pi x 64 x 30 = 12,064 mm^3
- 4 fillets remove: 4 x (25 - pi x 25/4) x 30 = 4 x 5.365 x 30 = 644 mm^3
- **Expected volume: ~167,292 mm^3**

**Evaluation criteria:**
- Does the agent create the block and hole correctly?
- Does it use list_features to discover the cut feature name before mirroring?
- Does it mirror across the correct plane (Right)?
- Does it select the correct edge coordinates for the fillet?
- Does the reported volume approximately match the expected value?

**Tools that must be called (in order):**
1. `solidworks_new_part`
2. `solidworks_create_sketch` with plane "Front"
3. `solidworks_sketch_rectangle` with width=100, height=60, centerX=0, centerY=0
4. `solidworks_create_extrusion` with depth=30
5. `solidworks_create_sketch` with faceX=30, faceY=0, faceZ=0
6. `solidworks_sketch_circle` with radius=8, centerX=30, centerY=0
7. `solidworks_create_cut_extrusion` with depth=30
8. `solidworks_list_features`
9. `solidworks_mirror` with features=["Cut-Extrude1"], mirrorPlane="Right"
10. `solidworks_fillet` with radius=5, edges=[{x:50, y:30, z:15}, {x:-50, y:30, z:15}, {x:-50, y:-30, z:15}, {x:50, y:-30, z:15}]
11. `solidworks_get_mass_properties`

---

## Scoring Guide

| Score | Meaning |
|-------|---------|
| **Pass** | All required tools were called with correct parameters; the result matches expected outcome; reported volume is within 1% of expected |
| **Partial** | The right tools were called but with imprecise parameters (e.g., wrong center, missing positioning); the result is close but not exact; volume is off by more than 1% |
| **Fail** | Wrong tools used, incorrect workflow order, missing critical steps, SolidWorks errors not recovered, or volume not reported when required |

### Category Breakdown

| Category | Tests | What's Evaluated |
|----------|-------|------------------|
| **Core Workflow** | 1, 2, 27, 28 | new_part, create_sketch, extrude, exit_sketch |
| **Sketch Entities** | 3, 4, 5, 9, 10, 11, 18, 19, 21, 23 | All shape tools (rectangle, circle, polygon, ellipse, slot, line, arc, spline, text, point) |
| **Spatial Positioning** | 6, 7, 8, 20 | spacing, relativeX/Y, centerX/Y, get_last_shape_info |
| **Constraints & Construction** | 12, 13, 25 | constraint, centerline, toggle_construction |
| **3D Operations** | 14, 15, 16, 22, 26 | extrusion, cut-extrusion, reverse, mass_properties, face sketching |
| **Boss/Base Features** | 32, 33, 34 | revolve, sweep, loft (with auxiliary body workaround) |
| **Cut Features** | 43 | cut_revolve (stepped shaft) |
| **Applied Features** | 35, 36, 37, 38 | fillet, chamfer, shell, draft |
| **Patterns** | 39, 40, 41 | linear_pattern, circular_pattern, mirror |
| **Reference Geometry** | 42, 45 | ref_plane, ref_axis, ref_point, list_features |
| **Hole Features** | 44 | cosmetic thread (annotation-only) |
| **Complex / Natural Language** | 24, 29 | Multi-entity profiles, interpreting descriptions |
| **Error Handling** | 30 | Recovery from tool failures |
| **Comprehensive** | 31, 46 | Every sketch tool (31); multi-feature 3D workflow (46) |

### Volume Verification Summary

| Test | Geometry | Expected Volume (mm^3) |
|------|----------|----------------------|
| 1 | 100mm cube | 1,000,000 |
| 2 | 50mm dia x 75mm cylinder | ~147,262 |
| 3 | 30mm hex prism x 40mm | ~93,531 |
| 4 | 40x25mm ellipse x 5mm | ~15,708 |
| 5 | Slot 60x20mm x 10mm | ~15,142 |
| 14 | 80x60x30 block - 20mm dia hole | ~134,575 |
| 15 | 100mm cube | 1,000,000 |
| 16 | 40mm radius x 60mm cylinder | ~301,593 |
| 17 | 25mm inscribed pentagon x 15mm | ~34,057 |
| 22 | 40x40mm x 50mm (reverse) | 80,000 |
| 23 | 50x30mm x 20mm (corners) | 30,000 |
| 24 | L-bracket x 10mm | 12,750 |
| 26 | Washer 20mm/8mm x 3mm | ~3,167 |
| 27 | 35mm cube | 42,875 |
| 29 | Phone stand (approximate) | ~32,000 |
| 30 | 30x30mm x 50mm (recovery) | 45,000 |
| 32 | Revolved rectangle (cylinder R=20, H=50) | ~62,832 |
| 33 | Swept circle R=8 along 80mm path | ~16,085 |
| 34 | Loft R=30 to R=10 over 80mm (truncated cone) | ~108,909 |
| 35 | 100mm cube, 4 edges filleted R=10 | ~991,416 |
| 36 | 80x60x40 block, 1 edge chamfered 8mm | 189,440 |
| 37 | 50mm cube, shelled 5mm, back face removed | 53,000 |
| 38 | 40x40x50 block, draft 10° on 2 faces | ~62,365 |
| 39 | 120x60x10 plate, 4 holes R=5 (linear pattern) | ~68,858 |
| 40 | Disc R=40x10, 6 holes R=4 (circular pattern) | ~47,250 |
| 41 | 100x60x30 block, 2 holes R=8 (mirror) | ~167,936 |
| 42 | 60mm cube + ref plane (unchanged) | 216,000 |
| 43 | Stepped shaft R=30/R=25, each 30mm | ~143,728 |
| 44 | Cylinder R=10x30 + cosmetic thread (unchanged) | ~9,425 |
| 45 | Cylinder R=20x40 + ref axis + ref point (unchanged) | ~50,265 |
| 46 | 100x60x30 block, 2 holes R=8, 4 fillets R=5 | ~167,292 |
