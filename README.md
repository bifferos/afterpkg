...because there aren't enough package installers for Slackware :).

```
usage: afterpkg [-h] [-s SLACKBUILDS] [-d] [-n NUMTHREADS] [-c] [-o] [-v] [-2]                                                                                          
                [-3] [-p] [-b] [-a] [-r] [-g] [-q] [-t HOST]                                                                                                            
                packages [packages ...]                                                                                                                                 

Download, build and install packages from SBo-current. afterpkg expects a full                                                                                          
install of -current and the SBo repo to be found at ~/.afterpkg/slackbuilds/,                                                                                           
if missing the ponce repo will be cloned there. By default most functionality                                                                                           
is enabled, the options described below mostly DISABLE things.                                                                                                          

positional arguments:                                                                                                                                                   
  packages              Package(s) to build. If dash '-' is specified, reads                                                                                            
                        package list from stdin, one-per-line Hash characters                                                                                           
                        '#' will be considered comments and those lines (or                                                                                             
                        ends of lines) will be ignored.                                                                                                                 

optional arguments:                                                                                                                                                     
  -h, --help            show this help message and exit                                                                                                                 
  -s SLACKBUILDS, --slackbuilds SLACKBUILDS                                                                                                                             
                        Specify the slackbuild directory. The default is                                                                                                
                        ~/.afterpkg/slackbuilds. This directory will be cloned                                                                                          
                        from https://github.com/Ponce/slackbuilds.git if not                                                                                            
                        present. This will happen regardless of the -d flag                                                                                             
                        (it's not counted as doing anything). If you want a                                                                                             
                        different repository make sure this exists before
                        running.
  -d, --donothing       Don't actually do anything, just list the steps that
                        would be run. Note that this doesn't disable
                        threading: The steps will be output on different
                        threads, just as any real task would, which means they
                        can be executed in random order. If you don't like
                        this don't use -d with -n
  -n NUMTHREADS, --numthreads NUMTHREADS
                        How many parallel operations to allow (default 1). See
                        also the -g option.
  -c, --nocolour        Parallel builds are normally coloured. If you don't
                        like vt100 escape codes in your output, use this
                        option. You can still distinguish threads by the
                        output line prefix
  -o, --onlydownload    This will only download the package sources and not
                        build, so you can run the build offline
  -v, --novirtual       Don't include any pip-installed Python packages in
                        dependency computations (same as -2 and -3)
  -2, --nopip2          Don't include pip2-installed Python packages in
                        dependency computations
  -3, --nopip3          Don't include pip3-installed Python packages in
                        dependency computations
  -p, --pipinstall      By default Python SBo packages will be built and
                        installed as required. This option will pip install
                        them instead. Note that this makes -o somewhat
                        pointless, as it requires you to be online. You can
                        always pip install everything first, however.
  -b, --before          Don't execute any 'before' scripts. These scripts will
                        get sourced before building the package.
  -a, --after           Don't execute any 'after' scripts. These scripts will
                        get sourced after building the package.
  -r, --requires        Don't execute any 'requires' scripts. These scripts
                        will get sourced before executing the builds of
                        dependent packages.
  -g, --getinparallel   Normally downloads will be one-by-one. This will run
                        them in parallel (up to --numthreads)
  -q, --queue           Just print the queue of builds, similar to what sqg
                        would generate. You can use afterpkg to only compute
                        dependencies, generate an sbopkg queue and then run
                        the builds with sbopkg if you prefer.
  -t HOST, --targethost HOST
                        Specify the remote host to run build commands on. This
                        could be root@host or something defined in your ssh
                        config. You should employ ssh-copy-id or otherwise
                        update ~/.ssh/authorized_hosts on the host to avoid
                        password prompts as afterpkg will not prompt you and
                        just fail without this.
```

Afterpkg is for people who want to automate the the building of lots of 
Slackware packages without fuss.

It allows the maintenance of a tree of before/after/requires scripts that
come into play when building packages.  Since they are shell, and run in the
direct context of the SlackBuild, this allows you to customise pretty
much all aspects of the build.

before/after scripts
====================

before scripts are effectively inserted into the SlackBuild script at the
start.  You can think of them as being copy-pasted into the text as you
would in an editor.  After scripts are added at the end.  These are called
before.sh and after.sh and are, of course optional.  There's no need for any
hash-bangs, although they won't hurt.

requires
========

requires scripts are again inserted at the start of the slack-build but they
are used only for builds that depend on the build in question.  So for
instance if you want to compile runc, and it depends on google-go-lang, then
the google-go-lang requres script (if it existed) would be inserted prior. 
Clearly if you have 10 dependencies, each with a requires script, then the
10 requires scripts will all be added (in order they are declared in the
.info file) to the build. Currently this only happens for immediate
dependencies.

~/.afterpkg/scripts
===================

This location contains your script files.  It should mimick the structure of
SBo, i.e. under scripts comes a category directory, then a package
directory.  So the scripts for tunctl, if it had them would be:

~/.afterpkg/scripts/network/tunctl/before.sh
~/.afterpkg/scripts/network/tunctl/after.sh
~/.afterpkg/scripts/network/tunctl/requires.sh

afterpkg only expects the scripts directory to have been created.  All other
directories are optional.

Python
======

Afterpkg deals with Python dependencies with the concept of virtual
packages.  These virtual packages exist in the dependency tree but never get
installed.  The rationale is that all SBo packages have a pypi equivalent
which can be installed by some other means, and you may wish to do that,
either with pip or from a wheel, egg etc... Of course, this is not always the
case, some SBo python packages aren't in pypi in which case they have to be
installed from SBo anyhow, but at least it helps to avoid SBo packages
blocking upgrade operations from pip.

On the other hand, you may wish to simply install the pypi equivalents as
part of your queued builds which is also possible.  This is of course a
best-guess because some heuristics are required to figure out if a package
is a python extension.  They don't all start with python-.

Parallel Builds
===============

Afterpkg can launch parallel operations and manage them.  It will colourise
the output from different builds so you know what goes with what.  It
attempts to stop all the jobs if there's an error.  Inevitably the parallel
builds will stall when running out of packages with no dependencies so the
makeup of the dependency tree will determine how efficient this is, but you
can also combine with -j XX make options for packages that support it.  You
can do this with the before scripts.

