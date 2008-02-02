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
#

import os
import sys

import gettext
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

import pisi
import pisi.package
import pisi.context as ctx
import pisi.util as util
import pisi.dependency as dependency
import pisi.conflict
import pisi.pgraph as pgraph
import pisi.repodb
import pisi.installdb
import pisi.cli
import pisi.atomicoperations as atomicoperations
import pisi.ui as ui

class Error(pisi.Error):
    pass

def upgrade_pisi():
    """forces to reload pisi modules and runs rebuild-db if needed."""
    import pisi
    import pisi.context as ctx
    import pisi.version

    old_filesdbversion = pisi.__filesdbversion__
    old_dbversion = pisi.__dbversion__
    # we have to keep old_ui or by calling raw init, we lose it
    old_ui = ctx.ui

    def rebuild_db():
        """rebuild_db is necessary if database structures has changed."""
        if pisi.version.Version(pisi.__filesdbversion__) > pisi.version.Version(old_filesdbversion) or \
           pisi.version.Version(pisi.__dbversion__) > pisi.version.Version(old_dbversion):

            pisi.api.init(database=False, ui=old_ui)
            #FIXME: we can not use _( ) here or NoneType object is not callable error is seen from package-manager
            ctx.ui.info("* PiSi database version has changed. Rebuilding database...")
            pisi.api.rebuild_db(files=True)
            ctx.ui.info("* Database rebuild operation is completed succesfully.")
            pisi.api.finalize()

    def reload_pisi():
        for module in sys.modules.keys():
            if not module.startswith("pisi.ui") and not module.startswith("pisi.cli") and module.startswith("pisi."):
                """removal from sys.modules forces reload via import"""
                del(sys.modules[module])

    pisi.api.finalize()
    reload_pisi()
    reload(pisi)
    rebuild_db()
    pisi.api.init(ui=old_ui)

# high level operations

def install(packages, reinstall = False, ignore_file_conflicts=False):
    """install a list of packages (either files/urls, or names)"""

    if not ctx.get_option('ignore_file_conflicts'):
        ctx.set_option('ignore_file_conflicts', ignore_file_conflicts)

    # determine if this is a list of files/urls or names
    if packages and packages[0].endswith(ctx.const.package_suffix): # they all have to!
        return install_pkg_files(packages)
    else:
        return install_pkg_names(packages, reinstall)

def reorder_base_packages(order):
    """system.base packages must be first in order"""
    systembase = ctx.componentdb.get_union_comp('system.base').packages

    systembase_order = []
    nonbase_order = []
    for pkg in order:
        if pkg in systembase:
            systembase_order.append(pkg)
        else:
            nonbase_order.append(pkg)

    return systembase_order + nonbase_order

def install_pkg_files(package_URIs):
    """install a number of pisi package files"""

    ctx.ui.debug('A = %s' % str(package_URIs))

    for x in package_URIs:
        if not x.endswith(ctx.const.package_suffix):
            raise Error(_('Mixing file names and package names not supported yet.'))

    if ctx.config.get_option('ignore_dependency'):
        # simple code path then
        for x in package_URIs:
            atomicoperations.install_single_file(x)
        return # short circuit

    # read the package information into memory first
    # regardless of which distribution they come from
    d_t = {}
    dfn = {}
    for x in package_URIs:
        package = pisi.package.Package(x)
        package.read()
        name = str(package.metadata.package.name)
        d_t[name] = package.metadata.package
        dfn[name] = x

    def satisfiesDep(dep):
        # is dependency satisfied among available packages
        # or packages to be installed?
        return dependency.installed_satisfies_dep(dep) \
               or dependency.dict_satisfies_dep(d_t, dep)

    # for this case, we have to determine the dependencies
    # that aren't already satisfied and try to install them
    # from the repository
    dep_unsatis = []
    for name in d_t.keys():
        pkg = d_t[name]
        deps = pkg.runtimeDependencies()
        for dep in deps:
            if not satisfiesDep(dep):
                dep_unsatis.append(dep)

    # now determine if these unsatisfied dependencies could
    # be satisfied by installing packages from the repo

    # if so, then invoke install_pkg_names
    extra_packages = [x.package for x in dep_unsatis]
    if extra_packages:
        ctx.ui.info(_("""The following packages will be installed
in the respective order to satisfy extra dependencies:
""") + util.strlist(extra_packages))
        if not ctx.ui.confirm(_('Do you want to continue?')):
            raise Error(_('External dependencies not satisfied'))
        install_pkg_names(extra_packages)

    class PackageDB:
        def get_package(self, key, repo = None):
            return d_t[str(key)]

    packagedb = PackageDB()

    A = d_t.keys()

    if len(A)==0:
        ctx.ui.info(_('No packages to install.'))
        return

    # try to construct a pisi graph of packages to
    # install / reinstall

    G_f = pgraph.PGraph(packagedb)               # construct G_f

    # find the "install closure" graph of G_f by package
    # set A using packagedb
    for x in A:
        G_f.add_package(x)
    B = A
    while len(B) > 0:
        Bp = set()
        for x in B:
            pkg = packagedb.get_package(x)
            for dep in pkg.runtimeDependencies():
                if dependency.dict_satisfies_dep(d_t, dep):
                    if not dep.package in G_f.vertices():
                        Bp.add(str(dep.package))
                    G_f.add_dep(x, dep)
        B = Bp
    if ctx.config.get_option('debug'):
        G_f.write_graphviz(sys.stdout)
    order = G_f.topological_sort()
    if not ctx.get_option('ignore_package_conflicts'):
        conflicts = check_conflicts(order, packagedb)
        if conflicts:
            remove_conflicting_packages(conflicts)
    order.reverse()
    ctx.ui.info(_('Installation order: ') + util.strlist(order) )

    if ctx.get_option('dry_run'):
        return

    ctx.ui.notify(ui.packagestogo, order = order)

    for x in order:
        atomicoperations.install_single_file(dfn[x])

    pisi_installed = ctx.installdb.is_installed('pisi')

    if 'pisi' in order and pisi_installed:
        upgrade_pisi()

