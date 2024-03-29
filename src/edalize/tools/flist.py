import argparse
import logging
import os
import shutil
from pathlib import Path
from typing import Optional
from typing import Union

from edalize.tools.edatool import Edatool
from edalize.utils import EdaCommands
from fusesoc.fusesoc import Config
from fusesoc.fusesoc import Fusesoc
from fusesoc.main import _get_core

logger = logging.getLogger(__name__)


class Flist(Edatool):

    description = "F-list generator"

    TOOL_OPTIONS = {
        "file_types": {
            "type": "str",
            "desc": "File types which flist will search for",
            "list": True,
        },
    }

    def setup(self, edam):
        super().setup(edam)

        self.f = []

        for key, value in self.vlogdefine.items():
            define_str = self._param_value_str(param_value=value)
            self.f.append(f"+define+{key}={define_str}")

        for key, value in self.vlogparam.items():
            param_str = self._param_value_str(param_value=value, str_quote_style='"')
            self.f.append(f"-pvalue+{self.toplevel}.{key}={param_str}")

        # Get a list of the valid file types. If none is specified use sv and v.
        file_types = self.tool_options.get(
            "file_types",
            ["systemVerilogSource", "verilogSource"],
        )

        incdirs = []
        vlog_files = []
        vlt_files = []
        depfiles = []
        unused_files = []

        for f in self.files:

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
                        f"""File type matched multiple prefixes ({[file_types
                        [idx] for idx in matches]}), proceeding with the first
                        match ({file_types[matches[0]]})""",
                    )

                # get the type of the first match
                file_type = file_types[matches[0]]

                # if its valid, add to the right source list
                match file_type:
                    case "systemVerilogSource" | "verilogSource":
                        if not self._add_include_dir(f, incdirs):
                            vlog_files.append(f["name"])
                    case "vlt":
                        vlt_files.append(f["name"])
                    case _:
                        logger.error(
                            f"""We found a file of type {file_type} which flist
                            currently does not support. Please remove this from your
                            core's list of file_types""",
                        )

            else:
                unused_files.append(f)
                depfile = False

            if depfile:
                depfiles.append(f["name"])

        for include_dir in incdirs:
            self.f.append(f"+incdir+{self.absolute_path(include_dir)}")

        # verilog and vlt files are passed to verilator the same way
        for file in [*vlt_files, *vlog_files]:
            self.f.append(f"{self.absolute_path(file)}")

        output_file = self.name + ".f"
        self.edam = edam.copy()
        self.edam["files"] = unused_files
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
            depfiles,
        )

        commands.set_default_target(output_file)
        self.commands = commands

    def write_config_files(self):
        self.update_config_file(self.name + ".f", "\n".join(self.f) + "\n")

    def absolute_path(self, path):
        return os.path.abspath(os.path.join(self.work_root, path))


def flist(
    name: str,
    build_root: Optional[Union[str, Path]] = None,
    output: Optional[Union[str, Path]] = None,
) -> Path:
    """Writes out an EDA style filelist, aka VC file.

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
        build_root: FuseSoC build directory, traditionally 'build' in the directory
            FuseSoC was called. Here is defaults to /path/to/core/file/parent/.flist
            unless the user overrides it on the command line.
        output: Override the default filelist output path. By default it will be placed
            parallel to the Core file.

    Returns:
        dst: The Path to the output filelist.

    """
    config = Config()
    fs = Fusesoc(config)
    core = _get_core(fs, name)
    core_root = Path(core.core_root)

    if not build_root:
        build_root = core_root / ".flist"
    else:
        build_root = Path(build_root)

    setattr(config, "args_build_root", build_root)
    logger.debug(f"setting build_root to {build_root}")

    # Assumption is that the Core file target is 'flist'.
    flags = {
        "target": "flist",
    }

    try:
        flags = dict(core.get_flags(flags["target"]), **flags)
    except SyntaxError as e:
        logger.error(str(e))
        exit(1)
    except RuntimeError as e:
        logger.error(str(e))
        exit(1)

    try:
        _, backend = fs.get_backend(
            core,
            flags,
        )
    except RuntimeError as e:
        logger.error(str(e))
        exit(1)
    except FileNotFoundError as e:
        logger.error(f'Could not find EDA API file "{e.filename}"')
        exit(1)

    try:
        backend.configure()
    except RuntimeError as e:
        logger.error("Failed to configure the system")
        logger.error(str(e))
        exit(1)

    # Get the path to the generated filelist.  We use the sanitized core name
    # in order to avoid globbing another filelist if the same build_root has
    # been used for multiple core files.  There should only ever be a single
    # glob result.
    glob_dir = build_root / core.name.sanitized_name
    src = list(glob_dir.glob("**/*.f"))[0]

    # Specify the destimation path.  The user can override the default which
    # is to output the filelist at the same path as the parent Core file.
    if output:
        dst = Path(output).absolute()
        assert dst.suffix == ".f", "expecting a .f suffix for filelist path"
    else:
        dst = (core_root / core.core_basename).with_suffix(".f")
    shutil.copy2(src, dst)

    return dst


def get_parser():
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
    parser.add_argument("-o", "--output", help="specify where to dump the filelist")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="use verbose logging",
    )
    return parser


def main():
    args = get_parser().parse_args()

    Fusesoc.init_logging(verbose=args.verbose, monochrome=False)

    filelist = flist(name=args.core, build_root=args.build_root, output=args.output)

    logger.info(f"Created filelist {filelist}")
