# -*- coding: utf-8 -*-
#
# Copyright (C) 2005 - 2007, TUBITAK/UEKAE
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# Please read the COPYING file.

import os
import fcntl
import re
import logging
import logging.handlers
import fetcher

import gettext
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

import pisi
import pisi.context as ctx
import pisi.uri
import pisi.util
import pisi.dependency as dependency
import pisi.pgraph as pgraph
import pisi.db.packagedb
import pisi.db.repodb
import pisi.db.filesdb
import pisi.db.installdb
import pisi.db.historydb
import pisi.db.sourcedb
import pisi.db.componentdb
import pisi.index
import pisi.config
import pisi.metadata
import pisi.file
import pisi.blacklist
import pisi.atomicoperations
import pisi.operations.delta
import pisi.operations.remove
import pisi.operations.upgrade
import pisi.operations.install
import pisi.operations.history
import pisi.operations.helper
import pisi.operations.check
import pisi.operations.emerge
import pisi.operations.build
import pisi.errors

def locked(func):
    """
    Decorator for synchronizing privileged functions
    """
    def wrapper(*__args,**__kw):
        try:
            lock = file(pisi.util.join_path(pisi.context.config.lock_dir(), 'pisi'), 'w')
        except IOError:
            raise pisi.errors.PrivilegeError(_("You have to be root for this operation."))

        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            raise pisi.errors.AnotherInstanceError(_("Another instance of PiSi is running. Only one instance is allowed."))

        try:
            return func(*__args,**__kw)
        finally:
            lock.close()
    return wrapper

def set_userinterface(ui):
    """
    Set the user interface where the status information will be send
    @param ui: User interface
    """
    ctx.ui = ui

def set_io_streams(stdout=None, stderr=None):
    """
    Set standart i/o streams
    Used by Buildfarm
    @param stdout: Standart output
    @param stderr: Standart input
    """
    if stdout:
        ctx.stdout = stdout
    if stderr:
        ctx.stderr = stderr

def set_comar(enable):
    """
    Set comar usage
    False means no preremove and postinstall scripts will be run
    @param enable: Flag indicating comar usage
    """
    ctx.comar = enable

def set_comar_destination(destination):
    """
    Set comar bus destination
    @param destination: Path to bus destination of COMAR
    """
    ctx.comar_destination = destination

def set_dbus_sockname(sockname):
    """
    Set dbus socket file
    Used by YALI
    @param sockname: Path to dbus socket file
    """
    ctx.dbus_sockname = sockname

def set_dbus_timeout(timeout):
    """
    Set dbus timeout
    Used by YALI
    @param timeout: Timeout in seconds
    """
    ctx.dbus_timeout = timeout

def set_signal_handling(enable):
    """
    Enable signal handling. Signal handling in pisi mostly used for disabling keyboard interrupts
    in critical paths.
    Used by YALI
    @param enable: Flag indicating signal handling usage
    """
    if enable:
        ctx.sig = pisi.signalhandler.SignalHandler()
    else:
        ctx.sig = None

def set_options(options):
    """
    Set various options of pisi
    @param options: option set

           >>> options = pisi.config.Options()

           options.destdir     # pisi destination directory where operations will take effect
           options.username    # username that for reaching remote repository
           options.password    # password that for reaching remote repository
           options.debug       # flag controlling debug output
           options.verbose     # flag controlling verbosity of the output messages
           options.output_dir  # build and delta operations package output directory
    """
    ctx.config = pisi.config.Config(options)

def list_pending():
    """
    Return a list of configuration pending packages -> list_of_strings
    """
    return pisi.db.installdb.InstallDB().list_pending()

def list_installed():
    """
    Return a list of installed packages -> list_of_strings
    """
    return pisi.db.installdb.InstallDB().list_installed()

def list_obsoleted(repo=None):
    """
    Return a list of obsoleted packages -> list_of_strings
    @param repo: Repository of the obsoleted packages. If repo is None than returns
    a list of all the obsoleted packages in all the repositories
    """
    return pisi.db.packagedb.PackageDB().get_obsoletes(repo)

