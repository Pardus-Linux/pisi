# -*- coding: utf-8 -*-
#
# Copyright (C) 2005 - 2010, TUBITAK/UEKAE
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

    def __init__(self):
        lazydb.LazyDB.__init__(self, cacheable=True, cachedir=ctx.config.packages_dir())

    def init(self):
        self.installed_db = self.__generate_installed_pkgs()
        self.rev_deps_db = self.__generate_revdeps()

    def __generate_installed_pkgs(self):
        return dict(map(lambda x:pisi.util.parse_package_name(x), os.listdir(ctx.config.packages_dir())))

    def __get_marked_packages(self, _type):
        info_path = os.path.join(ctx.config.info_dir(), _type)
        if os.path.exists(info_path):
            return open(info_path, "r").read().split()
        return []

    def __add_to_revdeps(self, package, revdeps):
        metadata_xml = os.path.join(self.package_path(package), ctx.const.metadata_xml)
        try:
            meta_doc = piksemel.parse(metadata_xml)
            pkg = meta_doc.getTag("Package")
        except:
            pkg = None

        if pkg is None:
            # If package info is broken or not available, skip it.
            ctx.ui.warning(_("Installation info for package '%s' is broken. "
                             "Reinstall it to fix this problem.") % package)
            del self.installed_db[package]
            return

        deps = pkg.getTag('RuntimeDependencies')
        if deps:
            for dep in deps.tags("Dependency"):
                revdep = revdeps.setdefault(dep.firstChild().data(), {})
                revdep[package] = dep.toString()
            for anydep in deps.tags("AnyDependency"):
                for dep in anydep.tags("Dependency"):
                    revdep = revdeps.setdefault(dep.firstChild().data(), {})
                    revdep[package] = anydep.toString()

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

    def search_package(self, terms, lang=None, fields=None):
        """
        fields (dict) : looks for terms in the fields which are marked as True
        If the fields is equal to None this method will search in all fields

        example :
        if fields is equal to : {'name': True, 'summary': True, 'desc': False}
        This method will return only package that contents terms in the package
        name or summary
        """
        resum = '<Summary xml:lang=.(%s|en).>.*?%s.*?</Summary>'
        redesc = '<Description xml:lang=.(%s|en).>.*?%s.*?</Description>'
        if not fields:
            fields = {'name': True, 'summary': True, 'desc': True}
        if not lang:
            lang = pisi.pxml.autoxml.LocalText.get_lang()
        found = []
        for name in self.list_installed():
            xml = open(os.path.join(self.package_path(name), ctx.const.metadata_xml)).read()
            if terms == filter(lambda term: (fields['name'] and \
                    re.compile(term, re.I).search(name)) or \
                    (fields['summary'] and \
                    re.compile(resum % (lang, term), re.I).search(xml)) or \
                    (fields['desc'] and \
                    re.compile(redesc % (lang, term), re.I).search(xml)), terms):
                found.append(name)
        return found

    def get_isa_packages(self, isa):
        risa = '<IsA>%s</IsA>' % isa
        packages = []
        for name in self.list_installed():
            xml = open(os.path.join(self.package_path(name), ctx.const.metadata_xml)).read()
            if re.compile(risa).search(xml):
                packages.append(name)
        return packages

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

    def __make_dependency(self, depStr):
        node = piksemel.parseString(depStr)
        dependency = pisi.dependency.Dependency()
        dependency.package = node.firstChild().data()
        if node.attributes():
            attr = node.attributes()[0]
            dependency.__dict__[attr] = node.getAttribute(attr)
        return dependency

    def __create_dependency(self, depStr):
        if "<AnyDependency>" in depStr:
            anydependency = pisi.specfile.AnyDependency()
            for dep in re.compile('(<Dependency .*?>.*?</Dependency>)').findall(depStr):
                anydependency.dependencies.append(self.__make_dependency(dep))
            return anydependency
        else:
            return self.__make_dependency(depStr)

    def get_rev_deps(self, name):
        rev_deps = []

        package_revdeps = self.rev_deps_db.get(name)
        if package_revdeps:
            for pkg, dep in package_revdeps.items():
                dependency = self.__create_dependency(dep)
                rev_deps.append((pkg, dependency))

        return rev_deps

    def pkg_dir(self, pkg, version, release):
        return pisi.util.join_path(ctx.config.packages_dir(), pkg + '-' + version + '-' + release)

    def get_package(self, package):
        metadata = pisi.metadata.MetaData()
        metadata_xml = os.path.join(self.package_path(package), ctx.const.metadata_xml)
        metadata.read(metadata_xml)
        return metadata.package

    def __mark_package(self, _type, package):
        packages = self.__get_marked_packages(_type)
        if package not in packages:
            packages.append(package)
            self.__write_marked_packages(_type, packages)

    def mark_pending(self, package):
        self.__mark_package(ctx.const.config_pending, package)

    def mark_needs_restart(self, package):
        self.__mark_package(ctx.const.needs_restart, package)

    def mark_needs_reboot(self, package):
        self.__mark_package(ctx.const.needs_reboot, package)

    def add_package(self, pkginfo):
        # Cleanup old revdep info
        for revdep_info in self.rev_deps_db.values():
            if pkginfo.name in revdep_info:
                del revdep_info[pkginfo.name]

        self.installed_db[pkginfo.name] = "%s-%s" % (pkginfo.version, pkginfo.release)
        self.__add_to_revdeps(pkginfo.name, self.rev_deps_db)

    def remove_package(self, package_name):
        if self.installed_db.has_key(package_name):
            del self.installed_db[package_name]

        # Cleanup revdep info
        for revdep_info in self.rev_deps_db.values():
            if package_name in revdep_info:
                del revdep_info[package_name]

        self.clear_pending(package_name)

    def list_pending(self):
        return self.__get_marked_packages(ctx.const.config_pending)

    def list_needs_restart(self):
        return self.__get_marked_packages(ctx.const.needs_restart)

    def list_needs_reboot(self):
        return self.__get_marked_packages(ctx.const.needs_reboot)

    def __write_marked_packages(self, _type, packages):
        info_file = os.path.join(ctx.config.info_dir(), _type)
        config = open(info_file, "w")
        for pkg in set(packages):
            config.write("%s\n" % pkg)
        config.close()

    def __clear_marked_packages(self, _type, package):
        if package == "*":
            self.__write_marked_packages(_type, [])
            return
        packages = self.__get_marked_packages(_type)
        if package in packages:
            packages.remove(package)
            self.__write_marked_packages(_type, packages)

    def clear_pending(self, package):
        self.__clear_marked_packages(ctx.const.config_pending, package)

    def clear_needs_restart(self, package):
        self.__clear_marked_packages(ctx.const.needs_restart, package)

    def clear_needs_reboot(self, package):
        self.__clear_marked_packages(ctx.const.needs_reboot, package)

    def package_path(self, package):

        if self.installed_db.has_key(package):
            return os.path.join(ctx.config.packages_dir(), "%s-%s" % (package, self.installed_db[package]))

        raise Exception(_('Package %s is not installed') % package)
