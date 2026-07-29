"""
SolidWorks Configuration & Equation Tools

Configurations: named variants of a model with per-configuration dimension
values. Equations: dimension relationships ("D1@Boss-Extrude1" = "D1@Sketch1"/2)
that re-solve automatically when driving dimensions change.

COM notes (verified live on SW2025):
  - AddConfiguration3(name, comment, alternateName, options) -> IConfiguration
  - ShowConfiguration2(name) -> bool activates a configuration
  - Config-specific dimension: IDimension.SetSystemValue3(value,
    swSetValue_InSpecificConfigurations=3, VARIANT(VT_ARRAY|VT_BSTR, [names]))
  - IEquationMgr via GetEquationMgr (property): Add2(index, equation, solve),
    GetCount (property), Equation(i), Delete(i)
"""

import json
import logging
import math
import pythoncom
import win32com.client
from mcp.types import Tool
from .com_utils import com_prop

logger = logging.getLogger(__name__)


class ConfigurationTools:
    """Configurations and equations for parts and assemblies."""

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
                name="solidworks_add_configuration",
                description="Add a named configuration (design variant) to the active document. Use switch_configuration to activate it, and set_parameter with the configuration argument (or set_config_parameter) to give it different dimension values.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "New configuration name (e.g. 'Version B')"},
                        "activate": {"type": "boolean", "description": "Activate it immediately (default true)"}
                    },
                    "required": ["name"]
                }
            ),
            Tool(
                name="solidworks_switch_configuration",
                description="Activate a configuration by name. Subsequent mass properties reflect the active configuration.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Configuration name to activate"}
                    },
                    "required": ["name"]
                }
            ),
            Tool(
                name="solidworks_list_configurations",
                description="List all configurations of the active document and which one is active.",
                inputSchema={"type": "object", "properties": {}}
            ),
            Tool(
                name="solidworks_set_config_parameter",
                description="Set a dimension value in ONE SPECIFIC configuration only (other configurations keep their value). Parameter format like set_parameter: 'D1@Sketch1', 'D1@Boss-Extrude1'.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "parameter": {"type": "string", "description": "<DimName>@<FeatureOrSketchName>"},
                        "value": {"type": "number", "description": "New value (mm for lengths, degrees for angles)"},
                        "unit": {"type": "string", "enum": ["mm", "deg"], "description": "Unit (default mm)"},
                        "configuration": {"type": "string", "description": "Configuration to change"}
                    },
                    "required": ["parameter", "value", "configuration"]
                }
            ),
            Tool(
                name="solidworks_add_equation",
                description="Add an equation linking dimensions, e.g. '\"D1@Boss-Extrude1\" = \"D1@Sketch1\" / 2' (dimension names in double quotes). The model re-solves automatically when driving dimensions change. Returns the equation index.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "equation": {
                            "type": "string",
                            "description": "Equation text; dimension names must be double-quoted, e.g. \"D2@Sketch1\" = \"D1@Sketch1\" * 0.5"
                        }
                    },
                    "required": ["equation"]
                }
            ),
            Tool(
                name="solidworks_list_equations",
                description="List all equations in the active document with their indices and current text.",
                inputSchema={"type": "object", "properties": {}}
            ),
            Tool(
                name="solidworks_delete_equation",
                description="Delete an equation by its index (from list_equations).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "Equation index to delete"}
                    },
                    "required": ["index"]
                }
            ),
        ]

    def execute(self, tool_name: str, args: dict) -> str:
        self.connection.ensure_connection()
        dispatch = {
            "solidworks_add_configuration": lambda: self.add_configuration(args),
            "solidworks_switch_configuration": lambda: self.switch_configuration(args),
            "solidworks_list_configurations": lambda: self.list_configurations(),
            "solidworks_set_config_parameter": lambda: self.set_config_parameter(args),
            "solidworks_add_equation": lambda: self.add_equation(args),
            "solidworks_list_equations": lambda: self.list_equations(),
            "solidworks_delete_equation": lambda: self.delete_equation(args),
        }
        handler = dispatch.get(tool_name)
        if not handler:
            raise Exception(f"Unknown configuration tool: {tool_name}")
        return handler()

    def _doc(self):
        doc = self.connection.get_active_doc()
        if not doc:
            raise Exception("No active document")
        return doc

    # --- Configurations ---

    def add_configuration(self, args: dict) -> str:
        doc = self._doc()
        name = args["name"].strip()
        cfg = doc.AddConfiguration3(name, "", "", 0)
        if not cfg:
            raise Exception(f"Failed to add configuration '{name}' (duplicate name?)")
        activate = args.get("activate", True)
        if activate:
            doc.ShowConfiguration2(name)
            doc.ForceRebuild3(True)
        names = list(com_prop(doc, "GetConfigurationNames") or [])
        return self._json_result(
            f"✓ Configuration '{name}' added{' and activated' if activate else ''}. "
            f"Configurations: {names}",
            name=name,
            configurations=names,
            type="configuration",
        )

    def switch_configuration(self, args: dict) -> str:
        doc = self._doc()
        name = args["name"].strip()
        ok = doc.ShowConfiguration2(name)
        if not ok:
            names = list(com_prop(doc, "GetConfigurationNames") or [])
            raise Exception(f"Could not activate configuration '{name}'. Available: {names}")
        doc.ForceRebuild3(True)
        return self._json_result(
            f"✓ Configuration '{name}' is now active. Mass properties reflect it.",
            name=name,
            type="configuration",
        )

    def list_configurations(self) -> str:
        doc = self._doc()
        names = list(com_prop(doc, "GetConfigurationNames") or [])
        active = None
        try:
            active = doc.ConfigurationManager.ActiveConfiguration.Name
        except Exception:
            pass
        return json.dumps({
            "result": f"✓ {len(names)} configuration(s); active: {active}",
            "configurations": names,
            "active": active,
        })

    def set_config_parameter(self, args: dict) -> str:
        doc = self._doc()
        param_name = args["parameter"].strip()
        config = args["configuration"].strip()
        unit = args.get("unit", "mm")
        value_sys = (math.radians(args["value"]) if unit == "deg"
                     else args["value"] / 1000.0)

        dim = doc.Parameter(param_name)
        if dim is None:
            raise Exception(f"Parameter not found: {param_name!r}")

        # swSetValue_InSpecificConfigurations = 3, with a VT_BSTR array of names
        names = win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_BSTR, [config])
        dim.SetSystemValue3(value_sys, 3, names)
        from .com_utils import verify_rebuild
        rebuilt_ok, problems = verify_rebuild(doc)

        display = f"{args['value']}°" if unit == "deg" else f"{args['value']}mm"
        if not rebuilt_ok:
            return self._json_result(
                f"⚠ {param_name} = {display} set in configuration '{config}', "
                f"but the REBUILD REPORTS ERRORS: {'; '.join(problems[:4])}. "
                f"A downstream feature fails with this value in this "
                f"configuration.",
                parameter=param_name,
                configuration=config,
                newValue=args["value"],
                rebuildErrors=problems[:8],
                type="parameter",
            )
        return self._json_result(
            f"✓ {param_name} = {display} in configuration '{config}' only. "
            f"Other configurations keep their value.",
            parameter=param_name,
            configuration=config,
            newValue=args["value"],
            type="parameter",
        )

    # --- Equations ---

    def add_equation(self, args: dict) -> str:
        doc = self._doc()
        equation = args["equation"].strip()
        em = com_prop(doc, "GetEquationMgr")
        idx = em.Add2(-1, equation, True)
        if idx is None or idx < 0:
            raise Exception(
                f"Failed to add equation: {equation!r}. Dimension names must be "
                f'double-quoted, e.g. "D1@Boss-Extrude1" = "D1@Sketch1" / 2'
            )
        from .com_utils import verify_rebuild
        rebuilt_ok, problems = verify_rebuild(doc)
        if not rebuilt_ok:
            return self._json_result(
                f"⚠ Equation added at index {idx} ({equation}), but the "
                f"REBUILD REPORTS ERRORS: {'; '.join(problems[:4])}. The "
                f"equation's driven value likely breaks a downstream feature.",
                index=idx,
                equation=equation,
                rebuildErrors=problems[:8],
                type="equation",
            )
        return self._json_result(
            f"✓ Equation added at index {idx}: {equation}",
            index=idx,
            equation=equation,
            type="equation",
        )

    def list_equations(self) -> str:
        doc = self._doc()
        em = com_prop(doc, "GetEquationMgr")
        count = int(com_prop(em, "GetCount"))
        equations = []
        for i in range(count):
            entry = {"index": i, "equation": em.Equation(i)}
            try:
                entry["value"] = em.Value(i)
            except Exception:
                pass
            equations.append(entry)
        return json.dumps({
            "result": f"✓ {count} equation(s)",
            "equations": equations,
        })

    def delete_equation(self, args: dict) -> str:
        doc = self._doc()
        em = com_prop(doc, "GetEquationMgr")
        ret = em.Delete(int(args["index"]))
        doc.ForceRebuild3(True)
        if ret is not None and ret < 0:
            raise Exception(f"Failed to delete equation index {args['index']}")
        return self._json_result(f"✓ Equation {args['index']} deleted", type="equation")
