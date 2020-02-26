#!/usr/bin/env python3
"""
    Copyright(c) 2020 bifferos@gmail.com UK
    All rights reserved.

    Redistribution and use of this script, with or without modification, is
    permitted provided that the following conditions are met:

    1. Redistributions of this script must retain the above copyright
       notice, this list of conditions and the following disclaimer.

     THIS SOFTWARE IS PROVIDED BY THE AUTHOR "AS IS" AND ANY EXPRESS OR IMPLIED
     WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
     MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO
     EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
     SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
     PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
     OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
     WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
     OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
     ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

import argparse
import copy
import json
import os
import pickle
import re
import sys
import time

from configparser import ConfigParser
from pathlib import Path
from queue import Queue
from subprocess import Popen, PIPE
from threading  import Thread, Lock
from urllib.parse import urlparse
import xmlrpc.client as xmlrpclib


PROGNAME = "afterpkg"

# These can only be local
SCRIPTS_DIR = Path(os.path.expanduser(f"~/.{PROGNAME}/scripts"))
PYPI_PICKLE = Path(os.path.expanduser(f"~/.{PROGNAME}/pypi.pickle"))

BOT_STATUS = Path(os.path.expanduser(f"~/.{PROGNAME}"))


# Can be local or remote
INSTALLED_PACKAGES_DIR = Path("/var/lib/pkgtools/packages")
BOT_WORKING_DIRS = Path(f"~/.{PROGNAME}/bots")
DOWNLOAD_PKG_DIR = Path(f"~/.{PROGNAME}/downloads")

# Use for both the installpkg and pip install steps.
INSTALLER_LOCK = Lock()
DOWNLOAD_LOCK = Lock()


# Remote host to talk to, if requested on the command-line
g_ssh_host = None


def get_remote_command(command):
    """
        Return the command to be executed, taking into account g_ssh_host setting.
    """
    if g_ssh_host:
        command = f'ssh {g_ssh_host} "{command}"'
    return command


def put_file_to_remote(src, dest):
    """
        Return the command to copy directory of files locally or remotely depending on g_ssh_host setting
    """
    dest = str(dest)
    if dest.startswith("~/"):
        dest = dest[2:]
    if g_ssh_host:
        command = f"scp -r {src} {g_ssh_host}:{dest}"
    else:
        command = f"cp -r {src} {dest}"
    return command


def remote_popen(command):
    """
        Run a command and fetch the output, don't care about return code.  Use this only when you don't care about the
        result, e.g. md5sum will give either the correct md5 or something else, we don't care what.
    """
    command = get_remote_command(command)
    p = Popen(command, stdout=PIPE, stderr=PIPE, shell=True)
    sout, _ = p.communicate("")
    return sout.decode("utf-8")


def find_scripts_location():
    """
        If the script location is
    """
    # If this is running from a git repo, scripts are in subdirs.
    p = Popen("git rev-parse --git-dir", stdout=PIPE, stderr=PIPE, shell=True, cwd=sys.path[0])
    _, _ = p.communicate("")
    if p.returncode == 0:
        return Path(sys.path[0]) / "scripts"
    else:
        # Otherwise look for scripts in ~/.afterpkg/scripts
        return SCRIPTS_DIR


class NoOpLock:
    """A do-nothing context manager"""
    def __enter__(self):
        pass
    def __exit__(self, _type, value, traceback):
        pass


def list_all_pypi_packages():
    """
        Download and cache the entire list of packages from pypi.  This takes a couple of seconds but it's cached
        to be considerate to the server.  You'll need to periodically delete the downloaded file yourself.
    """
    if PYPI_PICKLE.exists():
        return pickle.loads(PYPI_PICKLE.open("rb").read())
    else:
        print("Downloading package list from pypi")
        client = xmlrpclib.ServerProxy('https://pypi.python.org/pypi')
        # get a list of package names
        packages = client.list_packages()
        data = pickle.dumps(packages)
        PYPI_PICKLE.open("wb").write(data)
        return packages


def get_installed_packages():
    """Figure out the list of installed packages, including Slackware core ones.  Return as a set."""
    rex = re.compile("^(.*)-([^-]*)-([^-]*)-([^-]*)$")
    out = set()
    for line in remote_popen("ls %s" % INSTALLED_PACKAGES_DIR).split("\n"):
        m = rex.match(line.strip())
        if m:
            out.add(m.group(1))
    return out


g_info_cache = {}


def read_info(path):
    """Read a fields of .info file"""
    if path in g_info_cache:
        return g_info_cache[path]

    cfg = ConfigParser(interpolation=None)
    cfg.optionxform = str
    with path.open("r") as fp:
        out = []
        for line in fp.readlines():
            if line[-2:] == "\\\n":
                out.append(line[:-2])
            else:
                out.append(line)
        section = "GLOBAL"
        pkg_info = ("[%s]\n" % section) + "".join(out)
        cfg.read_string(pkg_info)
        options = cfg.options(section)
        result = {}
        for option in options:
            value = cfg.get(section, option).strip('"')
            if option in ["REQUIRES", "MD5SUM_x86_64", "DOWNLOAD_x86_64", "DOWNLOAD", "MD5SUM"]:
                if value == '':
                    value = []
                else:
                    value = value.split(" ")
            result[option] = value
        g_info_cache[path] = result
        return result


# Special cases
sbo_to_pypi_specials = [
    ("python-cheetah",              "Cheetah"),
    ("python-django-legacy",        "Django"),
    ("python-xrandr",               None),       #
    ("python-importlib_metadata",   "importlib-metadata"),
    ("python-uri-templates",        "uri-template"),
    ("python-pmw",                  "Pmw"),
    ("python-django",               "Django"),
    ("python-distutils-extra",      None),       #
    ("python-elib.intl",            "elib"),
    ("python-configargparse",       "ConfigArgParse"),
    ("python-slip",                 "SLIP"),
    ("python-setuptools-doc",       None),       #
    ("python-keybinder",            None),       # python3-keybinder only?
    ("python-twisted",              "Twisted"),

    # Python 3
    ("python3-setuptools_autover",  None),
    ("python3-jupyter-ipykernel",   "ipykernel"),
    ("python3-django",              "Django"),
    ("python3-babel",               "Babel"),
    ("python3-prompt_toolkit",      "prompt-toolkit"),
    ("python3-cycler",              "Cycler"),
    ("python3-dvdvideo",            None),

    ("websocket-client",            "websocket_client"),
]


class DependencyManager:
    def __init__(self, path, novirtual):
        """path is the root of slackbuilds"""
        if not path.exists():
            print("No slackbuilds directory found at %s." % path)
            os.system(f"git -C ~/.{PROGNAME} ~/ clone https://github.com/Ponce/slackbuilds.git")

        self.ignore = {"%README%", ""}
        self.package_dirs = {}
        self.pySBo_all = set()
        for category in path.iterdir():
            if not category.is_dir() or category.name.startswith("."):
                continue
            for package in category.iterdir():
                name = package.name
                self.package_dirs[name] = package
                if name.startswith("python-") or name.startswith("python3-"):
                    self.pySBo_all.add(name)

        self.pypi_all = list_all_pypi_packages()
        self.pypi_local_py2 = self.list_local_pip_packages("")
        self.pypi_local_py3 = self.list_local_pip_packages("3")
        self.slack_pkg_local = get_installed_packages()
        self.py_rex = re.compile("^(python3?-)(.*)$")
        self.pip_rex = re.compile("^python(3?)-(.*)$")
        self.novirtual = novirtual


    def list_local_pip_packages(self, version):
        """
            Run pip to determine locally installed packages.
            Empty version string == py2, '3' == py3
        """
        command = f"pip{version} list --format json"
        sout = remote_popen(command)
        out = set()
        for d in json.loads(sout):
            name = d["name"]
            if name.startswith("-"):
                name = name[1:]
            out.add(name)
        return out

    def is_python_package(self, name):
        """
            TODO:  Figure out the combined python2-3 packages and what to do with them.
            Also this function is way too crude right now.
        """
        # Is it in the python category?
        path = self.package_dirs[name]
        if path.parent.name == "python":
            return True
        # does it start with python[3]-?
        if self.pip_rex.match(name):
            return True
        # Does it have a distutils step in the build script.
        build_script = self.package_dirs[name] / (name + ".SlackBuild")
        txt = build_script.open("rb").read()
        if txt.find(b"python setup.py install ") != -1:
            return True
        if txt.find(b"python3 setup.py install ") != -1:
            return True
        # Then I guess it's not a python package.
        return False


    def get_pip_version(self, name):
        """
            Figure out the pip version needed to install said package.  Basically use pip3 for anything python3-
            This is naive to say the least.
        """
        m = self.pip_rex.match(name)
        if not m:
            return "pip"
        return "pip" + m.group(1)


    def sbo_to_pypi(self, name):
        """
            Convert an SBo name to a pip name.  We assume is_python_package() has already been called to check.
            Not going to be foolproof but works for most cases above to give *something* that exists
            on pypi.  Of course that doesn't mean it's actually the same package, but it probably will be for anything
            I need!!!
        """
        # Remove any python[3]- prefix and see if the remaining string matches a pypi package.  Try py3 first, of course.
        m = self.py_rex.match(name)
        if m:
            to_try = name.replace(m.group(1), "", 1)
            if to_try in self.pypi_all:
                return to_try    # pypi exists with that name.

        # Try again without the prefix removed.
        if name in self.pypi_all:
            return name

        if m:
            # Before giving up, replace python3- with python- and try that.
            if m.group(1) == "python3-":
                to_try = name.replace("python3-", "python-", 1)
                if to_try in self.pypi_all:
                    return to_try

        # Go through the special-cases embedded in this script.  They generally involve case mismatches or dashes
        # Becoming underscores when the SlackBuild was created.
        for SBo, pypi in sbo_to_pypi_specials:
            if name == SBo:
                return pypi

        # As a last resort we'll assume we have to actually build the thing the conventional way.
        return None


    def has_local_package(self, sbo_name):
        """
            Check if the given package name is installed, either via pip or SBo
            if novirtual has been set, don't bother with virtual packages.
        """
        if sbo_name in self.slack_pkg_local:
            return True
        if self.novirtual:
            return False
        pip_pkg = self.sbo_to_pypi(sbo_name)
        if pip_pkg:
            if sbo_name.startswith("python3-"):
                if pip_pkg in self.pypi_local_py3:
                    return True
            if sbo_name.startswith("python-"):
                if pip_pkg in self.pypi_local_py2:
                    return True
        return False


    def lookup_deps(self, pkg, remove_local=True):
        """
            Find the SBo defined deps (.info file) for a given package
            Remove any installed packages we're not interested in building those.
            We don't count non-SBo packages as dependencies.  They can't be installed anyhow so there's no point.
        """
        if pkg not in self.package_dirs:
            return None
        pkg_info = self.package_dirs[pkg] / (pkg + ".info")
        deps = []
        for dep in read_info(pkg_info)["REQUIRES"]:
            if dep in self.ignore:
                continue
            if not self.is_sbo_pkg(dep):
                continue
            if remove_local:
                if self.has_local_package(dep):
                    continue
            deps.append(dep)
        return deps


    def _resolve_dependencies(self, package_names, resolved, remove_local):
        """
            Ends up with a list of all packages that need to be built in resolved.
        """
        for package_name in package_names:
            if package_name in resolved:
                continue
            deps = self.lookup_deps(package_name, remove_local)
            if deps is None:
                print("Package %r not found" % package_name)
                sys.exit(1)
            
            # It's nice if the queue is ordered the same way on each run.  This won't necessarily be build
            # order though, unless there's only one thread.
            if deps:
                self._resolve_dependencies(deps, resolved, remove_local)
            resolved.append(package_name)


    def resolve_dependencies(self, package_names, remove_local=True):
        resolved = []
        self._resolve_dependencies(package_names, resolved, remove_local)
        return resolved


    def get_source_location(self, name):
        """Get the path to the SBo SlackBuild Directory"""
        return self.package_dirs[name]


    def is_sbo_pkg(self, pkg):
        """Is the package an SBo one?"""
        return pkg in self.package_dirs


class ScriptManager:
    def __init__(self, path, args):
        self.script_types = ["before", "after", "requires"]
        self.before = {}
        self.after = {}
        self.requires = {}
        for script in self.script_types:
            setattr(self, script, {})
        for category in path.iterdir():
            if not category.is_dir() or category.name.startswith("."):
                continue
            for package in category.iterdir():
                for script in self.script_types:
                    if not getattr(args, script):
                        location = package / ("%s.sh" % script)
                        if location.exists():
                            getattr(self, script)[package.name] = location

    def get_before(self, package):
        if package in self.before:
            return self.before[package]

    def get_after(self, package):
        if package in self.after:
            return self.after[package]
            
    def get_requires(self, package):
        if package in self.requires:
            return self.requires[package]


def output_thread(fp, console_q, package, bot_index):
    """
        read from fp, tag the data and put it on the console queue.  package and bot_index are just passed on
        after eof, signal we're done on quit_q.
    """
    while True:
        text = fp.readline()
        if not text:
            break
        console_q.put((text, package, bot_index))


def get_built_package_location(name, info_dict):
    command = f"ls /tmp/{name}-" + info_dict["VERSION"] + "-*"
    out = []
    for path in remote_popen(command).split("\n"):
        if not path:
            continue
        out.append(path)
    if len(out) == 1:
        return out[0]
    raise ValueError("Unable to find built package location, build may have failed.")


class Runner:
    """
        Run programs from the bot, doing something sensible with the output.
    """
    def __init__(self, console, bot_index, donothing):
        self.console = console
        self.package = "<BOT>"
        self.bot_index = bot_index
        self.donothing = donothing

    def set_package(self, package):
        self.package = package

    def echo(self, text):
        self.console.put(((text+"\n").encode("utf-8"), self.package, self.bot_index))

    def exec(self, command, stdin_text=None):

        command = get_remote_command(command)
        if self.donothing:
            if stdin_text:
                self.echo(f'cat <script> | {command}')
            else:
                self.echo(f'{command}')
        else:
            self.run(command, stdin_text)

    def run(self, command, stdin_text=None):
        """"Execute a command from a bot thread"""

        if stdin_text:
            stdin_pipe = PIPE
        else:
            stdin_pipe = None

        p = Popen(command, stdout=PIPE, stderr=PIPE, stdin=stdin_pipe, shell=True, bufsize=0)

        # These threads only exist as long as the package build
        sout = Thread(target=output_thread, args=(p.stdout, self.console, self.package, self.bot_index))
        sout.daemon = True
        sout.start()

        serr = Thread(target=output_thread, args=(p.stderr, self.console, self.package, self.bot_index))
        serr.daemon = True
        serr.start()

        if stdin_text:
            p.stdin.write(stdin_text)
            p.stdin.close()

        sout.join()
        serr.join()
        p.wait()
        if p.returncode != 0:
            raise OSError("Error executing %r" % command)


    def copytree(self, src_path, dest_path):
        command = put_file_to_remote(src_path, dest_path)
        if self.donothing:
            self.echo(command)
        else:
            self.run(command)