# FIXME: this should be done in atomicoperations automatically.
def remove_replaced_packages(order, replaces):

    replaced = []
    inorder = set(order).intersection(replaces.values())

    if inorder:
        for pkg in replaces.keys():
            if replaces[pkg] in inorder:
                replaced.append(pkg)

    if replaced:
        if remove(replaced, ignore_dep=True, ignore_safety=True):
            raise Error(_("Replaced package remains"))

def remove_conflicting_packages(conflicts):
    if remove(conflicts, ignore_dep=True, ignore_safety=True):
        raise Error(_("Conflicts remain"))

def remove_obsoleted_packages():
    obsoletes = filter(ctx.installdb.is_installed, ctx.packagedb.get_obsoletes())
    if obsoletes:
        if remove(obsoletes, ignore_dep=True, ignore_safety=True):
            raise Error(_("Obsoleted packages remaining"))

def check_conflicts(order, packagedb):
    """check if upgrading to the latest versions will cause havoc
    done in a simple minded way without regard for dependencies of
    conflicts, etc."""

    (C, D, pkg_conflicts) = pisi.conflict.calculate_conflicts(order, packagedb)

    if D:
        raise Error(_("Selected packages [%s] are in conflict with each other.") %
                    util.strlist(list(D)))

    if pkg_conflicts:
        conflicts = ""
        for pkg in pkg_conflicts.keys():
            conflicts += _("[%s conflicts with: %s]\n") % (pkg, util.strlist(pkg_conflicts[pkg]))

        ctx.ui.info(_("The following packages have conflicts:\n%s") %
                    conflicts)

        if not ctx.ui.confirm(_('Remove the following conflicting packages?')):
            raise Error(_("Conflicts remain"))

    return list(C)

def is_upgradable(name, ignore_build = False):
    if not ctx.installdb.is_installed(name):
        return False
    (version, release, build) = ctx.installdb.get_version(name)
    try:
        pkg = ctx.packagedb.get_package(name)
    except KeyboardInterrupt:
        raise
    except Exception, e: #FIXME: what exception could we catch here, replace with that.
        return False

    if ignore_build or (not build) or (not pkg.build):
        return pisi.version.Version(release) < pisi.version.Version(pkg.release)
    else:
        return build < pkg.build

