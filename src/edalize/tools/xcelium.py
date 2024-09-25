import logging
import os

from edalize.tools.edatool import Edatool
from edalize.utils import EdaCommands

logger = logging.getLogger(__name__)


class Xcelium(Edatool):

    description = "Xcelium is a (System)Verilog/VHDL mixed language simulation tool"

    argtypes = ["vlogdefine", "vlogparam", "generic"]

    TOOL_OPTIONS = {
        "timescale": {
            "type": "str",
            "desc": "Default timescale",
        },
        "xmvhdl_options": {
            "type": "str",
            "desc": "Additional options for compilation with xmvhdl",
            "list": True,
        },
        "xmvlog_options": {
            "type": "str",
            "desc": "Additional options for compilation with xmvlog",
            "list": True,
        },
        "xmsim_options": {
            "type": "str",
            "desc": "Additional run options for xmsim",
            "list": True,
        },
        "xrun_options": {
            "type": "str",
            "desc": "Additional run options for xrun",
            "list": True,
        },
    }

    def setup(self, edam):
        super().setup(edam)

        self.f_list = []

        incdirs = []
        depfiles = []
        unused_files = []

        # project-wide defines
        for key, value in self.vlogdefine.items():
            self.f_list.append(
                "+define+{}={}\n".format(key, self._param_value_str(value, "")),
            )

        # Top level parameters (for each top level)
        for key, value in self.vlogparam.items():
            for toplevel in self.toplevel.split(" "):
                self.f_list.append("-defparam")
                self.f_list.append(
                    "{}.{}={}".format(toplevel, key, self._param_value_str(value, '"')),
                )

        # Source files
        for f in self.files:

            file_type = f.get("file_type", "")

            args = []
            cmd = None
            depfile = True

            if file_type.startswith("verilogSource") or file_type.startswith(
                "systemVerilogSource",
            ):
                cmd = "xmvlog"
                args += self.tool_options.get("xmvlog_options", [])
                if file_type.startswith("systemVerilogSource"):
                    args += ["-sv"]

            elif file_type.startswith("vhdlSource"):
                cmd = "xmvhdl"
                if file_type.endswith("-93"):
                    args += ["-v93"]
                elif file_type.endswith("-2008"):
                    args += ["-v200x"]

                args += self.tool_options.get("xmvhdl_options", [])
            else:
                depfile = False

            if depfile:
                depfiles.append(f["name"])

            # Process the line
            if cmd is not None:
                args += [self._absolute_path(f["name"])]
                line = (
                    "-makelib"
                    f" {f.get('logical_name') or 'worklib'} {' '.join(args)} -endlib"
                )
                if not self._add_include_dir(f, incdirs):
                    self.f_list.append(line)

        # Add the include dirs
        for include_dir in incdirs:
            self.f_list.append(f"+incdir+{self._absolute_path(include_dir)}")

        # Update EDAM
        output_file = self.name + ".f"
        self.edam = edam.copy()
        self.edam["files"] = unused_files
        self.edam["files"].append(
            {
                "name": output_file,
                "file_type": "verilogSource",
            },
        )

        xmsim_opts = self.tool_options.get("xmsim_options", [])

        # Generate the xrun command
        commands = EdaCommands()
        commands.add(
            ["xrun"]
            + ["-q"]
            + ["-elaborate"]
            + [f"-top {t}" for t in self.toplevel.split(" ")]
            + (["-xmsimargs", *xmsim_opts] if xmsim_opts else [])
            + ["-f", output_file]
            + ["-access", "rwc"]
            + ["-timescale", self.tool_options.get("timescale", "10ps/1ps")],
            [self.name],
            depfiles,
        )
        commands.set_default_target(self.name)

        self.commands = commands

    def _absolute_path(self, path):
        return os.path.abspath(os.path.join(self.work_root, path))

    def write_config_files(self):
        self.update_config_file(self.name + ".f", "\n".join(self.f_list) + "\n")

    def run(self):
        args = [self.name]

        # Set plusargs
        if self.plusarg:
            plusargs = []
            for key, value in self.plusarg.items():
                plusargs += [f"+{key}={self._param_value_str(value)}"]
            args.append("EXTRA_OPTIONS=" + " ".join(plusargs))

        return ("make", args, self.work_root)
