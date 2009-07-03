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

"""Atomic package operations such as install/remove/upgrade"""

import gettext
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

import os
import shutil

import pisi
import pisi.context as ctx
import pisi.conflict
import pisi.util as util
import pisi.metadata
import pisi.files
import pisi.uri
import pisi.ui
import pisi.version
import pisi.operations.helper
import pisi.operations.delta
import pisi.db

class Error(pisi.Error):
    pass

class NotfoundError(pisi.Error):
    pass

# single package operations

class AtomicOperation(object):

    def __init__(self, ignore_dep = None):
        #self.package = package
        if ignore_dep==None:
            self.ignore_dep = ctx.config.get_option('ignore_dependency')
        else:
            self.ignore_dep = ignore_dep

        self.historydb = pisi.db.historydb.HistoryDB()

    def run(self, package):
        "perform an atomic package operation"
        pass

# possible paths of install operation
(INSTALL, REINSTALL, UPGRADE, DOWNGRADE, REMOVE) = range(5)
opttostr = {INSTALL:"install", REMOVE:"remove", REINSTALL:"reinstall", UPGRADE:"upgrade", DOWNGRADE:"downgrade"}

class Install(AtomicOperation):
    "Install class, provides install routines for pisi packages"

    @staticmethod
    def from_name(name, ignore_dep = None):
        packagedb = pisi.db.packagedb.PackageDB()
        # download package and return an installer object
        # find package in repository
        repo = packagedb.which_repo(name)
        if repo:
            repodb = pisi.db.repodb.RepoDB()
            ctx.ui.info(_("Package %s found in repository %s") % (name, repo))

            repo = repodb.get_repo(repo)
            pkg = packagedb.get_package(name)
            delta = None

            installdb = pisi.db.installdb.InstallDB()
            # Package is installed. This is an upgrade. Check delta.
            if installdb.has_package(pkg.name):
                (version, release, build, distro, distro_release) = installdb.get_version_and_distro_release(pkg.name)
                # pisi distro upgrade should not use delta support
                if distro == pkg.distribution and distro_release == pkg.distributionRelease:
                    delta = pkg.get_delta(buildFrom=build)

            # If delta exists than use the delta uri.
            if delta:
                pkg_uri = delta.packageURI
                pkg_hash = delta.packageHash
            else:
                pkg_uri = pkg.packageURI
                pkg_hash = pkg.packageHash

            uri = pisi.uri.URI(pkg_uri)
            if uri.is_absolute_path():
                pkg_path = str(pkg_uri)
            else:
                pkg_path = os.path.join(os.path.dirname(repo.indexuri.get_uri()),
                                        str(uri.path()))

            ctx.ui.info(_("Package URI: %s") % pkg_path, verbose=True)

            # Bug 4113
            cached_file = pisi.package.Package.is_cached(pkg_path)
            if cached_file and util.sha1_file(cached_file) != pkg_hash:
                os.unlink(cached_file)

            install_op = Install(pkg_path, ignore_dep)

            # Bug 4113
            downloaded_file = install_op.package.filepath
            if pisi.util.sha1_file(downloaded_file) != pkg_hash:
                raise pisi.Error(_("Download Error: Package does not match the repository package."))

            return install_op
        else:
            raise Error(_("Package %s not found in any active repository.") % name)

    def __init__(self, package_fname, ignore_dep = None, ignore_file_conflicts = None):
        "initialize from a file name"
        super(Install, self).__init__(ignore_dep)
        if not ignore_file_conflicts:
            ignore_file_conflicts = ctx.get_option('ignore_file_conflicts')
        self.ignore_file_conflicts = ignore_file_conflicts
        self.package_fname = package_fname
        self.package = pisi.package.Package(package_fname)
        self.package.read()
        self.metadata = self.package.metadata
        self.files = self.package.files
        self.pkginfo = self.metadata.package
        self.filesdb = pisi.db.filesdb.FilesDB()
        self.installdb = pisi.db.installdb.InstallDB()
        self.operation = INSTALL

    def install(self, ask_reinstall = True):
        ctx.ui.status(_('Installing %s, version %s, release %s, build %s') %
                (self.pkginfo.name, self.pkginfo.version,
                 self.pkginfo.release, self.pkginfo.build))
        ctx.ui.notify(pisi.ui.installing, package=self.pkginfo, files=self.files)

        self.ask_reinstall = ask_reinstall
        self.check_requirements()
        self.check_versioning("%s-%s" % (self.pkginfo.version, self.pkginfo.release))
        self.check_relations()
        self.check_operation()
        self.extract_install()

        ctx.disable_keyboard_interrupts()
        self.store_pisi_files()
        self.postinstall()

        self.update_databases()

        ctx.enable_keyboard_interrupts()

        ctx.ui.close()
        if self.operation == UPGRADE:
            event = pisi.ui.upgraded
        else:
            event = pisi.ui.installed
        ctx.ui.notify(event, package = self.pkginfo, files = self.files)

    def check_requirements(self):
        """check system requirements"""
        #TODO: IS THERE ENOUGH SPACE?
        # what to do if / is split into /usr, /var, etc.
        # check comar
        if self.metadata.package.providesComar and ctx.comar:
            import pisi.comariface as comariface
            comariface.get_iface()

    def check_versioning(self, version):
        if not pisi.version.Version.valid(version):
            raise Error("%s is not a valid PiSi version format" % version)

    def check_relations(self):
        # check dependencies
        if not ctx.config.get_option('ignore_dependency'):
            if not self.pkginfo.installable():
                raise Error(_("%s package cannot be installed unless the dependencies are satisfied") %
                            self.pkginfo.name)

        # If it is explicitly specified that package conflicts with this package and also
        # we passed check_conflicts tests in operations.py than this means a non-conflicting
        # pkg is in "order" to be installed that has no file conflict problem with this package. 
        # PS: we need this because "order" generating code does not consider conflicts.
        def really_conflicts(pkg):
            if not self.pkginfo.conflicts:
                return True

            return not pkg in map(lambda x:x.package, self.pkginfo.conflicts)
        
        # check file conflicts
        file_conflicts = []
        for f in self.files.list:
            if self.filesdb.has_file(f.path):
                pkg, existing_file = self.filesdb.get_file(f.path)
                dst = pisi.util.join_path(ctx.config.dest_dir(), f.path)
                if pkg != self.pkginfo.name and not os.path.isdir(dst) and really_conflicts(pkg):
                    file_conflicts.append( (pkg, existing_file) )
        if file_conflicts:
            file_conflicts_str = ""
            for (pkg, existing_file) in file_conflicts:
                file_conflicts_str += _("/%s from %s package\n") % (existing_file, pkg)
            msg = _('File conflicts:\n%s') % file_conflicts_str
            if self.ignore_file_conflicts:
                ctx.ui.warning(msg)
            else:
                raise Error(msg)

    def check_operation(self):

        self.old_pkginfo = None
        pkg = self.pkginfo

        if self.installdb.has_package(pkg.name): # is this a reinstallation?
            ipkg = self.installdb.get_info(pkg.name)
            repomismatch = ipkg.distribution != pkg.distribution
            (iversion, irelease, ibuild) = self.installdb.get_version(pkg.name)

            # determine if same version
            self.same_ver = False
            ignore_build = ctx.config.options and ctx.config.options.ignore_build_no
            if repomismatch or (not ibuild) or (not pkg.build) or ignore_build:
                # we don't look at builds to compare two package versions
                if pisi.version.Version(pkg.release) == pisi.version.Version(irelease):
                    self.same_ver = True
            else:
                if pkg.build == ibuild:
                    self.same_ver = True

            if self.same_ver:
                if self.ask_reinstall:
                    if not ctx.ui.confirm(_('Re-install same version package?')):
                        raise Error(_('Package re-install declined'))
                self.operation = REINSTALL
            else:
                # is this an upgrade?
                # determine and report the kind of upgrade: version, release, build
                if pisi.version.Version(pkg.version) > pisi.version.Version(iversion):
                    ctx.ui.info(_('Upgrading to new upstream version'))
                    self.operation = UPGRADE
                elif pisi.version.Version(pkg.release) > pisi.version.Version(irelease):
                    ctx.ui.info(_('Upgrading to new distribution release'))
                    self.operation = UPGRADE
                elif ((not ignore_build) and ibuild and pkg.build
                       and pkg.build > ibuild):
                    ctx.ui.info(_('Upgrading to new distribution build'))
                    self.operation = UPGRADE

                # is this a downgrade? confirm this action.
                if not self.operation == UPGRADE:
                    if pisi.version.Version(pkg.version) < pisi.version.Version(iversion):
                        #x = _('Downgrade to old upstream version?')
                        x = None
                    elif pisi.version.Version(pkg.release) < pisi.version.Version(irelease):
                        x = _('Downgrade to old distribution release?')
                    else:
                        x = _('Downgrade to old distribution build?')
                    if self.ask_reinstall and x and not ctx.ui.confirm(x):
                        raise Error(_('Package downgrade declined'))
                    self.operation = DOWNGRADE

            # schedule for reinstall
            self.old_files = self.installdb.get_files(pkg.name)
            self.old_pkginfo = self.installdb.get_info(pkg.name)
            self.old_path = self.installdb.pkg_dir(pkg.name, iversion, irelease)
            self.remove_old = Remove(pkg.name)
            self.remove_old.run_preremove()

    def reinstall(self):
        return not self.operation == INSTALL

    def postinstall(self):
        self.config_later = False
        if ctx.comar:
            import pisi.comariface
            try:
                if self.operation == UPGRADE:
                    fromVersion = self.old_pkginfo.version
                    fromRelease = self.old_pkginfo.release
                else:
                    fromVersion = None
                    fromRelease = None
                ctx.ui.notify(pisi.ui.configuring, package = self.pkginfo, files = self.files)
                pisi.comariface.post_install(
                    self.pkginfo.name,
                    self.metadata.package.providesComar,
                    self.package.comar_dir(),
                    os.path.join(self.package.pkg_dir(), ctx.const.metadata_xml),
                    os.path.join(self.package.pkg_dir(), ctx.const.files_xml),
                    fromVersion,
                    fromRelease,
                    self.metadata.package.version,
                    self.metadata.package.release
                    )
                ctx.ui.notify(pisi.ui.configured, package = self.pkginfo, files = self.files)
            except pisi.comariface.Error:
                ctx.ui.warning(_('%s configuration failed.') % self.pkginfo.name)
                self.config_later = True
        else:
            self.config_later = True

    def extract_install(self):
        "unzip package in place"

        ctx.ui.notify(pisi.ui.extracting, package = self.pkginfo, files = self.files)

        config_changed = []
        def check_config_changed(config):
            fpath = pisi.util.join_path(ctx.config.dest_dir(), config.path)
            if pisi.util.config_changed(config):
                config_changed.append(fpath)
                self.historydb.save_config(self.pkginfo.name, fpath)
                if os.path.exists(fpath + '.old'):
                    os.unlink(fpath + '.old')
                os.rename(fpath, fpath + '.old')

        # old config files are kept as they are. New config files from the installed
        # packages are saved with ".newconfig" string appended to their names.
        def rename_configs():
            for path in config_changed:
                newconfig = path + '.newconfig'
                oldconfig = path + '.old'
                if os.path.exists(newconfig):
                    os.unlink(newconfig)

                # In the case of delta packages: the old package and the new package
                # may contain same config typed files with same hashes, so the delta
                # package will not have that config file. In order to protect user
                # changed config files, they are renamed with ".old" prefix in case
                # of the hashes of these files on the filesystem and the new config 
                # file that is coming from the new package. But in delta package case
                # with the given scenario there wont be any, so we can pass this one.
                # If the config files were not be the same between these packages the
                # delta package would have it and extract it and the path would point
                # to that new config file. If they are same and the user had changed 
                # that file and using the changed config file, there is no problem 
                # here.
                if os.path.exists(path):
                    os.rename(path, newconfig)

                os.rename(oldconfig, path)

        # Delta package does not contain the files that have the same hash as in 
        # the old package's. Because it means the file has not changed. But some 
        # of these files may be relocated to some other directory in the new package. 
        # We handle these cases here.
        def relocate_files():
            for old_file, new_file in pisi.operations.delta.find_relocations(self.old_files, self.files):
                old_path, new_path = ("/" + old_file.path, "/" + new_file.path)

                destdir = os.path.dirname(new_path)
                if not os.path.exists(destdir):
                    os.makedirs(destdir)

                if os.path.lexists(new_path):
                    os.unlink(new_path)

                if os.path.islink(old_path):
                    os.symlink(os.readlink(old_path), new_path)
                else:
                    shutil.copy(old_path, new_path)

        # remove left over files from the old package.
        def clean_leftovers():
            new = set(str(f.path) for f in self.files.list)
            old = set(str(f.path) for f in self.old_files.list)
            leftover = old - new
            old_fileinfo = {}
            for fileinfo in self.old_files.list:
                old_fileinfo[str(fileinfo.path)] = fileinfo
            for path in leftover:
                    Remove.remove_file(old_fileinfo[path], self.pkginfo.name)

        if self.reinstall():
            # get 'config' typed file objects
            new = filter(lambda x: x.type == 'config', self.files.list)
            old = filter(lambda x: x.type == 'config', self.old_files.list)

            # get config path lists
            newconfig = set(str(x.path) for x in new)
            oldconfig = set(str(x.path) for x in old)

            config_overlaps = newconfig & oldconfig
            if config_overlaps:
                files = filter(lambda x: x.path in config_overlaps, old)
                for f in files:
                    check_config_changed(f)
        else:
            for f in self.files.list:
                if f.type == 'config':
                    # there may be left over config files
                    check_config_changed(f)

        if self.package_fname.endswith(ctx.const.delta_package_suffix):
            relocate_files()

        self.package.extract_install(ctx.config.dest_dir())

        if config_changed:
            rename_configs()

        if self.reinstall():
            clean_leftovers()


    def store_pisi_files(self):
        """put files.xml, metadata.xml, actions.py and COMAR scripts
        somewhere in the file system. We'll need these in future..."""

        if self.reinstall():
            util.clean_dir(self.old_path)

        ctx.ui.info(_('Storing %s, ') % ctx.const.files_xml, verbose=True)
        self.package.extract_file(ctx.const.files_xml, self.package.pkg_dir())

        ctx.ui.info(_('Storing %s.') % ctx.const.metadata_xml, verbose=True)
        self.package.extract_file(ctx.const.metadata_xml, self.package.pkg_dir())

        for pcomar in self.metadata.package.providesComar:
            fpath = os.path.join(ctx.const.comar_dir, pcomar.script)
            # comar prefix is added to the pkg_dir while extracting comar
            # script file. so we'll use pkg_dir as destination.
            ctx.ui.info(_('Storing %s') % fpath, verbose=True)
            self.package.extract_file(fpath, self.package.pkg_dir())

    def update_databases(self):
        "update databases"
        if self.reinstall():
            self.remove_old.remove_db()

        if self.config_later:
            self.installdb.mark_pending(self.pkginfo.name)

        # filesdb
        self.filesdb.add_files(self.metadata.package.name, self.files)

        # installed packages
        self.installdb.add_package(self.pkginfo)

        otype = "delta" if self.package_fname.endswith("delta.pisi") else None
        self.historydb.add_and_update(pkgBefore=self.old_pkginfo, pkgAfter=self.pkginfo, operation=opttostr[self.operation], otype=otype)