def upgrade_base(A = set(), ignore_package_conflicts = False):
    ignore_build = ctx.get_option('ignore_build_no')
    if not ctx.get_option('ignore_safety'):
        if ctx.componentdb.has_component('system.base'):
            systembase = set(ctx.componentdb.get_union_comp('system.base').packages)
            extra_installs = filter(lambda x: not ctx.installdb.is_installed(x), systembase - set(A))
            if extra_installs:
                ctx.ui.warning(_('Safety switch: Following packages in system.base will be installed: ') +
                               util.strlist(extra_installs))
            G_f, install_order = plan_install_pkg_names(extra_installs, ignore_package_conflicts)
            extra_upgrades = filter(lambda x: is_upgradable(x, ignore_build), systembase - set(install_order))
            upgrade_order = []
            if extra_upgrades:
                ctx.ui.warning(_('Safety switch: Following packages in system.base will be upgraded: ') +
                               util.strlist(extra_upgrades))
                G_f, upgrade_order = plan_upgrade(extra_upgrades)
            # return packages that must be added to any installation
            return set(install_order + upgrade_order)
        else:
            ctx.ui.warning(_('Safety switch: the component system.base cannot be found'))
    return set()

def install_pkg_names(A, reinstall = False):
    """This is the real thing. It installs packages from
    the repository, trying to perform a minimum number of
    installs"""

    A = [str(x) for x in A] #FIXME: why do we still get unicode input here? :/ -- exa
    # A was a list, remove duplicates
    A_0 = A = set(A)

    # filter packages that are already installed
    if not reinstall:
        Ap = set(filter(lambda x: not ctx.installdb.is_installed(x), A))
        d = A - Ap
        if len(d) > 0:
            ctx.ui.warning(_("The following package(s) are already installed and are not going to be installed again:\n") +
                             util.strlist(d))
            A = Ap

    if len(A)==0:
        ctx.ui.info(_('No packages to install.'))
        return

    A |= upgrade_base(A)

    if not ctx.config.get_option('ignore_dependency'):
        G_f, order = plan_install_pkg_names(A)
    else:
        G_f = None
        order = list(A)

    # Bug 4211
    if ctx.componentdb.has_component('system.base'):
        order = reorder_base_packages(order)

    if len(order) > 1:
        ctx.ui.info(_("Following packages will be installed in the respective "
                      "order to satisfy dependencies:\n") + util.strlist(order))

    total_size, cached_size = calculate_download_sizes(order)
    total_size, symbol = util.human_readable_size(total_size)
    ctx.ui.info(_('Total size of package(s): %.2f %s') % (total_size, symbol))

    if ctx.get_option('dry_run'):
        return

    if set(order) - A_0:
        if not ctx.ui.confirm(_('There are extra packages due to dependencies. Do you want to continue?')):
            return False

    ctx.ui.notify(ui.packagestogo, order = order)

    pisi_installed = ctx.installdb.is_installed('pisi')

    for x in order:
        atomicoperations.install_single_name(x, True)  # allow reinstalls here

    if 'pisi' in order and pisi_installed:
        upgrade_pisi()

def plan_install_pkg_names(A, ignore_package_conflicts = False):
    # try to construct a pisi graph of packages to
    # install / reinstall

    G_f = pgraph.PGraph(ctx.packagedb)               # construct G_f

    # find the "install closure" graph of G_f by package
    # set A using packagedb
    for x in A:
        G_f.add_package(x)
    B = A

    while len(B) > 0:
        Bp = set()
        for x in B:
            pkg = ctx.packagedb.get_package(x)
            for dep in pkg.runtimeDependencies():
                ctx.ui.debug('checking %s' % str(dep))
                # we don't deal with already *satisfied* dependencies
                if not dependency.installed_satisfies_dep(dep):
                    if not dep.package in G_f.vertices():
                        Bp.add(str(dep.package))
                    G_f.add_dep(x, dep)
        B = Bp
    if ctx.config.get_option('debug'):
        G_f.write_graphviz(sys.stdout)
    order = G_f.topological_sort()
    order.reverse()
    if not ctx.get_option('ignore_package_conflicts') and not ignore_package_conflicts:
        conflicts = check_conflicts(order, ctx.packagedb)
        if conflicts:
            remove_conflicting_packages(conflicts)
    return G_f, order

def upgrade(A):
    upgrade_pkg_names(A)

