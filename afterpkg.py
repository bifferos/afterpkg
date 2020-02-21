#!/usr/bin/env python3

"""
"""

import os
import argparse
from pathlib import Path
from configparser import ConfigParser


def read_config(path):
    with path.open("r") as fp:
        out = []
        for line in fp.readlines():
            if line[-2:] == "\\\n":
                out.append(line[:-2])
            else:
                out.append(line)
        return "[DEFAULT]\n" + "".join(out)


class DependencyManager:
    def __init__(self, path=Path("/var/lib/sbopkg/SBo-git")):
        """path is the root of slackbuilds"""
        ignore = {"%README%", ""}
        self.packages = {}
        for category in path.iterdir():
            if not category.is_dir() or category.name.startswith("."):
                continue
            for package in category.iterdir():
                pkg_info = package / (package.name + ".info")
                cfg = ConfigParser(interpolation=None)
                cfg.optionxform = str
                cfg.read_string(read_config(pkg_info))
                deps = cfg.get("DEFAULT", "REQUIRES").strip('"').split(" ")
                deps = set(deps)
                deps -= ignore
                self.packages[package.name] = deps

    def lookup_deps(self, pkg):
        return self.packages[pkg]

    def is_sbo_pkg(self, pkg):
        return pkg in self.packages


class ScriptManager:
    def __init__(self, path=Path(".")):
        self.before = {}
        self.after = {}
        for category in path.iterdir():
            if not category.is_dir() or category.name.startswith("."):
                continue
            for package in category.iterdir():
                before = package / "before.sh"
                after = package / "after.sh"
                if before.exists():
                    self.before[package.name] = before
                if after.exists():
                    self.after[package.name] = after

    def run_before(self, package):
        if package in self.before:
            os.system(self.before[package])

    def run_after(self, package):
        if package in self.after:
            os.system(self.after[package])


def build_package(dep_manager, script_manager, package_name, built):
    deps = dep_manager.lookup_deps(package_name)
    for dep in deps:
        if dep_manager.is_sbo_pkg(dep):    # Don't build anything from the core distro, assume full install
            build_package(dep_manager, script_manager, dep, built)
    if package_name in built:
        return
    script_manager.run_before(package_name)
    print("running sbopkg -B -i %s" % package_name)
    script_manager.run_after(package_name)
    built.add(package_name)


def build_packages(args):
    dep = DependencyManager()
    scripts = ScriptManager()
    built_packages = set()
    if args.packages:
        for pkg_name in args.packages:
            build_package(dep, scripts, pkg_name, built_packages)
    else:
        print()


def main():
    parser = argparse.ArgumentParser(prog='afterpkg')
    parser.add_argument("packages", default=False, nargs="+",
                        help="Package(s) to build")
    args = parser.parse_args()
    build_packages(args)


if __name__ == "__main__":
    main()

