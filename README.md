...because there aren't enough package installers for Slackware :).

```
usage: afterpkg [-h] [-s SLACKBUILDS] [-d] [-n NUMTHREADS] [-c] [-o] [-v] [-2]
                [-3] [-p] [-b] [-a] [-r] [-g] [-q]
                packages [packages ...]

Build and install packages from SBo-current. Afterpkg expects a full install
of -current and the SBo repo to be found at ~/.afterpkg/slackbuilds/. If not
found it will be cloned there. By default most functionality is enabled, the
options described below mostly DISABLE functionality

positional arguments:
  packages              Package(s) to build

optional arguments:
  -h, --help            show this help message and exit
  -s SLACKBUILDS, --slackbuilds SLACKBUILDS
                        Specify the slackbuild directory. The default is
                        ~/.afterpkg/slackbuilds
  -d, --donothing       Don't actually build any packages, just list the steps
                        that would be run
  -n NUMTHREADS, --numthreads NUMTHREADS
                        How many parallel builds to allow (default 1)
  -c, --nocolour        Parallel builds are normally coloured. If you don't
                        like vt100 escape codes in your output, use this
                        option You can still distinguish threads by the output
                        line prefix
  -o, --onlydownload    This will only download the package sources and not
                        build, so you can run the rest of the build offline
  -v, --novirtual       Don't include any pip-installed Python packages in
                        dependency computations (same as -2 and -3)
  -2, --nopip2          Don't include pip2-installed Python packages in
                        dependency computations
  -3, --nopip3          Don't include pip3-installed Python packages in
                        dependency computations
  -p, --pipinstall      By default Python SBo packages will be built and
                        installed as required. This option will pip install
                        them instead. Note that this option makes -o somewhat
                        pointless, as it requires you to be online. You can
                        always pip install everything before you start,
                        however.
  -b, --before          Don't include 'before' scripts
  -a, --after           Don't include 'after' scripts
  -r, --requires        Don't execute 'requires' scripts. These scripts will
                        get executed before executing the builds of dependent
                        packages.
  -g, --getinparallel   Normally downloads will be one-by-one. This will run
                        them in parallel (up to --numthreads)
  -q, --queue           Just print the queue of builds, similar to what sqg
                        would generate. You can use afterpkg to only compute
                        dependencies, generate an sbopkg queue and then run
                        the builds with sbopkg if you prefer.

```



Afterpkg started off life as a POC for running scripts during queue
processing of sbopkg.  I soon realised that sbopkg was not going to give me
what I wanted in terms of package management.  In fact nothing else that I
knew about would.

First, I wanted something written in Python because I can't work with large
programs in shell, it just ties my brain in knots.

Second, I wanted something to do no-nonsense parallel tasking, even where
the build script doesn't accommodate it (make -j XX), it seemed safer to run
the build as the user intended.

Third I wanted some way to execute scripts before or after package building. 
I wanted those scripts to be tied to the packages they relate to, not in
some hand-crafted 'hint' files.  I also wanted to run scripts whenever
something used something else as a dependency.

Finally I wanted to get over the Slackware 'python problem', as I call it. Most
Slackware Python packages just dump data into the rootfs.  This is fine
until pip comes into play where it often wants to update these (often poorly
maintained, often ancient) versions of distutils-installed packages.  It
can't because it can't uninstall what it isn't aware of.  So you decide
instead to pip install the package first, but then SBo will try to clobber
it because it in turn doesn't know about it.  What if the dependency
manager just 'knew' that pip had already installed the package, and then
didn't bother with the SBo version?  Taking that one step further, what
about actually pip-installing the package as part of the build queue?

Of course there are the usual set of options as with any program that does
anything complex, run ./afterpkg --help to list them.

Oh, and there will be bugs.  Loads of them, this is v0.1 :-D.