def upgrade_pkg_names(A = []):
    """Re-installs packages from the repository, trying to perform
    a minimum or maximum number of upgrades according to options."""

    ignore_build = ctx.get_option('ignore_build_no')
    security_only = ctx.get_option('security_only')

    replaced = []
    replaces = ctx.packagedb.get_replaces()

    if not A:
        # if A is empty, then upgrade all packages
        A = ctx.installdb.list_installed()

    A_0 = A = set(A)

    Ap = []
    for x in A:
        if x.endswith(ctx.const.package_suffix):
            ctx.ui.debug(_("Warning: package *name* ends with '.pisi'"))

        # Handling of replacement packages
        if x in replaces.values():
            Ap.append(x)
            continue

        if x in replaces.keys():
            Ap.append(replaces[x])
            continue

        if not ctx.installdb.is_installed(x):
            ctx.ui.info(_('Package %s is not installed.') % x, True)
            continue
        (version, release, build) = ctx.installdb.get_version(x)
        if ctx.packagedb.has_package(x):
            pkg = ctx.packagedb.get_package(x)
        else:
            ctx.ui.info(_('Package %s is not available in repositories.') % x, True)
            continue

        if security_only:
            updates = [i for i in pkg.history if pisi.version.Version(i.release) > pisi.version.Version(release)]
            if not pisi.util.any(lambda i:i.type == 'security', updates):
                continue

        if ignore_build or (not build) or (not pkg.build):
            if pisi.version.Version(release) < pisi.version.Version(pkg.release):
                Ap.append(x)
            else:
                ctx.ui.info(_('Package %s is already at the latest release %s.')
                            % (pkg.name, pkg.release), True)
        else:
            if build < pkg.build:
                Ap.append(x)
            else:
                ctx.ui.info(_('Package %s is already at the latest build %s.')
                            % (pkg.name, pkg.build), True)


    A = set(Ap)

    if len(A)==0:
        ctx.ui.info(_('No packages to upgrade.'))
        return True

    A |= upgrade_base(A)

    ctx.ui.debug('A = %s' % str(A))

    if not ctx.config.get_option('ignore_dependency'):
        G_f, order = plan_upgrade(A)
    else:
        G_f = None
        order = list(A)

    # Bug 4211
    if ctx.componentdb.has_component('system.base'):
        order = reorder_base_packages(order)

    if not ctx.get_option('ignore_package_conflicts'):
        conflicts = check_conflicts(order, ctx.packagedb)

    ctx.ui.info(_('The following packages will be upgraded: ') +
                util.strlist(order))

    total_size, cached_size = calculate_download_sizes(order)
    total_size, symbol = util.human_readable_size(total_size)
    ctx.ui.info(_('Total size of package(s): %.2f %s') % (total_size, symbol))

    if ctx.get_option('dry_run'):
        return

    if set(order) - A_0 - set(replaces.values()):
        if not ctx.ui.confirm(_('There are extra packages due to dependencies. Do you want to continue?')):
            return False

    ctx.ui.notify(ui.packagestogo, order = order)

    paths = []
    for x in order:
        ctx.ui.info(util.colorize(_("Downloading %d / %d") % (order.index(x)+1, len(order)), "yellow"))
        install_op = atomicoperations.Install.from_name(x)
        paths.append(install_op.package_fname)

    # fetch to be upgraded packages but do not install them.
    if ctx.get_option('fetch_only'):
        return

    if not ctx.get_option('ignore_package_conflicts'):
        if conflicts:
            remove_conflicting_packages(conflicts)

    if replaces:
        remove_replaced_packages(order, replaces)

    remove_obsoleted_packages()

    for path in paths:
        ctx.ui.info(util.colorize(_("Installing %d / %d") % (paths.index(path)+1, len(paths)), "yellow"))
        install_op = atomicoperations.Install(path, ignore_file_conflicts = True)
        install_op.install(True)

    if 'pisi' in order:
        upgrade_pisi()

def plan_upgrade(A):
    # try to construct a pisi graph of packages to
    # install / reinstall

    packagedb = ctx.packagedb

    G_f = pgraph.PGraph(packagedb)               # construct G_f

    # find the "install closure" graph of G_f by package
    # set A using packagedb
    for x in A:
        G_f.add_package(x)
    B = A

    # TODO: conflicts

    while len(B) > 0:
        Bp = set()
        for x in B:
            pkg = packagedb.get_package(x)
            for dep in pkg.runtimeDependencies():
                # add packages that can be upgraded
                if ctx.installdb.is_installed(dep.package) and dependency.installed_satisfies_dep(dep):
                    continue

                if dependency.repo_satisfies_dep(dep):
                    if not dep.package in G_f.vertices():
                        Bp.add(str(dep.package))
                    G_f.add_dep(x, dep)
                else:
                    ctx.ui.error(_('Dependency %s of %s cannot be satisfied') % (dep, x))
                    raise Error(_("Upgrade is not possible."))

        B = Bp
    # now, search reverse dependencies to see if anything
    # should be upgraded
    B = A
    while len(B) > 0:
        Bp = set()
        for x in B:
            pkg = packagedb.get_package(x)
            rev_deps = packagedb.get_rev_deps(x)
            for (rev_dep, depinfo) in rev_deps:
                # add only installed but unsatisfied reverse dependencies
                if ctx.installdb.is_installed(rev_dep) and \
                        (not dependency.installed_satisfies_dep(depinfo)):
                    if not dependency.repo_satisfies_dep(depinfo):
                        raise Error(_('Reverse dependency %s of %s cannot be satisfied') % (rev_dep, x))
                    if not rev_dep in G_f.vertices():
                        Bp.add(rev_dep)
                        G_f.add_plain_dep(rev_dep, x)
        B = Bp

    if ctx.config.get_option('debug'):
        G_f.write_graphviz(sys.stdout)
    order = G_f.topological_sort()
    order.reverse()
    return G_f, order

