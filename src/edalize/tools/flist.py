"""The flist Edalize extension for generating files lists for SV/VHDL projects."""

import argparse
import logging
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from edalize.tools.edatool import Edatool
from edalize.utils import EdaCommands
from fusesoc.fusesoc import Config, Fusesoc
from fusesoc.main import _get_core

logger = logging.getLogger(__name__)


@dataclass
class FileList:
    """Collects files into logical groups."""

    incdirs: list[str] = field(default_factory=list)
    rtl_files: list[str] = field(default_factory=list)
    vlt_files: list[str] = field(default_factory=list)
    cpp_incdirs: list[str] = field(default_factory=list)
    cpp_files: list[str] = field(default_factory=list)
    depfiles: list[str] = field(default_factory=list)
    unused_files: list[dict[str, Any]] = field(default_factory=list)


class Flist(Edatool):
    """Edalize extension which writes a list of all project file paths to a .f file."""

    description = "F-list generator"

    TOOL_OPTIONS: ClassVar[dict[str, Any]] = {
        "file_types": {
            "type": "str",
            "desc": "File types which flist will search for",
            "list": True,
        },
        "simulator": {
            "type": "str",
            "desc": "The name of the target simulator",
        },
    }

    # Most simulator follow this syntax for defines and parameter passing
    _DEFAULT_SIM_PREFIXES: ClassVar[dict[str, str]] = {
        "define": "+define+",
        "param": "-G",
    }

    # The supported simulators are the keys of this dict
    _SIM_PREFIXES: ClassVar[dict[str, dict[str, str]]] = {
        "verilator": _DEFAULT_SIM_PREFIXES,
        "xcelium": {
            "define": "+define+",
            "param": "-defparam {toplevel}.",
        },
        "modelsim": _DEFAULT_SIM_PREFIXES,
        "questa": _DEFAULT_SIM_PREFIXES,
    }

    # Supported RTL source types. Users may constraint this with the file_types tool
    # option
    _RTL_SOURCE_TYPES: ClassVar[list[str]] = [
        "systemVerilogSource",
        "verilogSource",
        "vhdlSource",
        "vhdlSource-2008",
        "vhdlSource-93",
    ]

    def _generate_file_list(
        self, files: list[dict[str, Any]], file_types: list[str]
    ) -> FileList:
        """Generate an ordered file list object from a list of files.

        Args:
            files: The list of file specification dictionaries (from edalize)
            file_types: The list of file types to process. All others are ignored.

        Returns:
            FileList: The grouped file list object

        """
        result = FileList()

        for f in files:
            file_type = f.get("file_type", "")
            depfile = True

            matches = [
                idx
                for idx, prefix in enumerate(file_types)
                if file_type.startswith(prefix)
            ]

            # file type matches one of the passed in ones
            if matches:
                if len(matches) > 1:
                    logger.warning(
                        "File type matched multiple prefixes ... "
                        f"({[file_types[idx] for idx in matches]}), proceeding with "
                        f"the first match ({file_types[matches[0]]})",
                    )

                # get the type of the first match
                matched_type = file_types[matches[0]]

                match matched_type:
                    case rtl if rtl in self._RTL_SOURCE_TYPES:
                        if not self._add_include_dir(f, result.incdirs):
                            result.rtl_files.append(f["name"])
                    case "vlt":
                        result.vlt_files.append(f["name"])
                    case "cppSource":
                        if not self._add_include_dir(f, result.cpp_incdirs):
                            result.cpp_files.append(f["name"])
                    case _:
                        logger.error(
                            f"We found a file of type {matched_type} which flist "
                            "currently does not support. Please remove this from your "
                            "core's list of file_types",
                        )

            else:
                result.unused_files.append(f)
                depfile = False

            if depfile:
                result.depfiles.append(f["name"])

        return result

    def setup(self, edam: dict[str, Any]) -> None:
        """Tool implementation."""
        super().setup(edam)

        self.f = []

        simulator = self.tool_options.get("simulator", None)

        if simulator is None:
            simulator = "verilator"
            logger.warning("No simulator specified for Flist, defaulting to verilator")

        assert simulator in self._SIM_PREFIXES, (
            f"{simulator} not in {self._SIM_PREFIXES.keys()}"
        )

        for key, value in self.vlogdefine.items():
            define_str = self._param_value_str(param_value=value)
            prefix_str = self._SIM_PREFIXES[simulator]["define"]
            self.f.append(f"{prefix_str}{key}={define_str}")

        for key, value in self.vlogparam.items():
            param_str = self._param_value_str(param_value=value, str_quote_style='"')
            # Use defaultdict to construct a str() if the key is not in the string
            # being formatted (via format_map() below)
            params = defaultdict(str, toplevel=self.toplevel)
            prefix_str = self._SIM_PREFIXES[simulator]["param"].format_map(params)
            self.f.append(f"{prefix_str}{key}={param_str}")

        # Get a list of the valid file types. If none is specified use sv and v.
        file_types = self.tool_options.get(
            "file_types",
            self._RTL_SOURCE_TYPES,
        )

        file_list = self._generate_file_list(self.files, file_types)

        for include_dir in file_list.incdirs:
            self.f.append(f"+incdir+{self.absolute_path(include_dir)}")

        for include_dir in file_list.cpp_incdirs:
            self.f.append(f"-I{self.absolute_path(include_dir)}")

        # verilog and vlt files are passed to verilator the same way
        for file in [*file_list.vlt_files, *file_list.rtl_files]:
            self.f.append(f"{self.absolute_path(file)}")

        output_file = self.name + ".f"
        self.edam = edam.copy()
        self.edam["files"] = file_list.unused_files
        self.edam["files"].append(
            {
                "name": output_file,
                "file_type": "verilogSource",
            },
        )

        commands = EdaCommands()
        commands.add(
            [],
            [output_file],
            file_list.depfiles,
        )

        commands.set_default_target(output_file)
        self.commands = commands

    def write_config_files(self) -> None:
        """Write the set of collected files to a .f file."""
        self.update_config_file(self.name + ".f", "\n".join(self.f) + "\n")

    def absolute_path(self, path: str) -> Path:
        """Generate the absolute path of a file relative to the work root."""
        return Path.resolve(Path(self.work_root) / Path(path))