def list_replaces(repo=None):
    """
    Return a dictionary of the replaced packages in the given repository
    @param repo: Repository of the replaced packages. If repo is None than returns
    a dictionary of all the replaced packages in all the repositories

    {'gaim':'pidgin, 'actioncube':'assaultcube'}

    gaim replaced by pidgin and actioncube replaced by assaultcube
    """
    return pisi.db.packagedb.PackageDB().get_replaces(repo)

def list_available(repo=None):
    """
    Return a list of available packages in the given repository -> list_of_strings
    @param repo: Repository of the packages. If repo is None than returns
    a list of all the available packages in all the repositories
    """
    return pisi.db.packagedb.PackageDB().list_packages(repo)

def list_sources(repo=None):
    """
    Return a list of available source packages in the given repository -> list_of_strings
    @param repo: Repository of the source packages. If repo is None than returns
    a list of all the available source packages in all the repositories
    """
    return pisi.db.sourcedb.SourceDB().list_sources(repo)

def list_newest(repo=None, since=None):
    """
    Return a list of newest packages in the given repository -> list_of_strings since
    last update or before.
    @param repo: Repository of the packages. If repo is None than returns a list of
    all the newest packages from all the repositories.
    @param since: yyyy-mm-dd formatted
    """
    return pisi.db.packagedb.PackageDB().list_newest(repo, since)

def list_upgradable():
    """
    Return a list of packages that are upgraded in the repository -> list_of_strings
    """
    installdb = pisi.db.installdb.InstallDB()
    is_upgradable = lambda pkg: pisi.operations.upgrade.is_upgradable(pkg, ctx.get_option('ignore_build_no'))

    upgradable = filter(is_upgradable, installdb.list_installed())
    # replaced packages can not pass is_upgradable test, so we add them manually
    upgradable.extend(list_replaces())

    # consider also blacklist filtering
    upgradable = pisi.blacklist.exclude_from(upgradable, ctx.const.blacklist)

    return upgradable

def list_repos():
    """
    Return a list of the repositories -> list_of_strings
    """
    return pisi.db.repodb.RepoDB().list_repos()

def get_install_order(packages):
    """
    Return a list of packages in the installation order with extra needed
    dependencies -> list_of_strings
    @param packages: list of package names -> list_of_strings
    """
    install_order = pisi.operations.install.plan_install_pkg_names
    i_graph, order = install_order(packages, ignore_package_conflicts=True)
    return order

def get_remove_order(packages):
    """
    Return a list of packages in the remove order -> list_of_strings
    @param packages: list of package names -> list_of_strings
    """
    remove_order = pisi.operations.remove.plan_remove
    i_graph, order = remove_order(packages)
    return order

def get_upgrade_order(packages):
    """
    Return a list of packages in the upgrade order with extra needed
    dependencies -> list_of_strings
    @param packages: list of package names -> list_of_strings
    """
    upgrade_order = pisi.operations.upgrade.plan_upgrade
    i_graph, order = upgrade_order(packages)
    return order

def get_base_upgrade_order(packages):
    """
    Return a list of packages of the system.base component that needs to be upgraded
    or installed in install order -> list_of_strings
    All the packages of the system.base component must be installed on the system
    @param packages: list of package names -> list_of_strings
    """
    upgrade_order = pisi.operations.upgrade.upgrade_base
    order = upgrade_order(packages, ignore_package_conflicts=True)
    return list(order)

def get_conflicts(packages):
    """
    Return a tuple of the conflicting packages information -> tuple
    @param packages: list of package names -> list_of_strings

    >>> (pkgs, within, pairs) = pisi.api.get_conflicts(packages)
    >>>
    >>> pkgs # list of packages that are installed and conflicts with the
             # given packages list -> list_of_strings
    >>> [...]
    >>> within # list of packages that already conflict with each other
               # in the given packages list -> list_of_strings
    >>> [...]
    >>> pairs # dictionary of conflict information that contains which package in the
              # given packages list conflicts with which of the installed packages

    >>> {'imlib2': <class pisi.conflict.Conflict>, 'valgrind': <class pisi.conflict.Conflict>,
    'libmp4v2':'<class pisi.conflict.Conflict>}

    >>> print map(lambda c:str(pairs[c]), pairs)
    >>> ['imblib', 'callgrind', 'faad2 release >= 3']
    """
    return pisi.conflict.calculate_conflicts(packages, pisi.db.packagedb.PackageDB())