def md5_sum(path):
    """Get the checksum of the passed path or None if non-existent"""
    rex = re.compile(r"^([a-f0-9]{32})\s+(\S+)$")
    for line in remote_popen(f"md5sum {path}").split("\n"):
        m =  rex.match(line.strip())
        if m:
            return m.group(1)
    return None


def required_source_files(info_dict):
    """Return a list of tuples of the [(url, fname and checksum), ...]"""
    urls = info_dict["DOWNLOAD_x86_64"]
    checksums = info_dict["MD5SUM_x86_64"]
    if not urls:
        urls = info_dict["DOWNLOAD"]
        checksums = info_dict["MD5SUM"]
    files = [Path(urlparse(url).path).name for url in urls]
    return zip(urls, files, checksums)


def download_file_commands(info_dict, download_dir):
    commands = []
    for url, fname, checksum in required_source_files(info_dict):
        download_location = download_dir / fname
        if md5_sum(download_location) != checksum:
            command = "wget --no-check-certificate -O %s %s" % (download_location, url)
            commands.append((command, download_location))
    return commands


class JobContext:
    def __init__(self, queue, package):
        self.queue = queue
        self.package = package
    def __enter__(self):
        pass
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.queue.put(self.package)
        else:
            self.queue.put(None)


def bot_thread(job_q, done_q, dep_manager, console, scripts, bot_index, args):
    """
        download, build and install packages on job_q, push name to done_q when done.
    """
    runner = Runner(console, bot_index, args.donothing)

    bot_working_dir = BOT_WORKING_DIRS / ("%02d" % bot_index)
    runner.exec("rm -rf %s" % bot_working_dir)
    runner.exec("mkdir -p %s" % bot_working_dir)

    job_count = 0
    download_lock = DOWNLOAD_LOCK if args.getinparallel else NoOpLock()

    package = True
    while package:
        package = job_q.get(True)
        if package is None:
            return

        with JobContext(done_q, package):
            runner.set_package(package)
            job_count += 1

            working_dir = bot_working_dir / ("%03x_%s" % (job_count, package))

            src_path = dep_manager.get_source_location(package)
            info = src_path / (package + ".info")

            if args.pipinstall:
                # Have a go at installing with pip.  If we can't still try to let SBo do it
                if dep_manager.is_python_package(package):
                    pypi = dep_manager.sbo_to_pypi(package)
                    pip_ver = dep_manager.get_pip_version(package)
                    with INSTALLER_LOCK:
                        runner.exec('%s install %s' % (pip_ver, pypi))
                    continue

            runner.exec("rm -rf %s" % working_dir)
            runner.copytree(src_path, working_dir)

            # Download step
            info_dict = read_info(info)
            category = dep_manager.get_source_location(package).parent.name
            download_dir = DOWNLOAD_PKG_DIR / category / package
            for command, location in download_file_commands(info_dict, download_dir):
                runner.exec("mkdir -p %s" % download_dir)
                with download_lock:
                    runner.exec(command)
                    
            for url, file_name, checksum in required_source_files(info_dict):
                runner.exec("cp %s %s" % (download_dir / file_name, working_dir / file_name))

            if args.onlydownload:
                continue

            temp_wrapper = working_dir / "afterpkg-build.sh"

            total_script = b'#!/bin/sh\n'
            before = scripts.get_before(package)
            if before:
                runner.echo('Adding *before* script for %s' % package)
                total_script += before.open("rb").read()

            for dep_package in dep_manager.resolve_dependencies([package], False):
                if  dep_package == package:
                    continue
                requires = scripts.get_requires(dep_package)
                if requires:
                    runner.echo('Adding *requires* script for %s' % dep_package)
                    total_script += requires.open("rb").read()

            runner.echo('Adding *build* script %s' % (package + ".SlackBuild"))

            build_script = src_path / (package + ".SlackBuild")
            total_script += build_script.open("rb").read()

            after = scripts.get_after(package)
            if after:
                runner.echo('Adding *after* script for %s' % package)
                total_script += after.open("rb").read()

            runner.exec(f"dd of={temp_wrapper}", total_script)
            runner.exec(f"cd {working_dir} && sh {temp_wrapper}")

            with INSTALLER_LOCK:
                built_location = "/tmp/%s-%s-...tgz" % (package, info_dict["VERSION"])
                if not args.donothing:
                    built_location = get_built_package_location(package, info_dict)
                runner.exec("installpkg %s" % str(built_location))


