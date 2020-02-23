#!/usr/bin/env python3

"""
    Copyright(c) 2020 Bifferos@gmail.com
    Parallel-tasking Slack builds with dependency resolution.
"""

import os
import re
import argparse
from pathlib import Path
from configparser import ConfigParser
import sys
import json
import copy
import shutil
import tempfile
from subprocess import Popen, PIPE
from threading  import Thread, Lock, get_ident
from queue import Queue, Empty
import xmlrpc.client as xmlrpclib
import pickle
from urllib.parse import urlparse
import getpass


HOME = Path.home()
if getpass.getuser() != "root":
    print("sorry, root users only")
    sys.exit(1)


INSTALLED_PACKAGES_DIR = Path("/var/lib/pkgtools/packages")


AFTERPKG_DIR = HOME / ".afterpkg"
AFTERPKG_DIR.mkdir(parents=True, exist_ok=True)

# Directory structure mimicking the SBo one
DOWNLOAD_PKG_DIR = AFTERPKG_DIR / "downloads"
DOWNLOAD_PKG_DIR.mkdir(parents=True, exist_ok=True)

SBO_DIR = AFTERPKG_DIR / "slackbuilds"
SCRIPTS_DIR = AFTERPKG_DIR / "scripts"
BOT_WORKING_DIRS = AFTERPKG_DIR / "bots"
PYPI_PICKLE = AFTERPKG_DIR / "pypi.pickle"

# Use for both the installpkg and pip install steps.
INSTALLER_LOCK = Lock()
DOWNLOAD_LOCK = Lock()


class NoOpLock:
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


def list_local_pip_packages(version):
    """
        Run pip to determine locally installed packages.
        Empty version string == py2, '3' == py3
    """
    command = "pip%s list --format json" % version
    p = Popen(command, stdout=PIPE, shell=True)
    sout, err = p.communicate("")
    out = set()
    for d in json.loads(sout):
        name = d["name"]
        if name.startswith("-"):
            name = name[1:]
        out.add(name)
    return out


def get_installed_packages():
    rex = re.compile("^(.*)-([^-]*)-([^-]*)-([^-]*)$")

    out = set()
    for path in INSTALLED_PACKAGES_DIR.iterdir():
        m = rex.match(path.name)
        if m:
            out.add(m.group(1))
    return out


def read_info(path):
    """Read a fields of .info file"""
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
            result[option] = cfg.get(section, option).strip('"')
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
        self.pypi_local_py2 = list_local_pip_packages("")
        self.pypi_local_py3 = list_local_pip_packages("3")
        self.slack_pkg_local = get_installed_packages()
        self.py_rex = re.compile("^(python3?-)(.*)$")
        self.pip_rex = re.compile("^python(3?)-(.*)$")
        self.novirtual = novirtual


    def is_python_package(self, name):
        """It would be nice if all SBo python packages started python- but they don't"""
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
        # Then I guess it's not a python package.
        return False


    def get_pip_version(self, name):
        """Figure out the pip version needed to install said package.  Basically use pip3 for anything python3-"""
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


    def lookup_deps(self, pkg):
        """
            Find the SBo defined deps (.info file) for a given package
            Remove any installed packages we're not interested in building those.
            We don't count non-SBo packages as dependencies.  They can't be installed anyhow so there's no point.
        """
        pkg_info = self.package_dirs[pkg] / (pkg + ".info")
        deps = set(read_info(pkg_info)["REQUIRES"].split(" "))
        deps -= self.ignore
        out = set()
        for dep in deps:
            if self.has_local_package(dep):
                continue
            if self.is_sbo_pkg(dep):
                out.add(dep)
        return out


    def get_source_location(self, name):
        """Get the path to the SBo SlackBuild Directory"""
        return self.package_dirs[name]


    def is_sbo_pkg(self, pkg):
        """Is the package an SBo one?"""
        return pkg in self.package_dirs


class ScriptManager:
    def __init__(self, path, args):
        self.before = {}
        self.after = {}
        for category in path.iterdir():
            if not category.is_dir() or category.name.startswith("."):
                continue
            for package in category.iterdir():
                for script in ["before", "after"]:
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


def output_thread(fp, console_q, quit_q, package, bot_index):
    """
        read from fp, tag the data and put it on the console queue.  package and bot_index are just passed on
        after eof, signal we're done on quit_q.
    """
    while True:
        text = fp.readline()
        if not text:
            break
        console_q.put((text, package, bot_index))

    # When there's no more data (empty-string read) signal the bot that we quitting
    quit_q.put(get_ident())


def get_built_package_location(name):
    rex = re.compile("^(.*)-([^-]*)-([^-]*)-([^-]*)$")
    for path in Path("/tmp").iterdir():
        m = rex.match(path.stem)
        if m:
            if name == m.group(1):
                return path
    raise ValueError("Unable to find built package location, build may have failed.")