def check(package, config=False):
    """
    Returns a dictionary that contains a list of both corrupted and missing files
    @param package: name of the package to be checked
    @param config: _only_ check the config files of the package, default behaviour is to check all the files
    of the package but the config files
    """
    return pisi.operations.check.check_package(package, config)

def search_package(terms, lang=None, repo=None):
    """
    Return a list of packages that contains all the given terms either in its name, summary or
    description -> list_of_strings
    @param terms: a list of terms used to search package -> list_of_strings
    @param lang: language of the summary and description
    @param repo: Repository of the packages. If repo is None than returns a list of all the packages
    in all the repositories that meets the search
    """
    packagedb = pisi.db.packagedb.PackageDB()
    return packagedb.search_package(terms, lang, repo)

def search_installed(terms, lang=None):
    """
    Return a list of components that contains all the given terms either in its name, summary or
    description -> list_of_strings
    @param terms: a list of terms used to search components -> list_of_strings
    @param lang: language of the summary and description
    """
    installdb = pisi.db.installdb.InstallDB()
    return installdb.search_package(terms, lang)

def search_source(terms, lang=None, repo=None):
    """
    Return a list of source packages that contains all the given terms either in its name, summary or
    description -> list_of_strings
    @param terms: a list of terms used to search source package -> list_of_strings
    @param lang: language of the summary and description
    @param repo: Repository of the source packages. If repo is None than returns a list of all the source
    packages in all the repositories that meets the search
    """
    sourcedb = pisi.db.sourcedb.SourceDB()
    return sourcedb.search_spec(terms, lang, repo)

def search_installed(terms, lang=None):
    """
    Return a list of components that contains all the given terms either in its name, summary or
    description -> list_of_strings
    @param terms: a list of terms used to search components -> list_of_strings
    @param lang: language of the summary and description
    """
    installdb = pisi.db.installdb.InstallDB()
    return installdb.search_package(terms, lang)

def search_component(terms, lang=None, repo=None):
    """
    Return a list of components that contains all the given terms either in its name, summary or
    description -> list_of_strings
    @param terms: a list of terms used to search components -> list_of_strings
    @param lang: language of the summary and description
    @param repo: Repository of the components. If repo is None than returns a list of all the components
    in all the repositories that meets the search
    """
    componentdb = pisi.db.componentdb.ComponentDB()
    return componentdb.search_component(terms, lang, repo)

def search_file(term):
    """
    Returns a tuple of package and matched files list that matches the files of the installed
    packages -> list_of_tuples
    @param term: used to search file -> list_of_strings

    >>> files = pisi.api.search_file("kvm-")

    >>> print files

    >>> [("kvm", (["lib/modules/2.6.18.8-86/extra/kvm-amd.ko","lib/modules/2.6.18.8-86/extra/kvm-intel.ko"])),]
    """
    filesdb = pisi.db.filesdb.FilesDB()
    if term.startswith("/"): # FIXME: why? why?
        term = term[1:]
    return filesdb.search_file(term)

@locked
def install(packages, reinstall=False, ignore_file_conflicts=False, ignore_package_conflicts=False):
    """
    Returns True if no errors occured during the operation
    @param packages: list of package names -> list_of_strings
    @param reinstall: reinstalls already installed packages else ignores
    @param ignore_file_conflicts: Ignores file conflicts during the installation and continues to install
    packages.
    @param ignore_package_conflicts: Ignores package conflicts during the installation and continues to
    install packages.
    """

    pisi.db.historydb.HistoryDB().create_history("install")

    if not ctx.get_option('ignore_file_conflicts'):
        ctx.set_option('ignore_file_conflicts', ignore_file_conflicts)

    if not ctx.get_option('ignore_package_conflicts'):
        ctx.set_option('ignore_package_conflicts', ignore_package_conflicts)

    # Install pisi package files or pisi packages from a repository
    if packages and packages[0].endswith(ctx.const.package_suffix):
        return pisi.operations.install.install_pkg_files(packages)
    else:
        return pisi.operations.install.install_pkg_names(packages, reinstall)

