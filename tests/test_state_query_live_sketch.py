import json
from types import SimpleNamespace
import unittest

from solidworks.state_query import StateQueryTools


class Point:
    def __init__(self, x, y):
        self.X = x
        self.Y = y


class LineSegment:
    GetType = 0

    def GetStartPoint2(self):
        return Point(0.001, 0.002)

    def GetEndPoint2(self):
        return Point(0.003, 0.004)


class CircleSegment:
    GetType = 1
    IsCircle = True

    def GetCenterPoint2(self):
        return Point(0.005, -0.006)

    def GetRadius(self):
        return 0.007


class ArcSegment:
    GetType = 1
    IsCircle = False

    def GetCenterPoint2(self):
        return Point(0.008, 0.009)

    def GetRadius(self):
        return 0.010

    def GetStartPoint2(self):
        return Point(0.018, 0.009)

    def GetEndPoint2(self):
        return Point(0.008, 0.019)

    def GetLength(self):
        return 0.015


class UnsupportedSegment:
    GetType = 7


class Sketch:
    def __init__(self, segments):
        self.segments = segments

    def GetSketchSegments(self):
        return self.segments


class Feature:
    def __init__(self, sketch):
        self.sketch = sketch

    def GetSpecificFeature2(self):
        return self.sketch


class Document:
    GetPathName = r"C:\temp\roundtrip.SLDPRT"
    GetTitle = "roundtrip.SLDPRT"

    def __init__(self, feature=None):
        self.feature = feature

    def FeatureByName(self, name):
        return self.feature if name == "Sketch1" else None


class Connection:
    def __init__(self, doc=None, alive=True):
        self.doc = doc
        self.alive = alive

    def is_alive(self):
        return self.alive

    def get_active_doc(self):
        return self.doc


class EmptyTracker:
    def get_sketch_entities(self, _sketch_id):
        return []


class StateQueryLiveSketchTests(unittest.TestCase):
    def test_tracker_hit_keeps_tracker_source(self):
        tracker = SimpleNamespace(get_sketch_entities=lambda _id: [
            SimpleNamespace(entity_id="entity:Sketch1/0", entity_type="line", coordinates={"x1": 1})
        ])
        result = json.loads(StateQueryTools(tracker).execute(
            "solidworks_get_sketch_entities", {"sketchId": "sketch:Sketch1"}))
        self.assertEqual(result["source"], "tracker")
        self.assertEqual(len(result["entities"]), 1)

    def test_empty_tracker_falls_back_to_live_com_and_converts_units(self):
        sketch = Sketch([LineSegment(), CircleSegment(), ArcSegment(), UnsupportedSegment()])
        tools = StateQueryTools(EmptyTracker(), Connection(Document(Feature(sketch))))
        result = json.loads(tools.execute(
            "solidworks_get_sketch_entities", {"sketchId": "sketch:Sketch1"}))

        self.assertEqual(result["source"], "live_com")
        self.assertEqual(result["documentPath"], r"C:\temp\roundtrip.SLDPRT")
        self.assertEqual(result["unsupportedCount"], 1)
        self.assertEqual(result["entities"][0]["coordinates"]["p2"], {"x": 3.0, "y": 4.0})
        self.assertEqual(result["entities"][1]["coordinates"]["radius"], 7.0)
        self.assertEqual(result["entities"][2]["coordinates"]["length"], 15.0)

    def test_live_errors_are_structured(self):
        tools = StateQueryTools(EmptyTracker(), Connection(None))
        result = json.loads(tools.execute(
            "solidworks_get_sketch_entities", {"sketchId": "Sketch1"}))
        self.assertEqual(result["source"], "live_com")
        self.assertEqual(result["error"]["code"], "NO_ACTIVE_DOCUMENT")


if __name__ == "__main__":
    unittest.main()