class Runner:
    def __init__(self, working_dir, console, package, bot_index):
        self.working_dir = working_dir
        self.console = console
        self.package = package
        self.bot_index = bot_index

    def exec(self, command):
        """"Execute a command from a bot thread"""
        open_handles = {}

        p = Popen(command, stdout=PIPE, stderr=PIPE, shell=True, bufsize=0, cwd=str(self.working_dir))

        console_quit_q = Queue()

        # These threads only exist as long as the package build
        sout = Thread(target=output_thread, args=(p.stdout, self.console, console_quit_q, self.package, self.bot_index))
        sout.daemon = True
        sout.start()
        open_handles[sout.ident] = None

        serr = Thread(target=output_thread, args=(p.stderr, self.console, console_quit_q, self.package, self.bot_index))
        serr.daemon = True
        serr.start()
        open_handles[serr.ident] = None

        # This loop will exit when the package is built.
        while open_handles:
            try:
                output_quit = console_quit_q.get(True, 0.5)
                del open_handles[output_quit]
            except Empty:
                pass


def bot_thread(job_q, done_q, dep_manager, console, scripts, bot_index, args):
    """
        build and install packages named on job_q, push name to done_q when done.  console and bot_index are passed on
        Signal it's over with quit_q
    """
    working_dir = BOT_WORKING_DIRS / ("%d" % bot_index)

    download_lock = DOWNLOAD_LOCK if args.getinparallel else NoOpLock()

    package = True
    while package:
        package = job_q.get(True)
        if package is None:
            return

        runner = Runner(working_dir, console, package, bot_index)

        if args.pipinstall:
            # Have a go at installing with pip.  If we can't still try to let SBo do it
            if dep_manager.is_python_package(package):
                pypi = dep_manager.sbo_to_pypi(package)
                pip_ver = dep_manager.get_pip_version(package)
                with INSTALLER_LOCK:
                    if args.donothing:
                        runner.exec('echo %s install %s' % (pip_ver, pypi))
                    else:
                        runner.exec('echo %s install %s' % (pip_ver, pypi))

                done_q.put(package)
                continue

        if working_dir.exists():
            shutil.rmtree(working_dir)

        # Working dir
        src_path = dep_manager.get_source_location(package)
        shutil.copytree(src_path, working_dir)

        info = working_dir / (package + ".info")

        # Download step
        urls = read_info(info)["DOWNLOAD_x86_64"]
        if not urls:
            urls = read_info(info)["DOWNLOAD"]
        with download_lock:
            if args.donothing:
                runner.exec("echo Downloading %s" % urls)
            else:
                category = dep_manager.get_source_location(package).parent.name
                download_dir = DOWNLOAD_PKG_DIR / category / package
                download_dir.mkdir(parents=True, exist_ok=True)
                for url in urls.split(" "):
                    url_parsed = urlparse(url)
                    file_name = Path(url_parsed.path).name
                    download_location = download_dir / file_name
                    if not download_location.exists():
                        runner.exec("wget -O %s %s" % (download_location, url))
                    shutil.copyfile(download_location, working_dir / file_name)

        if args.onlydownload:
            done_q.put(package)
            continue

        handle, temp_wrapper = tempfile.mkstemp(suffix=".sh", dir=working_dir, text=False)
        os.close(handle)

        total_script = b'#!/bin/sh\n'
        before = scripts.get_before(package)
        if before:
            if args.donothing:
                total_script += ('echo "Running before script for %s"\n' % package).encode("utf-8")
            else:
                total_script += before.open("rb").read()

        build_script = working_dir / (package + ".SlackBuild")
        if args.donothing:
            total_script += ('echo "Running build script %s"\n' % (package + ".SlackBuild")).encode("utf-8")
        else:
            total_script += build_script.open("rb").read()


        after = scripts.get_after(package)
        if after:
            if args.donothing:
                total_script += ('echo "Running after script for %s"\n' % package).encode("utf-8")
            else:
                total_script += after.open("rb").read()

        open(temp_wrapper, "wb").write(total_script)
        os.chmod(temp_wrapper, 0o755)
        runner.exec(temp_wrapper)

        with INSTALLER_LOCK:
            if args.donothing:
                runner.exec('echo "installing %s"' % package)
            else:
                built_location = get_built_package_location(package)
                runner.exec("installpkg %s" % str(built_location))

        done_q.put(package)


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


def get_leaf_packages(packages, dep_manager, built):
    """Return the set of packages with no deps other than the ones built"""
    out = set()
    for package in packages:
        deps = dep_manager.lookup_deps(package)
        if deps - built:
            continue
        out.add(package)
    return out