@locked
def takeback(operation):
    """
    Takes back the system to a previous state. Uses pisi history to find out which packages were
    installed at the time _after_ the given operation that the system is requested to be taken back.
    @param operation: number of the operation that the system will be taken back -> integer
    """

    historydb = pisi.db.historydb.HistoryDB()
    historydb.create_history("takeback")

    pisi.operations.history.takeback(operation)

def get_takeback_plan(operation):
    """
    Calculates and returns the plan of the takeback operation that contains information of which
    packages are going to be removed and which packages are going to be installed
    @param operation: number of the operation that the system will be taken back -> integer
    """

    beinstalled, beremoved, configs = pisi.operations.history.plan_takeback(operation)
    return beinstalled, beremoved

@locked
def snapshot():
    """
    Takes snapshot of the system packages. The snapshot is only a record of which packages are currently
    installed. The record is kept by pisi history mechanism as it works automatically on install, remove
    and upgrade operations.
    """

    installdb = pisi.db.installdb.InstallDB()
    historydb = pisi.db.historydb.HistoryDB()
    historydb.create_history("snapshot")

    li = installdb.list_installed()
    progress = ctx.ui.Progress(len(li))

    processed = 0
    for name in installdb.list_installed():
        package = installdb.get_package(name)
        historydb.add_package(pkgBefore=package, operation="snapshot")
        # Save changed config files of the package in snapshot
        for f in installdb.get_files(name).list:
            if f.type == "config" and pisi.util.config_changed(f):
                historydb.save_config(name, "/%s" % f.path)

        processed += 1
        ctx.ui.display_progress(operation = "snapshot",
                                percent = progress.update(processed),
                                info = _("Taking snapshot of the system"))

    historydb.update_history()

# ****** Danger Zone Below! Tressspassers' eyes will explode! ********** #

def package_graph(A, packagedb, ignore_installed = False):
    """Construct a package relations graph.

    Graph will contain all dependencies of packages A, if ignore_installed
    option is True, then only uninstalled deps will be added.

    """

    ctx.ui.debug('A = %s' % str(A))

    # try to construct a pisi graph of packages to
    # install / reinstall

    G_f = pgraph.PGraph(packagedb)             # construct G_f

    # find the "install closure" graph of G_f by package
    # set A using packagedb
    for x in A:
        G_f.add_package(x)
    B = A
    #state = {}
    while len(B) > 0:
        Bp = set()
        for x in B:
            pkg = packagedb.get_package(x)
            #print pkg
            for dep in pkg.runtimeDependencies():
                if ignore_installed:
                    if dependency.installed_satisfies_dep(dep):
                        continue
                if not dep.package in G_f.vertices():
                    Bp.add(str(dep.package))
                G_f.add_dep(x, dep)
        B = Bp
    return G_f

def generate_pending_order(A):
    # returns pending package list in reverse topological order of dependency
    installdb = pisi.db.installdb.InstallDB()
    G_f = pgraph.PGraph(installdb) # construct G_f
    for x in A:
        G_f.add_package(x)
    B = A
    while len(B) > 0:
        Bp = set()
        for x in B:
            pkg = installdb.get_package(x)
            for dep in pkg.runtimeDependencies():
                if dep.package in G_f.vertices():
                    G_f.add_dep(x, dep)
        B = Bp
    if ctx.get_option('debug'):
        import sys
        G_f.write_graphviz(sys.stdout)
    order = G_f.topological_sort()
    order.reverse()

    componentdb = pisi.db.componentdb.ComponentDB()
    # Bug 4211
    if componentdb.has_component('system.base'):
        order = reorder_base_packages(order)

    return order

