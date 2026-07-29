"""
SolidWorks MCP Module
"""

from .connection import SolidWorksConnection
from .state_tracker import StateTracker
from .sketching import SketchingTools
from .modeling import ModelingTools
from .features import FeatureTools
from .cut_features import CutFeatureTools
from .applied_features import AppliedFeatureTools
from .patterns import PatternTools
from .hole_features import HoleFeatureTools
from .reference_geometry import ReferenceGeometryTools
from .geometry_query import GeometryQueryTools
from .state_query import StateQueryTools
from .document_manager import DocumentManagerTools
from .assembly import AssemblyTools
from .configurations import ConfigurationTools

__all__ = [
    'SolidWorksConnection',
    'StateTracker',
    'SketchingTools',
    'ModelingTools',
    'FeatureTools',
    'CutFeatureTools',
    'AppliedFeatureTools',
    'PatternTools',
    'HoleFeatureTools',
    'ReferenceGeometryTools',
    'GeometryQueryTools',
    'StateQueryTools',
    'DocumentManagerTools',
    'AssemblyTools',
    'ConfigurationTools',
]
