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

# PiSi Configuration File module, obviously, is used to read from the
# configuration file. Module also defines default values for
# configuration parameters.
#
# Configuration file is located in /etc/pisi/pisi.conf by default,
# having an INI like format like below.
#
#[general]
#destinationdirectory = /
#autoclean = False
#
#[build]
#host = i686-pc-linux-gnu
#generateDebug = False
#jobs = "-j1"
#CFLAGS= -mtune=i686 -march=i686 -O2 -pipe -fomit-frame-pointer
#CXXFLAGS= -mtune=i686 -march=i686 -O2 -pipe -fomit-frame-pointer
#LDFLAGS=
#buildno=True     # necessary for generating build nos
#buildhelper = None / ccache / icecream
#compressionlevel = 7
#fallback = "ftp://ftp.pardus.org.tr/pub/pisi/source"
#
#[directories]
#lib_dir = /var/lib/pisi
#db_dir = /var/db/pisi
#archives_dir = /var/cache/pisi/archives
#packages_dir = /var/cache/pisi/packages
#compiled_packages_dir = "/var/cache/pisi/packages"
#index_dir = /var/cache/pisi/index
#tmp_dir = /var/pisi
#kde_dir = /usr/kde/3.5
#qt_dir = /usr/qt/3

import os
import re
import StringIO
import ConfigParser

import gettext
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

import pisi

class Error(pisi.Error):
    pass

class GeneralDefaults:
    """Default values for [general] section"""
    destinationdirectory = "/"
    autoclean = False
    distribution = "Pardus"
    distribution_release = "2007"
    http_proxy = os.getenv("HTTP_PROXY") or None
    https_proxy = os.getenv("HTTPS_PROXY") or None
    ftp_proxy = os.getenv("FTP_PROXY") or None
    package_cache = False
    package_cache_limit = 0

class BuildDefaults:
    """Default values for [build] section"""
    host = "i686-pc-linux-gnu"
    jobs = "-j1"
    generateDebug = False
    cflags = "-mtune=i686 -O2 -pipe -fomit-frame-pointer"
    cxxflags = "-mtune=i686 -O2 -pipe -fomit-frame-pointer"
    ldflags = ""
    buildno = False
    buildhelper = None
    compressionlevel = 7
    fallback = "ftp://ftp.pardus.org.tr/pub/pisi/source"

class DirectoriesDefaults:
    "Default values for [directories] section"
    lib_dir = "/var/lib/pisi"
    log_dir = "/var/log"
    db_dir = "/var/db/pisi"
    archives_dir = "/var/cache/pisi/archives"
    packages_dir = "/var/cache/pisi/packages"
    compiled_packages_dir = "/var/cache/pisi/packages"
    index_dir = "/var/lib/pisi/index"
    tmp_dir =  "/var/pisi"
    kde_dir = "/usr/kde/3.5"
    qt_dir = "/usr/qt/3"

class ConfigurationSection(object):
    """ConfigurationSection class defines a section in the configuration
    file, using defaults (above) as a fallback."""
    def __init__(self, section, items=[]):
        self.items = items

        if section == "general":
            self.defaults = GeneralDefaults
        elif section == "build":
            self.defaults = BuildDefaults
        elif section == "directories":
            self.defaults = DirectoriesDefaults
        else:
            e = _("No section by name '%s'") % section
            raise Error, e

        self.section = section

    def __getattr__(self, attr):

        # first search for attribute in the items provided in the
        # configuration file.
        if self.items:
            for item in self.items:
                if item[0] == attr:
                    # all values are returned as string types by ConfigParser.
                    # evaluate "True" or "False" strings to boolean.
                    if item[1] in ["True", "False", "None"]:
                        return eval(item[1])
                    else:
                        return item[1]

        # then fall back to defaults
        if hasattr(self.defaults, attr):
            return getattr(self.defaults, attr)

        return ""

    # We'll need to access configuration keys by their names as a
    # string. Like; ["default"]...
    def __getitem__(self, key):
        return self.__getattr__(key)