@locked
def configure_pending(packages=None):
    # Import COMAR
    import pisi.comariface

    # start with pending packages
    # configure them in reverse topological order of dependency
    installdb = pisi.db.installdb.InstallDB()
    if not packages:
        packages = installdb.list_pending()
    else:
        packages = set(packages).intersection(installdb.list_pending())

    order = generate_pending_order(packages)
    try:
        for x in order:
            if installdb.has_package(x):
                pkginfo = installdb.get_package(x)
                pkgname = pisi.util.package_name(x, pkginfo.version,
                                        pkginfo.release,
                                        False,
                                        False)
                pkg_path = pisi.util.join_path(ctx.config.packages_dir(), pkgname)
                m = pisi.metadata.MetaData()
                metadata_path = pisi.util.join_path(pkg_path, ctx.const.metadata_xml)
                m.read(metadata_path)
                # FIXME: we need a full package info here!
                pkginfo.name = x
                ctx.ui.notify(pisi.ui.configuring, package = pkginfo, files = None)
                pisi.comariface.post_install(
                    pkginfo.name,
                    m.package.providesComar,
                    pisi.util.join_path(pkg_path, ctx.const.comar_dir),
                    pisi.util.join_path(pkg_path, ctx.const.metadata_xml),
                    pisi.util.join_path(pkg_path, ctx.const.files_xml),
                    None,
                    None,
                    m.package.version,
                    m.package.release
                )
                ctx.ui.notify(pisi.ui.configured, package = pkginfo, files = None)
            installdb.clear_pending(x)
    except ImportError:
        raise pisi.Error(_("comar package is not fully installed"))

def info(package, installed = False):
    if package.endswith(ctx.const.package_suffix):
        return info_file(package)
    else:
        metadata, files, repo = info_name(package, installed)
        return metadata, files

def info_file(package_fn):

    if not os.path.exists(package_fn):
        raise pisi.Error (_('File %s not found') % package_fn)

    package = pisi.package.Package(package_fn)
    package.read()
    return package.metadata, package.files

def info_name(package_name, useinstalldb=False):
    """Fetch package information for the given package."""

    installdb = pisi.db.installdb.InstallDB()
    packagedb = pisi.db.packagedb.PackageDB()
    if useinstalldb:
        package = installdb.get_package(package_name)
        repo = None
    else:
        package, repo = packagedb.get_package_repo(package_name)

    metadata = pisi.metadata.MetaData()
    metadata.package = package
    #FIXME: get it from sourcedb if available
    metadata.source = None
    #TODO: fetch the files from server if possible (wow, you maniac -- future exa)
    if useinstalldb and installdb.has_package(package.name):
        try:
            files = installdb.get_files(package.name)
        except pisi.Error, e:
            ctx.ui.warning(e)
            files = None
    else:
        files = None
    return metadata, files, repo

def index(dirs=None, output='pisi-index.xml', skip_sources=False, skip_signing=False):
    """Accumulate PiSi XML files in a directory, and write an index."""
    index = pisi.index.Index()
    index.distribution = None
    if not dirs:
        dirs = ['.']
    for repo_dir in dirs:
        repo_dir = str(repo_dir)
        ctx.ui.info(_('* Building index of PiSi files under %s') % repo_dir)
        index.index(repo_dir, skip_sources)

    if skip_signing:
        index.write(output, sha1sum=True, compress=pisi.file.File.bz2, sign=None)
    else:
        index.write(output, sha1sum=True, compress=pisi.file.File.bz2, sign=pisi.file.File.detached)
    ctx.ui.info(_('* Index file written'))

