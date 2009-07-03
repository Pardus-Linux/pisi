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
#
# installation database
#

import os
import re
import gettext
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

import piksemel

# PiSi
import pisi
import pisi.context as ctx
import pisi.dependency
import pisi.files
import pisi.util
import pisi.db.lazydb as lazydb

class InstallDBError(pisi.Error):
    pass

class InstallInfo:

    state_map = { 'i': _('installed'), 'ip':_('installed-pending') }

    def __init__(self, state, version, release, build, distribution, time):
        self.state = state
        self.version = version
        self.release = release
        self.build = build
        self.distribution = distribution
        self.time = time

    def one_liner(self):
        import time
        time_str = time.strftime("%d %b %Y %H:%M", self.time)
        s = '%2s|%10s|%6s|%6s|%8s|%12s' % (self.state, self.version, self.release,
                                   self.build, self.distribution,
                                   time_str)
        return s

    def __str__(self):
        s = _("State: %s\nVersion: %s, Release: %s, Build: %s\n") % \
            (InstallInfo.state_map[self.state], self.version,
             self.release, self.build)
        import time
        time_str = time.strftime("%d %b %Y %H:%M", self.time)
        s += _('Distribution: %s, Install Time: %s\n') % (self.distribution,
                                                          time_str)
        return s

class InstallDB(lazydb.LazyDB):

    def init(self):
        self.installed_db = self.__generate_installed_pkgs()
        self.confing_pending_db = self.__generate_config_pending()
        self.rev_deps_db = self.__generate_revdeps()

    def __generate_installed_pkgs(self):
        return dict(map(lambda x:pisi.util.parse_package_name(x), os.listdir(ctx.config.packages_dir())))

    def __generate_config_pending(self):
        pending_info_path = os.path.join(ctx.config.info_dir(), ctx.const.config_pending)
        if os.path.exists(pending_info_path):
            return open(pending_info_path, "r").read().split()
        return []

    def __add_to_revdeps(self, package, revdeps):
        metadata_xml = os.path.join(self.package_path(package), ctx.const.metadata_xml)
        meta_doc = piksemel.parse(metadata_xml)
        name = meta_doc.getTag("Package").getTagData('Name')
        deps = meta_doc.getTag("Package").getTag('RuntimeDependencies')
        if deps:
            for dep in deps.tags("Dependency"):
                revdeps.setdefault(dep.firstChild().data(), set()).add((name, dep.toString()))

    def __generate_revdeps(self):
        revdeps = {}
        for package in self.list_installed():
            self.__add_to_revdeps(package, revdeps)
        return revdeps
        
    def list_installed(self):
        return self.installed_db.keys()
 
    def has_package(self, package):
        return self.installed_db.has_key(package)

    def list_installed_without_buildno(self):
        rebuildno = '<Build>.*?</Build>'
        found = []
        for name in self.list_installed():
            xml = open(os.path.join(self.package_path(name), ctx.const.metadata_xml)).read()
            if not re.compile(rebuildno).search(xml):
                found.append(name)
        return found

    def __get_version(self, meta_doc):
        history = meta_doc.getTag("Package").getTag("History")
        build = meta_doc.getTag("Package").getTagData("Build")
        version = history.getTag("Update").getTagData("Version")
        release = history.getTag("Update").getAttribute("release")

        return version, release, build and int(build)

    def __get_distro_release(self, meta_doc):
        distro = meta_doc.getTag("Package").getTagData("Distribution")
        release = meta_doc.getTag("Package").getTagData("DistributionRelease")

        return distro, release

    def get_version_and_distro_release(self, package):
        metadata_xml = os.path.join(self.package_path(package), ctx.const.metadata_xml)
        meta_doc = piksemel.parse(metadata_xml)
        return self.__get_version(meta_doc) + self.__get_distro_release(meta_doc)

    def get_version(self, package):
        metadata_xml = os.path.join(self.package_path(package), ctx.const.metadata_xml)
        meta_doc = piksemel.parse(metadata_xml)
        return self.__get_version(meta_doc)

    def get_files(self, package):
        files = pisi.files.Files()
        files_xml = os.path.join(self.package_path(package), ctx.const.files_xml)
        files.read(files_xml)
        return files

    def get_config_files(self, package):
        files = self.get_files(package)
        return filter(lambda x: x.type == 'config', files.list)

    def search_package(self, terms, lang=None):
        resum = '<Summary xml:lang="(%s|en)">.*?%s.*?</Summary>'
        redesc = '<Description xml:lang="(%s|en)">.*?%s.*?</Description>'
        if not lang:
            lang = pisi.pxml.autoxml.LocalText.get_lang()
        found = []
        for name in self.list_installed():
            xml = open(os.path.join(self.package_path(name), ctx.const.metadata_xml)).read()
            if terms == filter(lambda term: re.compile(term, re.I).search(name) or \
                                            re.compile(resum % (lang, term), re.I).search(xml) or \
                                            re.compile(redesc % (lang, term), re.I).search(xml), terms):
                found.append(name)
        return found

    def get_info(self, package):
        files_xml = os.path.join(self.package_path(package), ctx.const.files_xml)
        ctime = pisi.util.creation_time(files_xml)
        pkg = self.get_package(package)
        state = "i"
        if pkg.name in self.list_pending():
            state = "ip"
        
        info = InstallInfo(state,
                           pkg.version,
                           pkg.release,
                           pkg.build,
                           pkg.distribution,
                           ctime)
        return info

    def get_rev_deps(self, name):
        
        rev_deps = []

        if self.rev_deps_db.has_key(name):
            for pkg, dep in self.rev_deps_db[name]:
                node = piksemel.parseString(dep)
                dependency = pisi.dependency.Dependency()
                dependency.package = node.firstChild().data()
                if node.attributes():
                    attr = node.attributes()[0]
                    dependency.__dict__[attr] = node.getAttribute(attr)
                rev_deps.append((pkg, dependency))
            
        return rev_deps

    def pkg_dir(self, pkg, version, release):
        return pisi.util.join_path(ctx.config.packages_dir(), pkg + '-' + version + '-' + release)

    def get_package(self, package):
        metadata = pisi.metadata.MetaData()
        metadata_xml = os.path.join(self.package_path(package), ctx.const.metadata_xml)
        metadata.read(metadata_xml)
        return metadata.package

    def mark_pending(self, package):
        if package not in self.confing_pending_db:
            self.confing_pending_db.append(package)
            self.__write_config_pending()

    def add_package(self, pkginfo):
        self.installed_db[pkginfo.name] = "%s-%s" % (pkginfo.version, pkginfo.release)
        self.__add_to_revdeps(pkginfo.name, self.rev_deps_db)
        
    def remove_package(self, package_name):
        if self.installed_db.has_key(package_name):
            del self.installed_db[package_name]
        self.clear_pending(package_name)

    def list_pending(self):
        return self.confing_pending_db

    def clear_pending(self, package):
        if package in self.confing_pending_db:
            self.confing_pending_db.remove(package)
            self.__write_config_pending()

    def __write_config_pending(self):
        pending_info_file = os.path.join(ctx.config.info_dir(), ctx.const.config_pending)
        pending = open(pending_info_file, "w")
        for pkg in set(self.confing_pending_db):
            pending.write("%s\n" % pkg)
        pending.close()

    def package_path(self, package):

        if self.installed_db.has_key(package):
            return os.path.join(ctx.config.packages_dir(), "%s-%s" % (package, self.installed_db[package]))

        raise Exception(_('Package %s is not installed') % package)