COLOURS = {
        0: '\x1b[39m',  # normal
        1: '\x1b[91m',  # red
        2: '\x1b[94m',  # blue
        3: '\x1b[93m',  # yellow
        4: '\x1b[95m',  # magenta
        5: '\x1b[96m',  # cyan
    }

REVERT_COLOUR = '\x1b[0m'


def console_thread(console_q, args):
    """read console_q, write => stdout"""
    if args.nocolour:
        colour, revert_colour = [""]*6, ""
    else:
        colour, revert_colour = COLOURS, REVERT_COLOUR

    while True:
        text, package, bot_index = console_q.get(True)
        if text is None:
            break

        if int(args.numthreads) == 1:
            prefix = f"{package}: "
        else:
            prefix = f"[{bot_index}]:{package}: "

        sys.stdout.write(colour[bot_index % 6] + prefix + text.decode("utf-8") + revert_colour)


def bot_controller_thread(job_q, done_q, console_q, dep_manager, scripts, args):
    """Fire up a thread per build bot"""        
    bot_threads = []

    int(args.numthreads)
    for bot_index in range(int(args.numthreads)):
        bot = Thread(target=bot_thread, args=(job_q, done_q, dep_manager, console_q, scripts, bot_index, args))
        bot.daemon = True
        bot.start()
        bot_threads.append(bot)

    for thread in bot_threads:
        thread.join()