@locked
def add_repo(name, indexuri, at = None):
    if not re.match("^[0-9%s\-\\_\\.\s]*$" % str(pisi.util.letters()), name):
        raise pisi.Error(_('Not a valid repo name.'))
    repodb = pisi.db.repodb.RepoDB()
    if repodb.has_repo(name):
        raise pisi.Error(_('Repo %s already present.') % name)
    elif repodb.has_repo_url(indexuri):
        repo = repodb.get_repo_by_url(indexuri)
        raise pisi.Error(_('Repo already present with name %s.') % repo)
    else:
        repo = pisi.db.repodb.Repo(pisi.uri.URI(indexuri))
        repodb.add_repo(name, repo, at = at)
        ctx.ui.info(_('Repo %s added to system.') % name)

@locked
def remove_repo(name):
    repodb = pisi.db.repodb.RepoDB()
    if repodb.has_repo(name):
        repodb.remove_repo(name)
        ctx.ui.info(_('Repo %s removed from system.') % name)
    else:
        raise pisi.Error(_('Repository %s does not exist. Cannot remove.')
                 % name)

@locked
def update_repos(repos, force=False):
    pisi.db.historydb.HistoryDB().create_history("repoupdate")
    for repo in repos:
        __update_repo(repo, force)

@locked
def update_repo(repo, force=False):
    pisi.db.historydb.HistoryDB().create_history("repoupdate")
    __update_repo(repo, force)

def __update_repo(repo, force=False):
    ctx.ui.info(_('* Updating repository: %s') % repo)
    ctx.ui.notify(pisi.ui.updatingrepo, name = repo)
    repodb = pisi.db.repodb.RepoDB()
    index = pisi.index.Index()
    if repodb.has_repo(repo):
        repouri = repodb.get_repo(repo).indexuri.get_uri()
        try:
            index.read_uri_of_repo(repouri, repo)
            pisi.db.historydb.HistoryDB().update_repo(repo, repouri, "update")
        except pisi.file.AlreadyHaveException, e:
            ctx.ui.info(_('%s repository information is up-to-date.') % repo)
            if force:
                ctx.ui.info(_('Updating database at any rate as requested'))
                index.read_uri_of_repo(repouri, repo, force = force)
            else:
                return

        try:
            index.check_signature(repouri, repo)
        except pisi.file.NoSignatureFound, e:
            ctx.ui.warning(e)

        ctx.ui.info(_('* Package database updated.'))
    else:
        raise pisi.Error(_('No repository named %s found.') % repo)

def fetch(packages=[], path=os.path.curdir):
    """
    Fetches the given packages from the repository without installing, just downloads the packages.
    @param packages: list of package names -> list_of_strings
    @param path: path to where the packages will be downloaded. If not given, packages will be downloaded
    to the current working directory.
    """
    packagedb = pisi.db.packagedb.PackageDB()
    repodb = pisi.db.repodb.RepoDB()
    for name in packages:
        package, repo = packagedb.get_package_repo(name)
        ctx.ui.info(_("%s package found in %s repository") % (package.name, repo))
        uri = pisi.uri.URI(package.packageURI)
        if uri.is_absolute_path():
            url = str(pkg_uri)
        else:
            url = os.path.join(os.path.dirname(repodb.get_repo_url(repo)), str(uri.path()))

        fetcher.fetch_url(url, path, ctx.ui.Progress)

@locked
def delete_cache():
    pisi.util.clean_dir(ctx.config.cached_packages_dir())
    pisi.util.clean_dir(ctx.config.archives_dir())
    pisi.util.clean_dir(ctx.config.tmp_dir())

# FIXME: rebuild_db is only here for filesdb and it really is ugly. we should not need any rebuild.
@locked
def rebuild_db(files=False):

    filesdb = pisi.db.filesdb.FilesDB()
    installdb = pisi.db.installdb.InstallDB()

    def rebuild_filesdb():
        for pkg in list_installed():
            ctx.ui.info(_('* Adding \'%s\' to db... ') % pkg, noln=True)
            files = installdb.get_files(pkg)
            filesdb.add_files(pkg, files)
            ctx.ui.info(_('OK.'))

    # save parameters and shutdown pisi
    options = ctx.config.options
    ui = ctx.ui
    comar = ctx.comar
    pisi._cleanup()

    filesdb.close()
    filesdb.destroy()
    filesdb.init()

    # reinitialize everything
    set_userinterface(ui)
    set_options(options)
    set_comar(comar)

    # construct new database
    rebuild_filesdb()

