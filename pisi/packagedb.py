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

"""package database
interface for update/query to local package repository

we basically store everything in PackageInfo class
yes, we are cheap
"""

import gettext
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

import pisi
import pisi.context as ctx
import pisi.itembyrepodb

class Error(pisi.Error):
    pass

class NotfoundError(pisi.Error):
    def __init__(self, pkg):
        pisi.Error.__init__("Package %s not found" % pkg)
        self.pkg = pkg

class PackageDB(object):
    """PackageDB class provides an interface to the package database
    using shelf objects"""

    def __init__(self):
        self.d = pisi.itembyrepodb.ItemByRepoDB('package')
        self.dr = pisi.itembyrepodb.ItemByRepoDB('revdep')
        self.do = pisi.itembyrepodb.ItemByRepoDB('obsoleted')
        self.drp = pisi.itembyrepodb.ItemByRepoDB('replaces')

    def close(self):
        self.d.close()
        self.dr.close()
        self.do.close()
        self.drp.close()

    def destroy(self):
        self.d.destroy()
        self.dr.destroy()
        self.do.destroy()
        self.drp.destroy()

    def has_package(self, name, repo=None, txn = None):
        return self.d.has_key(name, repo, txn=txn)

    def get_package(self, name, repo=None, txn = None):
        try:
            return self.d.get_item(name, repo, txn=txn)
        except pisi.itembyrepodb.NotfoundError:
            raise Error(_('Package %s not found') % name)

    def get_package_repo(self, name, repo=None, txn = None):
        return self.d.get_item_repo(name, repo, txn=txn)

    def which_repo(self, name, txn = None):
        return self.d.which_repo(name, txn=txn)

    def get_obsoletes(self, repo=None):
        obsoletes = []
        for r in self.do.list(repo):
            obsoletes.extend(self.do.get_item(r, repo))

        replaces = self.get_replaces(repo)
        return set(str(o) for o in obsoletes) - set(replaces.keys())

    # replacesdb holds the info about the replaced packages (ex. gaim -> pidgin)
    def get_replaces(self, repo = None):
        pairs = {}
        for pkg_name in self.drp.list(repo):
            replaces = self.drp.get_item(pkg_name, repo)
            for r in replaces:
                if pisi.replace.installed_package_replaced(r):
                    pairs[r.package] = pkg_name

        return pairs

    def get_rev_deps(self, name, repo = None, txn = None):
        if self.dr.has_key(name, repo, txn=txn):
            return self.dr.get_item(name, repo, txn=txn)
        else:
            return []

    def get_deps(self, name, repo = None, txn = None):
        if self.d.has_key(name, repo, txn=txn):
            pinfo =  self.d.get_item(name, repo, txn=txn)
            return pinfo.packageDependencies
        else:
            return []

    def list_packages(self, repo=None):
        return self.d.list(repo)

    def add_obsoletes(self, obsoletes, repo, txn = None):
        def proc(txn):
            self.do.add_item(repo, obsoletes, repo, txn)
        ctx.txn_proc(proc, txn)

    def add_package(self, package_info, repo, txn = None):
        name = str(package_info.name)

        def proc(txn):
            self.d.add_item(name, package_info, repo, txn)
            for dep in package_info.runtimeDependencies():
                dep_name = str(dep.package)
                if self.dr.has_key(dep_name, repo, txn):
                    revdep = self.dr.get_item(dep_name, repo, txn)
                    revdep = filter(lambda (n,d):n!=name, revdep)
                    revdep.append( (name, dep) )
                    self.dr.add_item(dep_name, revdep, repo, txn)
                else:
                    self.dr.add_item(dep_name, [ (name, dep) ], repo, txn)

            if package_info.replaces:
                self.drp.add_item(name, package_info.replaces, repo, txn)

            # add component
            ctx.componentdb.add_package(package_info.partOf, package_info.name, repo, txn)

        ctx.txn_proc(proc, txn)

    def clear(self, txn = None):
        self.d.clear()
        self.dr.clear()
        self.do.clear()
        self.drp.clear()

    def remove_package(self, name, repo = None, txn = None):
        name = str(name)
        def proc(txn):
            package_info = self.d.get_item(name, repo, txn=txn)
            self.d.remove_item(name, repo, txn=txn)
            for dep in package_info.runtimeDependencies():
                dep_name = str(dep.package)
                if self.dr.has_key(dep_name, repo, txn):
                    revdep = self.dr.get_item(dep_name, repo, txn)
                    revdep = filter(lambda (n,d):n!=name, revdep)
                    if revdep:
                        self.dr.add_item(dep_name, revdep, repo, txn)
                    else:
                        # Bug 3558: removal of revdep list of a package from revdepdb
                        # should only be done by the list members (dep. packages), not
                        # the package itself. So if a package is removed, it is removed
                        # from packagedb but its revdepdb part may still exist, until
                        # all the list members are removed.
                        self.dr.remove_item(dep_name, repo, txn=txn)

            # remove from component
            ctx.componentdb.remove_package(package_info.partOf, package_info.name, repo, txn)

        self.d.txn_proc(proc, txn)

    def remove_repo(self, repo, txn = None):
        def proc(txn):
            self.d.remove_repo(repo, txn=txn)
            self.dr.remove_repo(repo, txn=txn)
            self.do.remove_repo(repo, txn=txn)
            self.drp.remove_repo(repo, txn=txn)
        self.d.txn_proc(proc, txn)

pkgdb = None

def remove_tracking_package(name, txn = None):
    # remove the guy from the tracking databases
    if pkgdb.has_package(name, pisi.itembyrepodb.installed, txn=txn):
        pkgdb.remove_package(name, pisi.itembyrepodb.installed, txn=txn)
    if pkgdb.has_package(name, pisi.itembyrepodb.thirdparty, txn=txn):
        pkgdb.remove_package(name, pisi.itembyrepodb.thirdparty, txn=txn)

def init_db():
    global pkgdb
    pkgdb = PackageDB()
    return pkgdb

def finalize_db():
    global pkgdb
    if pkgdb:
        pkgdb.close()
