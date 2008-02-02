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

"""package abstraction methods to add/remove files, extract control files"""

import os.path

import gettext
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

import pisi
import pisi.context as ctx
import pisi.archive as archive
import pisi.uri
import pisi.metadata
import pisi.files
import pisi.util as util
import fetcher

class Error(pisi.Error):
    pass


class Package:
    """PiSi Package Class provides access to a pisi package (.pisi
    file)."""
    def __init__(self, packagefn, mode='r'):
        self.filepath = packagefn
        url = pisi.uri.URI(packagefn)

        if url.is_remote_file():
            self.fetch_remote_file(url)

        self.impl = archive.ArchiveZip(self.filepath, 'zip', mode)

    def fetch_remote_file(self, url):
        dest = ctx.config.packages_dir()
        self.filepath = os.path.join(dest, url.filename())

        if not os.path.exists(self.filepath):
            try:
                fetcher.fetch_url(url, dest, ctx.ui.Progress)
            except pisi.fetcher.FetchError:
                # Bug 3465
                if ctx.get_option('reinstall'):
                    raise Error(_("There was a problem while fetching '%s'.\nThe package "
                    "may have been upgraded. Please try to upgrade the package.") % url);
                raise
        else:
            ctx.ui.info(_('%s [cached]') % url.filename())

    def add_to_package(self, fn, an=None):
        """Add a file or directory to package"""
        self.impl.add_to_archive(fn, an)

    def close(self):
        """Close the package archive"""
        self.impl.close()

    def extract(self, outdir):
        """Extract entire package contents to directory"""
        self.extract_dir('', outdir)         # means package root

    def extract_files(self, paths, outdir):
        """Extract paths to outdir"""
        self.impl.unpack_files(paths, outdir)

    def extract_file(self, path, outdir):
        """Extract file with path to outdir"""
        self.extract_files([path], outdir)

    def extract_dir(self, dir, outdir):
        """Extract directory recursively, this function
        copies the directory archiveroot/dir to outdir"""
        self.impl.unpack_dir(dir, outdir)

    def extract_install(self, outdir):
        if self.impl.has_file(ctx.const.install_tar_lzma):
            self.extract_file(ctx.const.install_tar_lzma, ctx.config.tmp_dir())
            tar = archive.ArchiveTar(os.path.join(ctx.config.tmp_dir(), ctx.const.install_tar_lzma), 'tarlzma', False, False)
            tar.unpack_dir(outdir)
        else:
            self.extract_dir_flat('install', outdir)

    def extract_dir_flat(self, dir, outdir):
        """Extract directory recursively, this function
        unpacks the *contents* of directory archiveroot/dir inside outdir
        this is the function used by the installer"""
        self.impl.unpack_dir_flat(dir, outdir)

    def extract_to(self, outdir, clean_dir = False):
        """Extracts contents of the archive to outdir. Before extracting if clean_dir
        is set, outdir is deleted with its contents"""
        self.impl.unpack(outdir, clean_dir)

    def extract_pisi_files(self, outdir):
        """Extract PiSi control files: metadata.xml, files.xml,
        action scripts, etc."""
        self.extract_files([ctx.const.metadata_xml, ctx.const.files_xml], outdir)
        self.extract_dir('config', outdir)

    def get_metadata(self):
        """reads metadata.xml from the PiSi package and returns MetaData object"""
        md = pisi.metadata.MetaData()
        md.parse(self.impl.read_file(ctx.const.metadata_xml))
        return md

    def get_files(self):
        """reads files.xml from the PiSi package and returns Files object"""
        files = pisi.files.Files()
        files.parse(self.impl.read_file(ctx.const.files_xml))
        return files

    def read(self, outdir = None):
        if not outdir:
            outdir = ctx.config.tmp_dir()

        # extract control files
        self.extract_pisi_files(outdir)

        self.metadata = pisi.metadata.MetaData()
        self.metadata.read( os.path.join(outdir, ctx.const.metadata_xml) )
        errs = self.metadata.errors()
        if errs:
            util.print_errors(errs)
            raise Error, _("MetaData format wrong")

        self.files = pisi.files.Files()
        self.files.read( os.path.join(outdir, ctx.const.files_xml) )
        if self.files.errors():
            raise Error, _("Invalid %s") % ctx.const.files_xml

    def pkg_dir(self):
        packageDir = self.metadata.package.name + '-' \
                     + self.metadata.package.version + '-' \
                     + self.metadata.package.release

        return os.path.join( ctx.config.lib_dir(), 'package', packageDir)

    def comar_dir(self):
        return os.path.join(self.pkg_dir(), ctx.const.comar_dir)
