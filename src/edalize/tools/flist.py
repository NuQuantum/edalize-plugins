import argparse
import logging
import os
import shutil
from pathlib import Path

from edalize.tools.edatool import Edatool
from edalize.utils import EdaCommands
from fusesoc.fusesoc import Config
from fusesoc.fusesoc import Fusesoc
from fusesoc.main import _get_core

logger = logging.getLogger(__name__)


class Flist(Edatool):

    description = "F-list generator"

    TOOL_OPTIONS = {}

    def setup(self, edam):
        super().setup(edam)

        self.f = []

        for key, value in self.vlogdefine.items():
            define_str = self._param_value_str(param_value=value)
            self.f.append(f"+define+{key}={define_str}")

        for key, value in self.vlogparam.items():
            param_str = self._param_value_str(param_value=value, str_quote_style='"')
            self.f.append(f"-pvalue+{self.toplevel}.{key}={param_str}")

        incdirs = []
        vlog_files = []
        depfiles = []
        unused_files = []

        for f in self.files:
            file_type = f.get("file_type", "")
            depfile = True
            if file_type.startswith("systemVerilogSource") or file_type.startswith(
                "verilogSource",
            ):
                if not self._add_include_dir(f, incdirs):
                    vlog_files.append(f["name"])
            else:
                unused_files.append(f)
                depfile = False

            if depfile:
                depfiles.append(f["name"])

        for include_dir in incdirs:
            self.f.append(f"+incdir+{self.absolute_path(include_dir)}")

        for vlog_file in vlog_files:
            self.f.append(f"{self.absolute_path(vlog_file)}")

        self.edam = edam.copy()
        self.edam["files"] = unused_files

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


def flist(name, build_root=None):
    """ """
    config = Config()
    fs = Fusesoc(config)
    core = _get_core(fs, name)
    core_root = Path(core.core_root)

    if not build_root:
        build_root = core_root / ".flist"
    else:
        build_root = Path(build_root)

    setattr(config, "args_build_root", build_root)

    flags = {"target": "flist"}

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

    glob_dir = build_root / core.name.sanitized_name
    src = list(glob_dir.glob("**/*.f"))[0]
    dst = (core_root / core.core_basename).with_suffix(".f")
    shutil.copy2(src, dst)
    return dst


def get_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("core", help="VLNV of system to filelist")
    parser.add_argument(
        "--build-root",
        help=(
            "override the FuseSoC build root which by default will be parallel to the"
            " core file"
        ),
    )
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

    filelist = flist(name=args.core, build_root=args.build_root)
    logger.info(f"Created filelist {filelist}")