def write_bot_status(ident, value):
    bot_status = BOT_STATUS / f"{ident}.txt"
    bot_data = "\n".join(value) + "\n"
    bot_status.open("wb").write(bot_data.encode("utf-8"))


def start_build_engine(dep_manager, packages, scripts, args):
    """packages is the list of packages to build"""

    remote_popen("rm -rf %s" % BOT_WORKING_DIRS)

    job_q = Queue()
    done_q = Queue()
    console_q = Queue()

    # To avoid all the bots chopping each other's output, this thread syncs and colourises it.
    console_controller = Thread(target=console_thread, args=(console_q, args))
    console_controller.daemon = True
    console_controller.start()

    # This thread controls the bots.
    bot_controller = Thread(target=bot_controller_thread, args=(job_q, done_q, console_q, dep_manager, scripts, args))
    bot_controller.daemon = True
    bot_controller.start()

    pending = copy.copy(packages)
    built = set()

    has_error = False

    while pending:
        # Figure out the set of packages that we can queue.  These will be the ones with no (un-built) dependencies.
        queued = []
        for package in pending:
            if set(dep_manager.lookup_deps(package)) - built:
                continue
            job_q.put(package)
            queued.append(package)
            
        pending = [i for i in pending if i not in queued]
        write_bot_status("pending", pending)
        write_bot_status("built", built)

        # Wait for a package to get built, then re-assess which packages are ready.
        done = done_q.get(True)
        if done is None:
            print("There was an error, shutting down...")
            has_error = True
            break

        built.add(done)


    # Signal the bots to drop out of their job processing loops.
    for _ in range(int(args.numthreads)):
        job_q.put(None)

    if has_error:
        time.sleep(0.5)  # Hopefully enough time for the exception to get printed.
        sys.exit(1)

    # The controller will quit when the bots quit
    bot_controller.join()

    # Tell the console thread we're done with it otherwise it'll wait forever for more input
    console_q.put((None, None, None))

    # Wait for any remaining console output to flush before continuing.
    console_controller.join()


