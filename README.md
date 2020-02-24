...because there aren't enough package installers for Slackware :).

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