def flist(  # noqa: PLR0912, PLR0913, PLR0915
    name: str,
    flags: list | None | None = None,
    build_root: str | Path | None = None,
    work_root: str | Path | None = None,
    output: str | Path | None = None,
    simulator: str | Path | None = None,
) -> Path:
    """Write out an EDA style filelist, aka VC file.

    This method runs the Flist Edatool.  It is assumed that a Core file will have an
    'flist' target that uses the FuseSoC flow API with the Generic flow as follows:

        targets:
            default: &default
                filesets:
                - rtl
                toplevel: modulename

            flist:
                <<: *default
                flow: generic
                flow_options:
                    tool: flist

    Limitations:
        The Flist tool currently only writes out Verilog, SV files and Verilator
        Waivers.

    Arguments:
        name: VLNV of the core to process or just the N if it resolves to a unique name.
        flags: an optional list of addition FuseSoC flags to apply
        work_root: FuseSoC work root directory. This overrides build_root and the
            extended hierarchy. All output files are placed in the directory specified.
            I.E. work_root rather than build_root/sanitized_core_name/tool_target.
        build_root: FuseSoC build directory, traditionally 'build' in the directory
            FuseSoC was called. Here is defaults to /path/to/core/file/parent/.flist
            unless the user overrides it on the command line.
        output: Override the default filelist output path. By default it will be placed
            parallel to the Core file.
        simulator: The simulation the flist is to be used on (optional)

    Returns:
        dst: The Path to the output filelist.

    """
    if flags is None:
        flags = []
    config = Config()
    fs = Fusesoc(config)
    core = _get_core(fs, name)
    core_root = Path(core.core_root)

    # The work-root switch takes precedence over build-root
    if work_root:
        work_root = Path(work_root)
        glob_dir = work_root
        config.args_work_root = work_root
    else:
        build_root = Path(build_root) if build_root else core_root / ".flist"
        glob_dir = build_root / core.name.sanitized_name
        config.args_build_root = build_root

    # Process any user defined flags
    user_flags: dict[str, Any] = {}
    for flag in flags:
        try:
            k, v = flag.split("=")
            user_flags[k] = v
        except ValueError as e:
            if match := re.match(r"((?:\+|\-))?(.+)", flag):
                if match.group(1) == "-":
                    user_flags[flag] = False
                else:
                    user_flags[flag] = True
            else:
                raise RuntimeError("flag regex failed") from e

    # Combine the user flags and the flist flags
    try:
        # Assumption is that the Core file target is 'flist'.
        combined_flags = dict(core.get_flags("flist"), **user_flags)
    except SyntaxError as e:
        logger.error(str(e))
        sys.exit(1)
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)

    try:
        _, backend = fs.get_backend(
            core,
            combined_flags,
            backendargs=["--simulator", simulator] if simulator is not None else [],
        )
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)
    except FileNotFoundError as e:
        logger.error(f'Could not find EDA API file "{e.filename}"')
        sys.exit(1)

    try:
        backend.configure()
    except RuntimeError as e:
        logger.error("Failed to configure the system")
        logger.error(str(e))
        sys.exit(1)

    # The Flist Edatool uses the sanitized name of the core file as the filename.
    src = next(iter(glob_dir.glob(f"**/{core.name.sanitized_name}.f")))

    # Specify the destimation path.  The user can override the default which
    # is to output the filelist at the same path as the parent Core file.
    if output:
        dst = Path(output).absolute()
        assert dst.suffix == ".f", "expecting a .f suffix for filelist path"
    else:
        dst = (core_root / core.core_basename).with_suffix(".f")
    shutil.copy2(src, dst)

    return dst


def _get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("core", help="VLNV of system to filelist")
    parser.add_argument(
        "-b",
        "--build-root",
        help=(
            "override the FuseSoC build root which by default will be parallel to the"
            " core file"
        ),
    )
    parser.add_argument(
        "-w",
        "--work-root",
        help="override the FuseSoC work root (overrides build-root)",
    )
    parser.add_argument(
        "-f",
        "--flag",
        default=[],
        action="append",
        help="specify any additional FuseSoC flags",
    )
    parser.add_argument("-o", "--output", help="specify where to dump the filelist")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="use verbose logging",
    )
    parser.add_argument(
        "-s",
        "--simulator",
        choices=Flist._SIM_PREFIXES.keys(),
        help="Name of the simulator tool which consumes the flist output",
        required=False,
    )
    return parser


def main() -> None:
    """Program entry-point."""
    args = _get_parser().parse_args()

    Fusesoc.init_logging(verbose=args.verbose, monochrome=False)

    filelist = flist(
        name=args.core,
        flags=args.flag,
        build_root=args.build_root,
        work_root=args.work_root,
        output=args.output,
        simulator=args.simulator,
    )

    logger.info(f"Created filelist {filelist}")


if __name__ == "__main__":
    main()