def read_packages_from_stdin(slackbuilds):
    if len(slackbuilds) != 1:
        print("Only a single dash '-' allowed for reading packages on stdin", file=sys.stderr)
        sys.exit(1)
    out = []
    for line in sys.stdin.readlines():
        text = line.partition("#")[0].strip()
        if not text:
            continue
        out.append(text)
    return out


def build_packages(args):
    global g_ssh_host
    g_ssh_host = args.targethost

    if "-" in args.packages:
        packages = read_packages_from_stdin(args.packages)
    else:
        packages = args.packages


    dep_manager = DependencyManager(Path(args.slackbuilds), args.novirtual)
    scripts = ScriptManager(find_scripts_location(), args)

    resolved = dep_manager.resolve_dependencies(packages, True)

    if args.queue:
        for package in resolved:
            print(package)
    else:
        start_build_engine(dep_manager, resolved, scripts, args)


def main():
    parser = argparse.ArgumentParser(prog=f'{PROGNAME}',
            description=f"Download, build and install packages from SBo-current. {PROGNAME} expects a full install of -current and "
                        f"the SBo repo to be found at ~/.{PROGNAME}/slackbuilds/, if missing the ponce repo will be cloned there.  "
                        "By default most functionality is enabled, the options described below mostly DISABLE things.")

    parser.add_argument("-s", "--slackbuilds", default=os.path.expanduser(f"~/.{PROGNAME}/slackbuilds"),
                        help=f"Specify the slackbuild directory.  The default is ~/.{PROGNAME}/slackbuilds.  This directory will be "
                             "cloned from https://github.com/Ponce/slackbuilds.git if not present.  This will happen regardless "
                             "of the -d flag (it's not counted as doing anything).  If you want a different repository make sure "
                             "this exists before running.")
    parser.add_argument("-d", "--donothing", default=False, action="store_true",
                        help="Don't actually do anything, just list the steps that would be run.  Note that this doesn't disable "
                             "threading:  The steps will be output on different threads, just as any real task would, which "
                             "means they can be executed in random order. If you don't like this don't use -d with -n")
    parser.add_argument("-n", "--numthreads", default="1",
                        help="How many parallel operations to allow (default 1).  See also the -g option.")
    parser.add_argument("-c", "--nocolour", default=False, action="store_true",
                        help="Parallel builds are normally coloured.  If you don't like vt100 escape codes in your output, use "
                             "this option. You can still distinguish threads by the output line prefix")
    parser.add_argument("-o", "--onlydownload", default=False, action="store_true",
                        help="This will only download the package sources and not build, so you can run the build offline")
    parser.add_argument("-v", "--novirtual", default=False, action="store_true",
                        help="Don't include any pip-installed Python packages in dependency computations (same as -2 and -3)")
    parser.add_argument("-2", "--nopip2", default=False, action="store_true",
                        help="Don't include pip2-installed Python packages in dependency computations")
    parser.add_argument("-3", "--nopip3", default=False, action="store_true",
                        help="Don't include pip3-installed Python packages in dependency computations")
    parser.add_argument("-p", "--pipinstall", default=False, action="store_true",
                        help="By default Python SBo packages will be built and installed as required. This option "
                             "will pip install them instead.  Note that this makes -o somewhat pointless, as it requires "
                             "you to be online.  You can always pip install everything first, however.")
    parser.add_argument("-b", "--before", default=False, action="store_true",
                        help="Don't execute any 'before' scripts.  These scripts will get sourced before building the package.")
    parser.add_argument("-a", "--after", default=False, action="store_true",
                        help="Don't execute any 'after' scripts.  These scripts will get sourced after building the package.")
    parser.add_argument("-r", "--requires", default=False, action="store_true",
                        help="Don't execute any 'requires' scripts.  These scripts will get sourced before executing the builds of "
                             "dependent packages.")
    parser.add_argument("-g", "--getinparallel", default=False, action="store_true",
                        help="Normally downloads will be one-by-one.  This will run them in parallel (up to --numthreads)")
    parser.add_argument("-q", "--queue", default=False, action="store_true",
                        help=f"Just print the queue of builds, similar to what sqg would generate. You can use {PROGNAME} to only "
                        "compute dependencies, generate an sbopkg queue and then run the builds with sbopkg if you prefer.")
    parser.add_argument("-t", "--targethost", default=None, metavar='HOST',
                        help="Specify the remote host to run build commands on. This could be root@host or something defined "
                             "in your ssh config.  You should employ ssh-copy-id or otherwise update ~/.ssh/authorized_hosts"
                             f"on the host to avoid password prompts as {PROGNAME} will not prompt you and just fail without this. ")

    parser.add_argument("packages", default=False, nargs="+",
                        help="Package(s) to build.  If dash '-' is specified, reads package list from stdin, one-per-line"
                             "Hash characters '#' will be considered comments and those lines (or ends of lines) will be ignored.")

    args = parser.parse_args()
    build_packages(args)


if __name__ == "__main__":
    main()

