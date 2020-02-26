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


    buildgen

    Generate a Slackware build to install a given Python package using pip.
    Note this doesn't generate a .info file but that can easily be added, it's
    not strictly needed, you still need to obtain your 'source' by running
    something like:

    $ pip3 download --no-deps --platform slackware <pypi name>

    Of course slackware won't match any known platform so it will fallback to downloading
    the source (sdist).  This will give you source tarball in cwd.
"""

import argparse
import textwrap
from pathlib import Path
import xmlrpc.client as xmlrpclib


PROGNAME = "sbgen"


do_install_template = """
pip3 install --no-deps --no-index --find-links /opt/afterpkg-python %(package)s
"""

build_template = """#!/bin/sh

# Slackware build script for %(package)s
# Generated code, do not edit.

PRGNAM=%(package)s
VERSION=${VERSION:-%(version)s}
BUILD=${BUILD:-1}
TAG=${TAG:-_SBo}

if [ -z "$ARCH" ]; then
  case "$( uname -m )" in
    i?86) ARCH=i586 ;;
    arm*) ARCH=arm ;;
       *) ARCH=$( uname -m ) ;;
  esac
fi

CWD=$(pwd)
TMP=${TMP:-/tmp/SBo}
PKG=$TMP/package-$PRGNAM
OUTPUT=${OUTPUT:-/tmp}

set -e

rm -rf $PKG
mkdir -p $TMP $PKG $OUTPUT
cd $TMP
rm -rf $PRGNAM-$VERSION
tar xvf $CWD/$PRGNAM-$VERSION.tar.gz
cd $PRGNAM-$VERSION
chown -R root:root .
find -L . \
 \( -perm 777 -o -perm 775 -o -perm 750 -o -perm 711 -o -perm 555 \
  -o -perm 511 \) -exec chmod 755 {} \; -o \
 \( -perm 666 -o -perm 664 -o -perm 640 -o -perm 600 -o -perm 444 \
  -o -perm 440 -o -perm 400 \) -exec chmod 644 {} \;


find $PKG -print0 | xargs -0 file | grep -e "executable" -e "shared object" | grep ELF \
  | cut -f 1 -d : | xargs strip --strip-unneeded 2> /dev/null || true

mkdir -p $PKG/usr/doc/$PRGNAM-$VERSION
cp -a \
   CHANGES LICENSE README  \
  $PKG/usr/doc/$PRGNAM-$VERSION
cat $CWD/$PRGNAM.SlackBuild > $PKG/usr/doc/$PRGNAM-$VERSION/$PRGNAM.SlackBuild

mkdir -p $PKG/install
mkdir -p $PKG/opt/afterpkg-python
cat $CWD/slack-desc > $PKG/install/slack-desc
cat $CWD/doinst.sh > $PKG/install/doinst.sh
cp $CWD/%(source)s > $PKG/opt/afterpkg-python/%(source)s

cd $PKG
/sbin/makepkg -l y -c n $OUTPUT/$PRGNAM-$VERSION-$ARCH-$BUILD$TAG.${PKGTYPE:-tgz}

"""


readme_template = """%(readme)s"""


desc_template = """# HOW TO EDIT THIS FILE:
# The "handy ruler" below makes it easier to edit a package description.
# Line up the first '|' above the ':' following the base package name, and
# the '|' on the right side marks the last column you can put a character in.
# You must make exactly 11 lines for the formatting to be correct.  It's also
# customary to leave one space after the ':' except on otherwise blank lines.

%(pad)s|-----handy-ruler------------------------------------------------------|
%(package)s: %(summary)s
%(package)s:
%(package)s: %(description1)s
%(package)s: %(description2)s
%(package)s: %(description3)s
%(package)s: %(description4)s
%(package)s: %(description5)s
%(package)s: %(description6)s
%(package)s: %(description7)s
%(package)s: %(description8)s
%(package)s: %(description9)s
"""

DESC_LINE_WIDTH = 70


def get_info(package):
    client = xmlrpclib.ServerProxy('https://pypi.python.org/pypi')
    release = client.package_releases(package)[0]

    data = client.release_data(package, release)
    description  = data["description"]

    fields = {
        "summary": data["summary"],
        "package": package,
        "pad": " "*len(package),
        "version": release
    }

    urls = client.release_urls(package, release)
    for url in urls:
        if url["packagetype"] == 'sdist':
            fields["source"] = url["filename"]

    readme = data["summary"] + "\n\n"

    lines = []
    for line in description.split("\n"):
        text = line.strip()
        if not text:
            continue
        if text.startswith(":"):
            continue
        if line.startswith("."):
            continue
        if line.startswith("#"):
            continue
        lines.append(text)
    # Wrap into the available space
    wrapped = textwrap.fill("\n".join(lines), width=DESC_LINE_WIDTH)

    readme += wrapped + "\n"

    # Discard anything after the first 9 lines.
    max_desc = wrapped.split("\n")[:9]
    with_tail = "\n".join(max_desc) + "\n"

    attempts = []
    for sep in [". ", ".)", ".\n"]:
        content, out_sep, tail = with_tail.rpartition(sep)
        attempts.append((len(content), content + out_sep))

    attempts.sort()
    fit_desc = attempts[-1][1].splitlines()

    # Check if it chopped a sentence.
    count = 0
    for line in fit_desc:
        count += 1
        fields["description%d" % count] = line
    while count < 9:
        count += 1
        fields["description%d" % count] = ""

    fields["readme"] = readme
    return fields


def render_template(name, template, fields):
    print("Writing %r" % name)
    Path(name).open("wb").write((template % fields).encode("utf-8"))


def generage_build(package):
    fields = get_info(package)
    render_template("doinst.sh", do_install_template, fields)
    render_template("README", readme_template, fields)
    render_template("slack-desc", desc_template, fields)
    render_template(package + ".SlackBuild", build_template, fields)


def main():
    parser = argparse.ArgumentParser(prog=f'{PROGNAME}',
            description=f"Generate a SlackBuild wrapper for a pypi python package ")
    parser.add_argument("package", default=False,
                        help="pypi name to generate wrapper for")

    args = parser.parse_args()
    generage_build(args.package)


if __name__ == "__main__":
    main()