def install_single(pkg, upgrade = False):
    """install a single package from URI or ID"""
    url = pisi.uri.URI(pkg)
    # Check if we are dealing with a remote file or a real path of
    # package filename. Otherwise we'll try installing a package from
    # the package repository.
    if url.is_remote_file() or os.path.exists(url.uri):
        install_single_file(pkg, upgrade)
    else:
        install_single_name(pkg, upgrade)

# FIXME: Here and elsewhere pkg_location must be a URI
def install_single_file(pkg_location, upgrade = False):
    """install a package file"""
    Install(pkg_location).install(not upgrade)

def install_single_name(name, upgrade = False):
    """install a single package from ID"""
    install = Install.from_name(name)
    install.install(not upgrade)

class Remove(AtomicOperation):

    def __init__(self, package_name, ignore_dep = None):
        super(Remove, self).__init__(ignore_dep)
        self.installdb = pisi.db.installdb.InstallDB()
        self.filesdb = pisi.db.filesdb.FilesDB()
        self.package_name = package_name
        self.package = self.installdb.get_package(self.package_name)
        try:
            self.files = self.installdb.get_files(self.package_name)
        except pisi.Error, e:
            # for some reason file was deleted, we still allow removes!
            ctx.ui.error(unicode(e))
            ctx.ui.warning(_('File list could not be read for package %s, continuing removal.') % package_name)
            self.files = pisi.files.Files()

    def run(self):
        """Remove a single package"""

        ctx.ui.status(_('Removing package %s') % self.package_name)
        ctx.ui.notify(pisi.ui.removing, package = self.package, files = self.files)
        if not self.installdb.has_package(self.package_name):
            raise Exception(_('Trying to remove nonexistent package ')
                            + self.package_name)

        self.check_dependencies()

        self.run_preremove()
        for fileinfo in self.files.list:
            self.remove_file(fileinfo, self.package_name, True)

        self.update_databases()

        self.remove_pisi_files()
        ctx.ui.close()
        ctx.ui.notify(pisi.ui.removed, package = self.package, files = self.files)

    def check_dependencies(self):
        #FIXME: why is this not implemented? -- exa
        #we only have to check the dependencies to ensure the
        #system will be consistent after this removal
        pass
        # is there any package who depends on this package?

    @staticmethod
    def remove_file(fileinfo, package_name, remove_permanent=False):

        if fileinfo.permanent and not remove_permanent:
            return
        
        fpath = pisi.util.join_path(ctx.config.dest_dir(), fileinfo.path)

        historydb = pisi.db.historydb.HistoryDB()
        filesdb = pisi.db.filesdb.FilesDB()
        # we should check if the file belongs to another
        # package (this can legitimately occur while upgrading
        # two packages such that a file has moved from one package to
        # another as in #2911)
        if filesdb.has_file(fileinfo.path):
            pkg, existing_file = filesdb.get_file(fileinfo.path)
            if pkg != package_name:
                ctx.ui.warning(_('Not removing conflicted file : %s') % fpath)
                return

        if fileinfo.type == ctx.const.conf:
            # config files are precious, leave them as they are
            # unless they are the same as provided by package.
            # remove symlinks as they are, cause if the hash of the
            # file it links has changed, it will be kept as is,
            # and when the package is reinstalled the symlink will
            # link to that changed file again.
            try:
                if os.path.islink(fpath) or pisi.util.sha1_file(fpath) == fileinfo.hash:
                    os.unlink(fpath)
                else:
                    # keep changed file in history
                    historydb.save_config(package_name, fpath)

                    # after saving to history db, remove the config file any way
                    if ctx.get_option("purge"):
                        os.unlink(fpath)
            except pisi.util.FileError:
                pass
        else:
            if os.path.isfile(fpath) or os.path.islink(fpath):
                os.unlink(fpath)
            elif os.path.isdir(fpath) and not os.listdir(fpath):
                os.rmdir(fpath)
            else:
                ctx.ui.warning(_('Installed file %s does not exist on system [Probably you manually deleted]') % fpath)
                return

            # remove emptied directories
            dpath = os.path.dirname(fpath)
            while dpath != '/' and not os.listdir(dpath):
                os.rmdir(dpath)
                dpath = os.path.dirname(dpath)

    def run_preremove(self):
        if ctx.comar:
            import pisi.comariface
            pisi.comariface.pre_remove(
                self.package_name,
                os.path.join(self.package.pkg_dir(), ctx.const.metadata_xml),
                os.path.join(self.package.pkg_dir(), ctx.const.files_xml),
            )

    def update_databases(self):
        self.remove_db()
        self.historydb.add_and_update(pkgBefore=self.package, operation="remove")        

    def remove_pisi_files(self):
        util.clean_dir(self.package.pkg_dir())

    def remove_db(self):
        self.installdb.remove_package(self.package_name)
        self.filesdb.remove_files(self.files.list)
# FIX:DB
#         # FIXME: something goes wrong here, if we use ctx operations ends up with segmentation fault!
#         pisi.db.packagedb.remove_tracking_package(self.package_name)


def remove_single(package_name):
    Remove(package_name).run()

def build(package):
    # wrapper for build op
    import pisi.operations.build
    return pisi.operations.build.build(package)