def remove(A, ignore_dep = False, ignore_safety = False):
    """remove set A of packages from system (A is a list of package names)"""

    A = [str(x) for x in A]

    # filter packages that are not installed
    A_0 = A = set(A)

    if not ctx.get_option('ignore_safety') and not ignore_safety:
        if ctx.componentdb.has_component('system.base'):
            systembase = set(ctx.componentdb.get_union_comp('system.base').packages)
            refused = A.intersection(systembase)
            if refused:
                ctx.ui.warning(_('Safety switch: cannot remove the following packages in system.base: ') +
                               util.strlist(refused))
                A = A - systembase
        else:
            ctx.ui.warning(_('Safety switch: the component system.base cannot be found'))

    Ap = []
    for x in A:
        if ctx.installdb.is_installed(x):
            Ap.append(x)
        else:
            ctx.ui.info(_('Package %s does not exist. Cannot remove.') % x)
    A = set(Ap)

    if len(A)==0:
        ctx.ui.info(_('No packages to remove.'))
        return False

    if not ctx.config.get_option('ignore_dependency') and not ignore_dep:
        G_f, order = plan_remove(A)
    else:
        G_f = None
        order = A

    ctx.ui.info(_("""The following minimal list of packages will be removed
in the respective order to satisfy dependencies:
""") + util.strlist(order))
    if len(order) > len(A_0):
        if not ctx.ui.confirm(_('Do you want to continue?')):
            ctx.ui.warning(_('Package removal declined'))
            return False

    if ctx.get_option('dry_run'):
        return

    ctx.ui.notify(ui.packagestogo, order = order)

    for x in order:
        if ctx.installdb.is_installed(x):
            atomicoperations.remove_single(x)
        else:
            ctx.ui.info(_('Package %s is not installed. Cannot remove.') % x)

def plan_remove(A):
    # try to construct a pisi graph of packages to
    # install / reinstall

    G_f = pgraph.PGraph(ctx.packagedb, pisi.itembyrepodb.installed)               # construct G_f

    # find the (install closure) graph of G_f by package
    # set A using packagedb
    for x in A:
        G_f.add_package(x)
    B = A
    while len(B) > 0:
        Bp = set()
        for x in B:
            rev_deps = ctx.packagedb.get_rev_deps(x, pisi.itembyrepodb.installed)
            for (rev_dep, depinfo) in rev_deps:
                # we don't deal with uninstalled rev deps
                # and unsatisfied dependencies (this is important, too)
                if ctx.packagedb.has_package(rev_dep, pisi.itembyrepodb.installed) and \
                   dependency.installed_satisfies_dep(depinfo):
                    if not rev_dep in G_f.vertices():
                        Bp.add(rev_dep)
                        G_f.add_plain_dep(rev_dep, x)
        B = Bp
    if ctx.config.get_option('debug'):
        G_f.write_graphviz(sys.stdout)
    order = G_f.topological_sort()
    return G_f, order

def expand_src_components(A):
    Ap = set()
    for x in A:
        if ctx.componentdb.has_component(x):
            Ap = Ap.union(ctx.componentdb.get_union_comp(x).sources)
        else:
            Ap.add(x)
    return Ap

