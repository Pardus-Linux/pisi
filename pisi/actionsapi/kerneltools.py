# -*- coding: utf-8 -*-
#
# Copyright (C) 2009-2010 TUBITAK/UEKAE
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# Please read the COPYING file.

# Standard Python Modules
import os
import re
import shutil

import gettext
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

# Pisi Modules
import pisi.context as ctx

# ActionsAPI Modules
import pisi.actionsapi
import pisi.actionsapi.get          as get
import pisi.actionsapi.autotools    as autotools
import pisi.actionsapi.pisitools    as pisitools
import pisi.actionsapi.shelltools   as shelltools


class ConfigureError(pisi.actionsapi.Error):
    def __init__(self, value=''):
        pisi.actionsapi.Error.__init__(self, value)
        self.value = value
        ctx.ui.error(value)

# Internal helpers

def __getAllSupportedFlavours():
    if os.path.exists("/etc/kernel"):
        return os.listdir("/etc/kernel")

#################
# Other helpers #
#################

def __getFlavour():
    flavour = ""
    try:
        flavour = get.srcNAME().split("kernel-")[1]
    except IndexError:
        pass

    return flavour

def __getModuleFlavour():
    for fl in [_f for _f in __getAllSupportedFlavours() if "-" in _f]:
        try:
            if fl.split("-")[1] == get.srcNAME().split("-")[1]:
                return fl
        except IndexError:
            # the package is not a module, may be a userspace application
            # needing the kernel sources/headers for only reference.
            pass

    return "kernel"

def __getSuffix():
    # Set suffix, e.g. "2.6.30_rc7-119"
    suffix = "%s-%s" % (get.srcVERSION(), get.srcRELEASE())
    if __getFlavour():
        suffix += "-%s" % __getFlavour()

    return suffix

def __getExtraVersion():
    extraversion = ""
    try:
        # if successful, this is something like:
        # .1 for 2.6.30.1
        # _rc8 for 2.6.30_rc8
        extraversion = re.split("2.[0-9].[0-9]{2}([._].*)", get.srcVERSION())[1]
    except IndexError:
        # e.g. if version == 2.6.30
        pass

    extraversion += "-%s" % get.srcRELEASE()

    # Append pae, default, rt, etc. to the extraversion if available
    if __getFlavour():
        extraversion += "-%s" % __getFlavour()

    return extraversion

#######################
# Configuration stuff #
#######################

def getKernelVersion(flavour=None):
    # Returns the KVER information to use with external module compilation
    # This is something like 2.6.30_rc7-119 which will be appended to /lib/modules.
    # if flavour==None, it will return the KVER in the /etc/kernel/kernel file else,
    # /etc/kernel/<flavour>.
    # If it fails, it will return the running kernel version.

    # Try to detect module flavour
    if not flavour:
        flavour = __getModuleFlavour()

    kverfile = os.path.join("/etc/kernel", flavour)

    if os.path.exists(kverfile):
        return open(kverfile, "r").read().strip()
    else:
        # Fail
        raise ConfigureError(_("Can't find kernel version information file %s.") % kverfile)

def configure():

    # I don't know what for but let's clean *.orig files
    shelltools.system("find . -name \"*.orig\" | xargs rm -f")

    # Set EXTRAVERSION
    pisitools.dosed("Makefile", "EXTRAVERSION =.*", "EXTRAVERSION = %s" % __getExtraVersion())

    # Configure the kernel
    configtype = os.getenv("KCONFIG")
    if configtype:
        autotools.make(configtype)
    else:
        autotools.make("oldconfig")

def updateKConfig():
    # Call this to set newly added symbols to their defaults after sedding some KConfig
    # variables.

    # Grr ugly but no solution.
    shelltools.system('yes "" | make oldconfig')


###################################
# Building and installation stuff #
###################################

def dumpVersion():
    # Writes the specific kernel version into /etc/kernel
    destination = os.path.join(get.installDIR(), "etc/kernel/")
    if not os.path.exists(destination):
        os.makedirs(destination)

    open(os.path.join(destination, get.srcNAME()), "w").write(__getSuffix())

def build(debugSymbols=False):
    extra_config = []
    if debugSymbols:
        # Enable debugging symbols (-g -gdwarf2)
        extra_config.append("CONFIG_DEBUG_INFO=y")

    autotools.make("%s" % " ".join(extra_config))

def install(installFirmwares=True):
    suffix = __getSuffix()

    # Check if loadable module support is available or not before doing module specific tasks
    if re.search("CONFIG_MODULES=y", open(".config", "r").read().strip()):

        # Install the modules into /lib/modules
        autotools.rawInstall("INSTALL_MOD_PATH=%s/" % get.installDIR(),
                             "modules_install")

        # Install Module.symvers and System.map
        pisitools.insinto("/lib/modules/%s/" % suffix, "System.map")
        pisitools.insinto("/lib/modules/%s/" % suffix, "Module.symvers")

        # Remove wrong symlinks
        pisitools.remove("/lib/modules/%s/source" % suffix)
        pisitools.remove("/lib/modules/%s/build" % suffix)

    # Install kernel image
    pisitools.insinto("/boot/", "arch/x86/boot/bzImage", "kernel-%s" % suffix)

    if not installFirmwares:
        # For use with PAE e.g.
        shelltools.system("rm -rf %s/lib/firmware" % get.installDIR())


