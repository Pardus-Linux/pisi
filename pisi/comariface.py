# -*- coding: utf-8 -*-
#
# Copyright (C) 2005-2006, TUBITAK/UEKAE
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# Please read the COPYING file.
#

import os
import time
import select

import gettext
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

import pisi
import pisi.context as ctx

class Error(pisi.Error):
    pass

try:
    import comar
except ImportError:
    raise Error(_("comar package is not fully installed"))

def get_comar():
    """Connect to the comar daemon and return the handle"""

    sockname = "/var/run/comar.socket"
    # YALI starts comar chrooted in the install target, but uses PiSi outside of
    # the chroot environment, so PiSi needs to use a different socket path to be
    # able to connect true comar (usually /mnt/target/var/run/comar.socket).
    if ctx.comar_sockname:
        sockname = ctx.comar_sockname

    # This function is sometimes called when comar has recently started
    # or restarting after an update. So we give comar a chance to become
    # active in a reasonable time.
    timeout = 7
    while timeout > 0:
        try:
            com = comar.Link(sockname)
            return com
        except comar.CannotConnect:
            pass
        time.sleep(0.2)
        timeout -= 0.2
    raise Error(_("cannot connect to comar"))

def wait_for_result(com, package_name=None):
    multiple = False
    while True:
        try:
            reply = com.read_cmd()
        except select.error:
            if ctx.keyboard_interrupt_pending():
                return
            raise
        except comar.LinkClosed:
            # Comar postInstall does a "service comar restart" which cuts
            # our precious communication link, so we waitsss
            if package_name == "comar":
                try:
                    get_comar()
                except Error:
                    raise Error, _("Could not restart comar")
                return
            else:
                if ctx.keyboard_interrupt_pending():
                    return
                raise Error, _("connection with comar unexpectedly closed")

        cmd = reply[0]
        if cmd == com.RESULT and not multiple:
            return
        elif cmd == com.NONE and not multiple:
            # no post/pre function, that is ok
            return
        elif cmd == com.RESULT_START:
            multiple = True
        elif cmd == com.RESULT_END:
            return
        elif cmd == com.FAIL:
            raise Error, _("Configuration error: %s") % reply[2]
        elif cmd == com.ERROR:
            raise Error, _("Script error: %s") % reply[2]
        elif cmd == com.DENIED:
            raise Error, _("comar denied our access")

def post_install(package_name, provided_scripts, scriptpath, metapath, filepath):
    """Do package's post install operations"""

    ctx.ui.info(_("Configuring %s package") % package_name)
    self_post = False
    com = get_comar()

    for script in provided_scripts:
        ctx.ui.debug(_("Registering %s comar script") % script.om)
        if script.om == "System.Package":
            self_post = True
        com.register(script.om, package_name, os.path.join(scriptpath, script.script))
        wait_for_result(com)

    ctx.ui.debug(_("Calling post install handlers"))
    com.call("System.PackageHandler.setupPackage", [ "metapath", metapath, "filepath", filepath ])
    wait_for_result(com)

    if self_post:
        ctx.ui.debug(_("Running package's post install script"))
        com.call_package("System.Package.postInstall", package_name)
        wait_for_result(com, package_name)

def pre_remove(package_name, metapath, filepath):
    """Do package's pre removal operations"""

    ctx.ui.info(_("Configuring %s package for removal") % package_name)
    com = get_comar()

    ctx.ui.debug(_("Running package's pre remove script"))
    com.call_package("System.Package.preRemove", package_name)
    wait_for_result(com)

    ctx.ui.debug(_("Calling pre remove handlers"))
    com.call("System.PackageHandler.cleanupPackage", [ "metapath", metapath, "filepath", filepath ])
    wait_for_result(com)

    ctx.ui.debug(_("Unregistering comar scripts"))
    com.remove(package_name)
    wait_for_result(com)