class ConfigurationFile(object):
    """Parse and get configuration values from the configuration file"""
    def __init__(self, filePath):
        self.parser = ConfigParser.ConfigParser()
        self.filePath = filePath

        self.parser.read(self.filePath)

        try:
            generalitems = self.parser.items("general")
        except ConfigParser.NoSectionError:
            generalitems = []
        self.general = ConfigurationSection("general", generalitems)

        try:
            builditems = self.parser.items("build")
        except ConfigParser.NoSectionError:
            builditems = []
        self.build = ConfigurationSection("build", builditems)

        try:
            dirsitems = self.parser.items("directories")
        except ConfigParser.NoSectionError:
            dirsitems = []
        self.dirs = ConfigurationSection("directories", dirsitems)

    # get, set and write_config methods added for manipulation of pisi.conf file from Comar to solve bug #5668.
    # Current ConfigParser does not keep the comments and white spaces, which we do not want for pisi.conf. There
    # are patches floating in the python sourceforge to add this feature. The write_config code is from python
    # sourceforge tracker id: #1410680, modified a little to make it turn into a function.

    def get(self, section, option):
        try:
            return self.parser.get(section, option)
        except ConfigParser.NoOptionError:
            return None

    def set(self, section, option, value):
        self.parser.set(section, option, value)

    def write_config(self, add_missing=True):
        sections = {}
        current = StringIO.StringIO()
        replacement = [current]
        sect = None
        opt = None
        written = []
        optcre = re.compile(
            r'(?P<option>[^:=\s][^:=]*)'
            r'(?P<vi>[:=])'
            r'(?P<padding>\s*)'
            r'(?P<value>.*)$'
            )
        
        fp = open(self.filePath, "r+")
        # Default to " = " to match write(), but use the most recent
        # separator found if the file has any options.
        padded_vi = " = "
        while True:
            line = fp.readline()
            if not line:
                break
            # Comment or blank line?
            if line.strip() == '' or line[0] in '#;' or \
               (line.split(None, 1)[0].lower() == 'rem' and \
                line[0] in "rR"):
                current.write(line)
                continue
            # Continuation line?
            if line[0].isspace() and sect is not None and opt:
                if ';' in line:
                    # ';' is a comment delimiter only if it follows
                    # a spacing character
                    pos = line.find(';')
                    if line[pos-1].isspace():
                        comment = line[pos-1:]
                        # Get rid of the newline, and put in the comment.
                        current.seek(-1, 1)
                        current.write(comment + "\n")
                continue
            # A section header or option header?
            else:
                # Is it a section header?
                mo = self.parser.SECTCRE.match(line)
                if mo:
                    # Remember the most recent section with this name,
                    # so that any missing options can be added to it.
                    if sect:
                        sections[sect] = current
                    sect = mo.group('header')
                    current = StringIO.StringIO()
                    replacement.append(current)
                    sects = self.parser.sections()
                    sects.append(ConfigParser.DEFAULTSECT)
                    if sect in sects:
                        current.write(line)
                    # So sections can't start with a continuation line:
                    opt = None
                # An option line?
                else:
                    mo = optcre.match(line)
                    if mo:
                        padded_opt, vi, value = mo.group('option', 'vi',
                                                         'value')
                        padded_vi = ''.join(mo.group('vi', 'padding'))
                        comment = ""
                        if vi in ('=', ':') and ';' in value:
                            # ';' is a comment delimiter only if it follows
                            # a spacing character
                            pos = value.find(';')
                            if value[pos-1].isspace():
                                comment = value[pos-1:]
                        # Keep track of what we rstrip to preserve formatting
                        opt = padded_opt.rstrip().lower()
                        padded_vi = padded_opt[len(opt):] + padded_vi
                        if self.parser.has_option(sect, opt):
                            value = self.parser.get(sect, opt)
                            # Fix continuations.
                            value = value.replace("\n", "\n\t")
                            current.write("%s%s%s%s\n" % (opt, padded_vi,
                                                          value, comment))
                            written.append((sect, opt))
        if sect:
            sections[sect] = current
        if add_missing:
            # Add any new sections.
            sects = self.parser.sections()
            if len(self.parser._defaults) > 0:
                sects.append(ConfigParser.DEFAULTSECT)
            sects.sort()
            for sect in sects:
                if sect == ConfigParser.DEFAULTSECT:
                    opts = self.parser._defaults.keys()
                else:
                    # Must use _section here to avoid defaults.
                    opts = self.parser._sections[sect].keys()
                opts.sort()
                if sect in sections:
                    output = sections[sect] or current
                else:
                    output = current
                    if len(written) > 0:
                    	output.write("\n")
                    output.write("[%s]\n" % (sect,))
                    sections[sect] = None
                for opt in opts:
                    if opt != "__name__" and not (sect, opt) in written:
                        value = self.parser.get(sect, opt)
                        # Fix continuations.
                        value = value.replace("\n", "\n\t")
                        output.write("%s%s%s\n" % (opt, padded_vi, value))
                        written.append((sect, opt))
        # Copy across the new file.
        fp.seek(0)
        fp.truncate()
        for sect in replacement:
            if sect is not None:
                fp.write(sect.getvalue())

        fp.close()
        
