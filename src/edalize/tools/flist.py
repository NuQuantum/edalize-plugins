import os
import sys
import argparse
import subprocess
import logging
import shutil
import tempfile

from edalize.tools.edatool import Edatool
from edalize.utils import EdaCommands

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
                "verilogSource"
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
            }
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


def post_process(src, dst):
    
    soc_repo_root = os.environ.get('SOC_REPO_ROOT')
    with open(dst, 'w') as ofile:
        with open(src, 'r') as ifile:
            for line in ifile.readlines():
                line.rstrip()
                line = line.replace(soc_repo_root, '$SOC_REPO_ROOT')
                ofile.write(line)


def flist(args):

    from fusesoc.main import init_logging
    from fusesoc.vlnv import Vlnv
    import glob

    init_logging(verbose=False, monochrome=False)

    try:
        core_info = subprocess.check_output(
            ["fusesoc", "core", "show", args.system],
            stderr=subprocess.STDOUT,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error(e.output)
        sys.exit(1)

    for line in core_info.split('\n'):
        if line.startswith('Core root:'):
            _,path = line.split(':')
            core_root = path.strip()
        if line.startswith('Core file:'):
            _,filename = line.split(':')
            core_file = filename.strip()

    dst = os.path.join(core_root, core_file.replace('.core', '.f'))

    with tempfile.TemporaryDirectory() as dir:
        try:
            subprocess.check_output(
                ["fusesoc", "run", "--no-export", "--build-root", dir, "--target", "flist", args.system],
                stderr=subprocess.STDOUT,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error(e.output)
            sys.exit(1)

        src = glob.glob(f"{dir}/**/*.f", recursive=True)[0]
        post_process(src, dst)
        logger.info(f"Created filelist at {dst}")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "system", help="FuseSoC VLNV"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    flist(args)