def emerge(A):

    # A was a list, remove duplicates and expand components
    A = [str(x) for x in A]
    A_0 = A = expand_src_components(set(A))
    ctx.ui.debug('A = %s' % str(A))

    if len(A)==0:
        ctx.ui.info(_('No packages to emerge.'))
        return

    #A |= upgrade_base(A)

    # FIXME: Errr... order_build changes type conditionally and this
    # is not good. - baris
    if not ctx.config.get_option('ignore_dependency'):
        G_f, order_inst, order_build = plan_emerge(A)
    else:
        G_f = None
        order_inst = []
        order_build = A

    if order_inst:
        ctx.ui.info(_("""The following minimal list of packages will be installed
from repository in the respective order to satisfy dependencies:
""") + util.strlist(order_inst))
    ctx.ui.info(_("""The following minimal list of packages will be built and
installed in the respective order to satisfy dependencies:
""") + util.strlist(order_build))

    if ctx.get_option('dry_run'):
        return

    if len(order_inst) + len(order_build) > len(A_0):
        if not ctx.ui.confirm(_('There are extra packages due to dependencies. Do you want to continue?')):
            return False

    ctx.ui.notify(ui.packagestogo, order = order_inst)

    pisi_installed = ctx.installdb.is_installed('pisi')

    for x in order_inst:
        atomicoperations.install_single_name(x)

    #ctx.ui.notify(ui.packagestogo, order = order_build)

    for x in order_build:
        package_names = atomicoperations.build(x)[0]
        install_pkg_files(package_names) # handle inter-package deps here

    # FIXME: take a look at the fixme above :(, we have to be sure
    # that order_build is a known type...
    U = set(order_build)
    U.update(order_inst)
    if 'pisi' in order_build or (('pisi' in U) and pisi_installed):
        upgrade_pisi()

def plan_emerge(A):

    # try to construct a pisi graph of packages to
    # install / reinstall

    G_f = pisi.graph.Digraph()

    def get_spec(name):
        if ctx.sourcedb.has_spec(name):
            return ctx.sourcedb.get_spec(name)
        else:
            raise Error(_('Cannot find source package: %s') % name)
    def get_src(name):
        return get_spec(name).source
    def add_src(src):
        if not str(src.name) in G_f.vertices():
            G_f.add_vertex(str(src.name), (src.version, src.release))
    def pkgtosrc(pkg):
        return ctx.sourcedb.pkgtosrc(pkg)

    # setup first
    #specfiles = [ ctx.sourcedb.get_source(x)[1] for x in A ]
    #pkgtosrc = {}
    B = A

    install_list = set()

    while len(B) > 0:
        Bp = set()
        for x in B:
            sf = get_spec(x)
            src = sf.source
            add_src(src)

            # add dependencies

            def process_dep(dep):
                if not dependency.installed_satisfies_dep(dep):
                    if dependency.repo_satisfies_dep(dep):
                        install_list.add(dep.package)
                        return
                    srcdep = pkgtosrc(dep.package)
                    if not srcdep in G_f.vertices():
                        Bp.add(srcdep)
                        add_src(get_src(srcdep))
                    if not src.name == srcdep: # firefox - firefox-devel thing
                        G_f.add_edge(src.name, srcdep)

            for builddep in src.buildDependencies:
                process_dep(builddep)

            for pkg in sf.packages:
                for rtdep in pkg.packageDependencies:
                    process_dep(rtdep)
        B = Bp

    if ctx.config.get_option('debug'):
        G_f.write_graphviz(sys.stdout)
    order_build = G_f.topological_sort()
    order_build.reverse()

    G_f2, order_inst = plan_install_pkg_names(install_list)

    return G_f, order_inst, order_build

def calculate_download_sizes(order):
    total_size = cached_size = 0

    for pkg in [ctx.packagedb.get_package(name) for name in order]:

        delta = None
        if ctx.installdb.is_installed(pkg.name):
            (version, release, build) = ctx.installdb.get_version(pkg.name)
            delta = pkg.get_delta(buildFrom=build)

        if delta:
            fn = os.path.basename(delta.packageURI)
            pkg_hash = delta.packageHash
            pkg_size = delta.packageSize
        else:
            fn = os.path.basename(pkg.packageURI)
            pkg_hash = pkg.packageHash
            pkg_size = pkg.packageSize

        path = util.join_path(ctx.config.packages_dir(), fn)

        # check the file and sha1sum to be sure it _is_ the cached package
        if os.path.exists(path) and util.sha1_file(path) == pkg_hash:
            cached_size += pkg_size

        total_size += pkg_size

    ctx.ui.notify(ui.cached, total=total_size, cached=cached_size)
    return total_size, cached_size
