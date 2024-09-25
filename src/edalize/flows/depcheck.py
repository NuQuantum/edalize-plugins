# Copyright edalize contributors
# Licensed under the 2-Clause BSD License, see LICENSE for details.
# SPDX-License-Identifier: BSD-2-Clause
from edalize.flows.edaflow import Edaflow
from edalize.flows.edaflow import FlowGraph


class Depcheck(Edaflow):
    """Run the dependency checker flow

    This flow utilises the flist tool to get the files required for a core file and
    then the Xcelium tool for elaboration of the netlist.
    """

    argtypes = ["cmdlinearg", "generic", "plusarg", "vlogdefine", "vlogparam"]

    FLOW_DEFINED_TOOL_OPTIONS = {}

    FLOW_OPTIONS = {
        "frontends": {
            "type": "str",
            "desc": "Tools to run before main flow",
            "list": True,
        },
        "tool": {
            "type": "str",
            "desc": "The tool to be used for the elaboration stage",
        },
    }

    @classmethod
    def get_tool_options(cls, flow_options):
        flow = flow_options.get("frontends", []).copy()
        tool = cls._require_flow_option(flow_options, "tool")
        flow.append(tool)

        return cls.get_filtered_tool_options(flow, cls.FLOW_DEFINED_TOOL_OPTIONS)

    def configure_flow(self, flow_options):
        flow = {}

        # Add any user-specified frontends to the flow
        deps = []
        for frontend in flow_options.get("frontends", []):
            flow[frontend] = {"deps": deps}
            deps = [frontend]

        # Get the elab tool (Xcelium or Vivado)
        elab_tool = self.flow_options.get("tool", "")

        # Add theelab tool to the flow
        flow[elab_tool] = {
            "deps": deps,
            "fdto": self.FLOW_DEFINED_TOOL_OPTIONS.get(elab_tool, {}),
        }

        # Create and return flow graph object
        return FlowGraph.fromdict(flow)

    def configure_tools(self, graph):
        super().configure_tools(graph)

        # Set flow default target from the main tool's default target
        tool = self.flow_options.get("tool")

        if tool == "xcelium":
            pass
        elif tool == "vivado":
            # net to set it to elab only
            raise NotImplementedError("Elab with Vivado not yet implemented")
        else:
            raise ValueError("Invalid tool specified")

        self.commands.set_default_target(
            graph.get_node(tool).inst.commands.default_target,
        )

    def build(self):
        """Custom build() method so that we can catch runtime errors on elab and do
        some post processing"""
        try:
            self.verbose = False
            self._run_tool("make", cwd=self.work_root, quiet=True)
        except RuntimeError:
            print(f"Dependencies incorrectly specified for core {self.edam['name']}")
            exit(0)

        print("All dependencies correctly specified!")
