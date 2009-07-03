# -*- coding: utf-8 -*-
#
# Copyright (C) 2005 - 2009, TUBITAK/UEKAE
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

import re
import time
import gzip
import gettext
import datetime
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

import piksemel

import pisi.db
import pisi.metadata
import pisi.dependency
import pisi.db.itembyrepo
import pisi.db.lazydb as lazydb

class PackageDB(lazydb.LazyDB):

    def init(self):

        self.__package_nodes = {} # Packages
        self.__revdeps = {}       # Reverse dependencies 
        self.__obsoletes = {}     # Obsoletes
        self.__replaces = {}      # Replaces

        repodb = pisi.db.repodb.RepoDB()

        for repo in repodb.list_repos():
            doc = repodb.get_repo_doc(repo)
            self.__package_nodes[repo] = self.__generate_packages(doc)
            self.__revdeps[repo] = self.__generate_revdeps(doc)
            self.__obsoletes[repo] = self.__generate_obsoletes(doc)
            self.__replaces[repo] = self.__generate_replaces(doc)

        self.pdb = pisi.db.itembyrepo.ItemByRepo(self.__package_nodes, compressed=True)
        self.rvdb = pisi.db.itembyrepo.ItemByRepo(self.__revdeps)
        self.odb = pisi.db.itembyrepo.ItemByRepo(self.__obsoletes)
        self.rpdb = pisi.db.itembyrepo.ItemByRepo(self.__replaces)

    def __generate_replaces(self, doc):
        return [x.getTagData("Name") for x in doc.tags("Package") if x.getTagData("Replaces")]

    def __generate_obsoletes(self, doc):
        distribution = doc.getTag("Distribution")
        obsoletes = distribution and distribution.getTag("Obsoletes")
        src_repo = doc.getTag("SpecFile") is not None

        if not obsoletes or src_repo:
            return []

        return map(lambda x: x.firstChild().data(), obsoletes.tags("Package"))

    def __generate_packages(self, doc):
        return dict(map(lambda x: (x.getTagData("Name"), gzip.zlib.compress(x.toString())), doc.tags("Package")))

    def __generate_revdeps(self, doc):
        revdeps = {}
        for node in doc.tags("Package"):
            name = node.getTagData('Name')
            deps = node.getTag('RuntimeDependencies')
            if deps:
                for dep in deps.tags("Dependency"):
                    revdeps.setdefault(dep.firstChild().data(), set()).add((name, dep.toString()))
        return revdeps

    def has_package(self, name, repo=None):
        return self.pdb.has_item(name, repo)

    def get_package(self, name, repo=None):
        pkg, repo = self.get_package_repo(name, repo)
        return pkg

    def search_package(self, terms, lang=None, repo=None):
        resum = '<Summary xml:lang="(%s|en)">.*?%s.*?</Summary>'
        redesc = '<Description xml:lang="(%s|en)">.*?%s.*?</Description>'
        if not lang:
            lang = pisi.pxml.autoxml.LocalText.get_lang()
        found = []
        for name, xml in self.pdb.get_items_iter(repo):
            if terms == filter(lambda term: re.compile(term, re.I).search(name) or \
                                            re.compile(resum % (lang, term), re.I).search(xml) or \
                                            re.compile(redesc % (lang, term), re.I).search(xml), terms):
                found.append(name)
        return found

    def __get_version(self, meta_doc):
        history = meta_doc.getTag("History")
        build = meta_doc.getTagData("Build")
        version = history.getTag("Update").getTagData("Version")
        release = history.getTag("Update").getAttribute("release")

        return version, release, build and int(build)

    def __get_distro_release(self, meta_doc):
        distro = meta_doc.getTagData("Distribution")
        release = meta_doc.getTagData("DistributionRelease")

        return distro, release

    def get_version_and_distro_release(self, name, repo):
        if not self.has_package(name, repo):
            raise Exception(_('Package %s not found.') % name)

        pkg_doc = piksemel.parseString(self.pdb.get_item(name, repo))
        return self.__get_version(pkg_doc) + self.__get_distro_release(pkg_doc)

    def get_version(self, name, repo):
        if not self.has_package(name, repo):
            raise Exception(_('Package %s not found.') % name)

        pkg_doc = piksemel.parseString(self.pdb.get_item(name, repo))
        return self.__get_version(pkg_doc)

    def get_package_repo(self, name, repo=None):
        pkg, repo = self.pdb.get_item_repo(name, repo)
        package = pisi.metadata.Package()
        package.parse(pkg)
        return package, repo

    def which_repo(self, name):
        return self.pdb.which_repo(name)

    def get_obsoletes(self, repo=None):
        return self.odb.get_list_item(repo)

    def get_rev_deps(self, name, repo=None):
        try:
            rvdb = self.rvdb.get_item(name, repo)
        except Exception: #FIXME: what exception could we catch here, replace with that.
            return []

        rev_deps = []
        for pkg, dep in rvdb:
            node = piksemel.parseString(dep)
            dependency = pisi.dependency.Dependency()
            dependency.package = node.firstChild().data()
            if node.attributes():
                attr = node.attributes()[0]
                dependency.__dict__[attr] = node.getAttribute(attr)
            rev_deps.append((pkg, dependency))
        return rev_deps

    # replacesdb holds the info about the replaced packages (ex. gaim -> pidgin)
    def get_replaces(self, repo=None):
        pairs = {}

        for pkg_name in self.rpdb.get_list_item():
            replaces = self.get_package(pkg_name).replaces
            for r in replaces:
                if pisi.replace.installed_package_replaced(r):
                    pairs[r.package] = pkg_name

        return pairs

    def list_packages(self, repo):
        return self.pdb.get_item_keys(repo)

    def list_newest(self, repo, since=None):
        packages = []
        historydb = pisi.db.historydb.HistoryDB()
        if since:
            since_date = datetime.datetime(*time.strptime(since, "%Y-%m-%d")[0:6])
        else:
            since_date = datetime.datetime(*time.strptime(historydb.get_last_repo_update(), "%Y-%m-%d")[0:6])

        for pkg in self.list_packages(repo):
            enter_date = datetime.datetime(*time.strptime(self.get_package(pkg).history[-1].date, "%Y-%m-%d")[0:6])
            if enter_date >= since_date:
                packages.append(pkg)
        return packages