def start_build_engine(dep_manager, packages, scripts, args):
    """packages is the list of packages to build"""

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

    remaining = copy.copy(packages)
    built = set()

    while remaining:
        # Figure out the set of packages that we can queue.  These will be the ones with no (un-built) dependencies.
        for package in get_leaf_packages(remaining, dep_manager, built):
            job_q.put(package)
            remaining.remove(package)

        # Wait for a package to get built, then re-assess which packages are ready.
        done = done_q.get(True)
        built.add(done)


    # Signal the bots to drop out of their job processing loops.
    for _ in range(int(args.numthreads)):
        job_q.put(None)

    # The controller will quit when the bots quit
    bot_controller.join()

    # Tell the console thread we're done with it otherwise it'll wait forever for more input
    console_q.put((None, None, None))

    # Wait for any remaining console output to flush before continuing.
    console_controller.join()


def resolve_dependencies(dep_manager, package_name, resolved):
    """
        Ends up with a list of all packages that need to be built in resolved.
    """
    deps = dep_manager.lookup_deps(package_name)
    # It's nice if the queue is ordered the same way on each run.  This won't necessarily be build
    # order though, unless there's only one thread.
    sort_deps = list(deps)
    sort_deps.sort()
    for dep in sort_deps:
        resolve_dependencies(dep_manager, dep, resolved)
    if package_name in resolved:
        return
    if dep_manager.has_local_package(package_name):
        print("# Skipping build of %s, already installed" % package_name)
        return
    resolved.append(package_name)


def build_packages(args):
    dep_manager = DependencyManager(SBO_DIR, args.novirtual)
    scripts = ScriptManager(SCRIPTS_DIR, args)

    resolved = []
    for package in args.packages:
        resolve_dependencies(dep_manager, package, resolved)

    if args.queue:
        for package in resolved:
            print(package)
    else:
        start_build_engine(dep_manager, resolved, scripts, args)


def main():
    parser = argparse.ArgumentParser(prog='afterpkg',
            description="Build and install packages from an SBo repo. Afterpkg expects a full install of -current and "
                        "the SBo repo to be found at ~/.afterpkg/slackbuilds/.  You will need to clone or copy it there. "
                        "By default most functionality is enabled, the options described below mostly DISABLE functionality")

    parser.add_argument("-d", "--donothing", default=False, action="store_true",
                        help="Don't actually build any packages, just list the steps that would be run")
    parser.add_argument("-n", "--numthreads", default="1",
                        help="How many parallel builds to allow (default 1)")
    parser.add_argument("-c", "--nocolour", default=False, action="store_true",
                        help="Parallel builds are normally coloured.  If you don't like vt100 escape codes in your output, use this option "
                             "You can still distinguish threads by the output line prefix")
    parser.add_argument("-o", "--onlydownload", default=False, action="store_true",
                        help="This will only download the package sources and not build, so you can run the rest of the build offline")
    parser.add_argument("-v", "--novirtual", default=False, action="store_true",
                        help="Don't include any pip-installed Python packages in dependency computations (same as -2 and -3)")
    parser.add_argument("-2", "--nopip2", default=False, action="store_true",
                        help="Don't include pip2-installed Python packages in dependency computations")
    parser.add_argument("-3", "--nopip3", default=False, action="store_true",
                        help="Don't include pip3-installed Python packages in dependency computations")
    parser.add_argument("-p", "--pipinstall", default=False, action="store_true",
                        help="By default Python SBo packages will be built and installed as required. This option "
                             "will pip install them instead.  Note that this option makes -o somewhat pointless, as it requires "
                             "you to be online.  You can always pip install everything before you start, however.")
    parser.add_argument("-b", "--before", default=False, action="store_true",
                        help="Don't include before scripts")
    parser.add_argument("-a", "--after", default=False, action="store_true",
                        help="Don't include after scripts")
    parser.add_argument("-i", "--install", default=False, action="store_true",
                        help="Install only the minimum.  Only build-time dependencies of other packages will be installed. "
                             "By default all packages will be installed.")
    parser.add_argument("-g", "--getinparallel", default=False, action="store_true",
                        help="Normally downloads will be one-by-one.  This will run them in parallel (up to --numthreads)")
    parser.add_argument("-q", "--queue", default=False, action="store_true",
                        help="Just print the queue of builds, similar to what sqj would generate. You can use afterpkg to only "
                        "compute dependencies, generate an sbopkg queue and then run the builds with sbopkg if you prefer.")

    parser.add_argument("packages", default=False, nargs="+",
                        help="Package(s) to build")
    args = parser.parse_args()
    build_packages(args)


if __name__ == "__main__":
    main()