############# FIXME: this was a quick fix. ##############################

# api was importing other module's functions and providing them as api functions. This is wrong.
# these are quick fixes for this problem. The api functions should be in this module.

# from pisi.operations import install, remove, upgrade, emerge
# from pisi.operations import plan_install_pkg_names as plan_install
# from pisi.operations import plan_remove, plan_upgrade, upgrade_base, calculate_conflicts, reorder_base_packages
# from pisi.build import build_until
# from pisi.atomicoperations import resurrect_package, build

@locked
def remove(*args, **kw):
    pisi.db.historydb.HistoryDB().create_history("remove")
    return pisi.operations.remove.remove(*args, **kw)

@locked
def upgrade(*args, **kw):
    pisi.db.historydb.HistoryDB().create_history("upgrade")
    return pisi.operations.upgrade.upgrade(*args, **kw)

@locked
def emerge(*args, **kw):
    pisi.db.historydb.HistoryDB().create_history("emerge")
    return pisi.operations.emerge.emerge(*args, **kw)

def calculate_conflicts(*args, **kw):
    return pisi.conflict.calculate_conflicts(*args, **kw)

def reorder_base_packages(*args, **kw):
    return pisi.operations.helper.reorder_base_packages(*args, **kw)

def build_until(*args, **kw):
    return pisi.operations.build.build_until(*args, **kw)

def build(*args, **kw):
    return pisi.atomicoperations.build(*args, **kw)

########################################################################

## Deletes the cached pisi packages to keep the package cache dir within cache limits
#  @param all When set all the cached packages will be deleted
@locked
def clearCache(all=False):

    import glob
    from sets import Set as set

    def getPackageLists(pkgList):
        latest = {}
        for f in pkgList:
            try:
                name, version = util.parse_package_name(f)
                if latest.has_key(name):
                    if Version(latest[name]) < Version(version):
                        latest[name] = version
                else:
                    if version:
                        latest[name] = version
            except:
                pass

        latestVersions = []
        for pkg in latest:
            latestVersions.append("%s-%s" % (pkg, latest[pkg]))

        oldVersions = list(set(pkgList) - set(latestVersions))
        return oldVersions, latestVersions

    def getRemoveOrder(cacheDir, pkgList):
        sizes = {}
        for pkg in pkgList:
            sizes[pkg] = os.stat(os.path.join(cacheDir, pkg) + ".pisi").st_size

        # sort dictionary by value from PEP-265
        from operator import itemgetter
        return sorted(sizes.iteritems(), key=itemgetter(1), reverse=False)

    def removeOrderByLimit(cacheDir, order, limit):
        totalSize = 0
        for pkg, size in order:
            totalSize += size
            if totalSize >= limit:
                try:
                    os.remove(os.path.join(cacheDir, pkg) + ".pisi")
                except exceptions.OSError:
                    pass

    def removeAll(cacheDir):
        cached = glob.glob("%s/*.pisi" % cacheDir) + glob.glob("%s/*.part" % cacheDir)
        for pkg in cached:
            try:
                os.remove(pkg)
            except exceptions.OSError:
                pass

    cacheDir = ctx.config.cached_packages_dir()

    pkgList = map(lambda x: os.path.basename(x).split(".pisi")[0], glob.glob("%s/*.pisi" % cacheDir))
    if not all:
        # Cache limits from pisi.conf
        config = pisi.configfile.ConfigurationFile("/etc/pisi/pisi.conf")
        cacheLimit = int(config.get("general", "package_cache_limit")) * 1024 * 1024 # is this safe?
        if not cacheLimit:
            return

        old, latest = getPackageLists(pkgList)
        order = getRemoveOrder(cacheDir, latest) + getRemoveOrder(cacheDir, old)
        removeOrderByLimit(cacheDir, order, cacheLimit)
    else:
        removeAll(cacheDir)