def installHeaders(extra=[]):
    """ Install the files needed to build out-of-tree kernel modules. """

    pruned = ["include", "scripts"]
    wanted = ["Makefile*", "Kconfig*", "Kbuild*", "*.sh", "*.pl", "*.lds"]

    suffix = __getSuffix()
    headersDirectoryName = "usr/src/linux-headers-%s" % suffix

    # Get the destination directory for header installation
    destination = os.path.join(get.installDIR(), headersDirectoryName)
    shelltools.makedirs(destination)

    # First create the skel
    find_cmd = "find . -path %s -prune -o -type f \( -name %s \) -print" % \
                (
                    " -prune -o -path ".join(["'./%s/*'" % l for l in pruned]),
                    " -o -name ".join(["'%s'" % k for k in wanted])
                ) + " | cpio -pVd --preserve-modification-time %s" % destination

    shelltools.system(find_cmd)

    # Install additional headers passed by actions.py
    for d in extra:
        shelltools.system("cp -a %s/*.h %s/%s" % (d, destination, d))

    # Install remaining headers
    shelltools.system("cp -a scripts include %s" % destination)

    # Finally copy the include directories found in arch/
    shelltools.system("(find arch -name include -type d -print | \
                        xargs -n1 -i: find : -type f) | \
                        cpio -pd --preserve-modification-time %s" % destination)

    # Copy Modules.symvers
    shutil.copy("Module.symvers", "%s/" % destination)

    # Copy .config file which will be needed by some external modules
    shutil.copy(".config", "%s/" % destination)

    # Unset CONFIG_DEBUG_INFO if it's set in the kernel configuration
    pisitools.dosed(".config", ".*CONFIG_DEBUG_INFO=.*", "# CONFIG_DEBUG_INFO is not set")

    # Settle the correct build symlink to this headers
    pisitools.dosym("/%s" % headersDirectoryName, "/lib/modules/%s/build" % suffix)

def installLibcHeaders(excludes=[]):
    headers_tmp = os.path.join(get.installDIR(), 'tmp-headers')
    headers_dir = os.path.join(get.installDIR(), 'usr/include')

    make_cmd = "O=%s INSTALL_HDR_PATH=%s/install" % (headers_tmp, headers_tmp)

    # Cleanup temporary header directory
    shelltools.system("rm -rf %s" % headers_tmp)

    # Create directories
    shelltools.makedirs(headers_tmp)
    shelltools.makedirs(headers_dir)

    # make defconfig and install the headers
    autotools.make("%s defconfig" % make_cmd)
    autotools.rawInstall(make_cmd, "headers_install")

    oldwd = os.getcwd()

    shelltools.cd(os.path.join(headers_tmp, "install", "include"))
    shelltools.system("find . -name '.' -o -name '.*' -prune -o -print | \
                       cpio -pVd --preserve-modification-time %s" % headers_dir)

    # Remove sound/ directory which is installed by alsa-headers
    shelltools.system("rm -rf %s/sound" % headers_dir)

    # Remove possible excludes given by actions.py
    if excludes:
        shelltools.system("rm -rf %s" % " ".join(["%s/%s" % (headers_dir, exc.strip("/")) for exc in excludes]))

    shelltools.cd(oldwd)

    # FIXME: Do we really need to delete those directories below?
    """
    # remove all directories other than asm/asm-generic and linux
    # FIXME: Check this.
    for directory in shelltools.ls("%s/usr/include/" % get.installDIR()):
        if directory not in ["asm", "asm-generic", "linux"]:
            pisitools.removeDir("/usr/include/%s" % directory)
    """

    # Remove tmp directory
    shelltools.system("rm -rf %s" % headers_tmp)


def installSource():
    destination = "usr/src/linux-source-%s" %  __getSuffix()

    # Copy the whole source directory
    pisitools.dodir("/usr/src")
    shelltools.copytree("../%s/" % os.path.basename(get.curDIR()), os.path.join(get.installDIR(), destination))

    # Cleanup the installed source
    shelltools.cd(os.path.join(get.installDIR(), destination))
    autotools.make("clean")
    autotools.make("modules_prepare")
    shelltools.system("find . -path './.*' | xargs rm -rf")

    # Create the symlink
    pisitools.dosym("/%s" % destination, "/lib/modules/%s/source" % __getSuffix())

def cleanModuleFiles():
    """ Cleans module.* files generated by depmod """
    # Remove modules.* files, they will be autogenerated during pakhandler.
    # Don't remove modules.order generated by kbuild for ordering the modules
    # according to the link order.
    shelltools.system("find %s/lib/modules/%s -name 'modules.*' \
                       -not -name 'modules.order' -exec rm -f '{}' \;" % (get.installDIR(), __getSuffix()))

def mkinitramfs():
    """ Create and install the initramfs image into the package. This will hopefully be done on user's system. """
    shelltools.system("/sbin/mkinitramfs kernel=%s --full --root-dir=%s --output=%s/boot" % (__getSuffix(), get.installDIR(), get.installDIR()))
