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

"""PiSi source/package index"""

import os
import shutil

import gettext
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

import pisi
import pisi.context as ctx
import pisi.specfile as specfile
import pisi.metadata as metadata
import pisi.util as util
import pisi.package
import pisi.pxml.xmlfile as xmlfile
import pisi.file
import pisi.pxml.autoxml as autoxml
import pisi.component as component

class Error(pisi.Error):
    pass

class Index(xmlfile.XmlFile):
    __metaclass__ = autoxml.autoxml

    tag = "PISI"

    t_Distribution = [ component.Distribution, autoxml.optional ]
    t_Specs = [ [specfile.SpecFile], autoxml.optional, "SpecFile"]
    t_Packages = [ [metadata.Package], autoxml.optional, "Package"]
    #t_Metadatas = [ [metadata.MetaData], autoxml.optional, "MetaData"]
    t_Components = [ [component.Component], autoxml.optional, "Component"]

    def name(self):
        return self.distribution.name + self.distribution.repositoryname

    def read_uri(self, uri, tmpdir, force = False):
        self.read(uri, tmpDir=tmpdir, sha1sum=not force,
                  compress=pisi.file.File.auto, sign=pisi.file.File.detached, copylocal = True)

    # read index for a given repo, force means download even if remote not updated
    def read_uri_of_repo(self, uri, repo = None, force = False):
        """Read PSPEC file"""
        if repo:
            tmpdir = os.path.join(ctx.config.index_dir(), repo)
        else:
            tmpdir = os.path.join(ctx.config.tmp_dir(), 'index')
            pisi.util.clean_dir(tmpdir)
        pisi.util.check_dir(tmpdir)

        # write uri
        urlfile = file(pisi.util.join_path(tmpdir, 'uri'), 'w')
        urlfile.write(uri) # uri
        urlfile.close()

        self.read_uri(uri, tmpdir, force)

        if not repo:
            repo = self.distribution.name()
            # and what do we do with it? move it to index dir properly
            newtmpdir = os.path.join(ctx.config.index_dir(), repo)
            pisi.util.clean_dir(newtmpdir) # replace newtmpdir
            shutil.move(tmpdir, newtmpdir)

    def check_signature(self, filename, repo):
        tmpdir = os.path.join(ctx.config.index_dir(), repo)
        pisi.file.File.check_signature(filename, tmpdir)

    def index(self, repo_uri, skip_sources=False):
        self.repo_dir = repo_uri

        packages = []
        deltas = {}
        for root, dirs, files in os.walk(repo_uri):
            for fn in files:

                if fn.endswith(ctx.const.delta_package_suffix):
                    name, version = util.parse_package_name(fn)
                    deltas.setdefault(name, []).append(os.path.join(root, fn))
                elif fn.endswith(ctx.const.package_suffix):
                    packages.append(os.path.join(root, fn))

                if fn == 'component.xml':
                    ctx.ui.info(_('Adding %s to component index') % fn)
                    self.add_component(os.path.join(root, fn))
                if fn == 'pspec.xml' and not skip_sources:
                    self.add_spec(os.path.join(root, fn), repo_uri)
                if fn == 'distribution.xml':
                    self.add_distro(os.path.join(root, fn))

        try:
            obsoletes_list = map(str, self.distribution.obsoletes)
        except AttributeError:
            obsoletes_list = []

        for pkg in util.filter_latest_packages(packages):
            pkg_name = util.parse_package_name(os.path.basename(pkg))[0]
            if pkg_name not in obsoletes_list:
                ctx.ui.info(_('Adding %s to package index') % pkg)
                self.add_package(pkg, deltas, repo_uri)

    def update_db(self, repo, txn = None):
        # FIXME: updating db takes too much time. So a notify mechanism is used to inform the status
        # of the operation.

        self.progress = ctx.ui.Progress(len(self.packages)+len(self.specs))
        self.processed = 0

        def update_progress():
            self.processed += 1
            ctx.ui.display_progress(operation = "updatingrepo",
                                    percent = self.progress.update(self.processed),
                                    info = _("Updating package database of %s") % repo)

        ctx.componentdb.remove_repo(repo, txn=txn)
        for comp in self.components:
            ctx.componentdb.update_component(comp, repo, txn)
        ctx.packagedb.remove_repo(repo, txn=txn)
        if self.distribution is not None:
            ctx.packagedb.add_obsoletes(self.distribution.obsoletes, repo, txn=txn)
        for pkg in self.packages:
            ctx.packagedb.add_package(pkg, repo, txn=txn)
            update_progress()
        ctx.sourcedb.remove_repo(repo, txn=txn)
        for sf in self.specs:
            ctx.sourcedb.add_spec(sf, repo, txn=txn)
            update_progress()

    def add_package(self, path, deltas, repo_uri):
        package = pisi.package.Package(path, 'r')
        md = package.get_metadata()
        md.package.packageSize = os.path.getsize(path)
        md.package.packageHash = util.sha1_file(path)
        if ctx.config.options and ctx.config.options.absolute_urls:
            md.package.packageURI = os.path.realpath(path)
        else:                           # create relative path by default
            # TODO: in the future well do all of this with purl/pfile/&helpers
            # really? heheh -- future exa
            md.package.packageURI = util.removepathprefix(repo_uri, path)
        # check package semantics
        errs = md.errors()
        if md.errors():
            ctx.ui.error(_('Package %s: metadata corrupt, skipping...') % md.package.name)
            ctx.ui.error(unicode(Error(*errs)))
        else:
            # No need to carry these with index (#3965)
            md.package.files = None
            md.package.additionalFiles = None

            if md.package.name in deltas:
                for delta_path in deltas[md.package.name]:
                    delta = metadata.Delta()
                    delta.packageURI = util.removepathprefix(repo_uri, delta_path)
                    delta.packageSize = os.path.getsize(delta_path)
                    delta.packageHash = util.sha1_file(delta_path)
                    name, buildFrom, buildTo = util.parse_delta_package_name(delta_path)
                    delta.buildFrom = buildFrom
                    md.package.deltaPackages.append(delta)

            self.packages.append(md.package)

    def add_component(self, path):
        comp = component.Component()
        #try:
        comp.read(path)
        self.components.append(comp)
        #except:
        #    raise Error(_('Component in %s is corrupt') % path)
            #ctx.ui.error(str(Error(*errs)))

    def add_distro(self, path):
        distro = component.Distribution()
        #try:
        distro.read(path)
        self.distribution = distro
        #except:
        #    raise Error(_('Distribution in %s is corrupt') % path)
            #ctx.ui.error(str(Error(*errs)))

    def add_spec(self, path, repo_uri):
        import pisi.build
        ctx.ui.info(_('Adding %s to source index') % path)
        #TODO: may use try/except to handle this
        builder = pisi.build.Builder(path)
            #ctx.ui.error(_('SpecFile in %s is corrupt, skipping...') % path)
            #ctx.ui.error(str(Error(*errs)))
        builder.fetch_component()
        sf = builder.spec
        if ctx.config.options and ctx.config.options.absolute_urls:
            sf.source.sourceURI = os.path.realpath(path)
        else:                           # create relative path by default
            sf.source.sourceURI = util.removepathprefix(repo_uri, path)
            # check component
        self.specs.append(sf)
