#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (C) 2005, 2006 TUBITAK/UEKAE
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# Please read the COPYING file.

import os
import sys
import glob
import string
import shutil
import pisi.util as util
from pisi.version import Version

def findUnneededFiles(listdir):
    dict = {}
    for f in listdir:
        try:
            name, version = util.parse_package_name(f)
            if dict.has_key(name):
                if Version(dict[name]) < Version(version):
                    dict[name] = version
            else:
                if version:
                    dict[name] = version

        except:
            pass

    for f in dict:
        listdir.remove("%s-%s" % (f, dict[f]))

    return listdir

def doit(root, listdir, clean, suffix = ""):
    for f in listdir:
        target = os.path.join(root, "%s%s" % (f, suffix))
        if os.path.exists(target):
            print "%s%s" % (f, suffix)
            if clean == True:
                try:
                    if os.path.isdir(target):
                        shutil.rmtree(target)
                    else:
                        os.remove(target)
                except OSError,e :
                    usage("Permission denied: %s" % e)


def cleanPisis(clean, root = '/var/cache/pisi/packages'):
    # pisi packages
    list = map(lambda x: os.path.basename(x).split(".pisi")[0], glob.glob("%s/*.pisi" % root))
    list.sort()
    l = findUnneededFiles(list)
    doit(root, l, clean, ".pisi")

def cleanBuilds(clean, root = '/var/pisi'):
    # Build remnant
    list = []
    for f in os.listdir(root):
        if os.path.isdir(os.path.join(root, f)):
             list.append(f)

    l = findUnneededFiles(list)
    doit(root, l, clean)

def usage(msg):
    print """
Error: %s

Usage:
    cleanCache --dry-run    (Shows unneeded files)
    cleanCache --clean      (Removes unneeded files)
    """ % msg

    sys.exit(1)

if __name__ == "__main__":
    try:
        sys.argv[1]
    except IndexError:
        usage("Unsufficient arguments...")

    if "--dry-run" in sys.argv:
        clean = False
    elif "--clean" in sys.argv:
        clean = True
    else:
        usage("No command given...")
        sys.exit(0)

    if "builds" in sys.argv:
        cleanBuilds(clean)

    else:
        cleanPisis(clean)

