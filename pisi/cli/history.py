# -*- coding:utf-8 -*-
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

import os
import sys
import optparse

import gettext
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

import pisi
import pisi.api
import pisi.db
import pisi.context as ctx
import pisi.cli.command as command

# Operation names for translation
opttrans = {"upgrade":_("upgrade"),"remove":_("remove"),"emerge":_("emerge"), "install":_("install"), "snapshot":_("snapshot"), "takeback":_("takeback"), "repoupdate":_("repository update")}

class History(command.PackageOp):
    __doc__ = _("""History of pisi operations

Usage: history

Lists previous operations.""")

    __metaclass__ = command.autocommand

    def __init__(self, args=None):
        super(History, self).__init__(args)
        self.historydb = pisi.db.historydb.HistoryDB()

    name = ("history", "hs")

    def options(self):

        group = optparse.OptionGroup(self.parser, _("history options"))
        self.add_options(group)
        self.parser.add_option_group(group)

    def add_options(self, group):
        group.add_option("-l", "--last", action="store", type="int", default=0,
                         help=_("Output only the last n operations"))
        group.add_option("-s", "--snapshot", action="store_true", default=False,
                         help=_("Take snapshot of the current system"))
        group.add_option("-t", "--takeback", action="store", type="int", default=-1,
                         help=_("Takeback to the state after the given operation finished"))

    def take_snapshot(self):
        pisi.api.snapshot()

    def takeback(self, operation):
        pisi.api.takeback(operation)

    def print_history(self):
        for operation in self.historydb.get_last(ctx.get_option('last')):
            print _("Operation #%d: %s") % (operation.no, opttrans[operation.type])
            print _("Date: %s %s") % (operation.date, operation.time)
            print

            if operation.type == "snapshot":
                print _("    * There are %d packages in this snapshot.") % len(operation.packages)
            elif operation.type == "repoupdate":
                for repo in operation.repos:
                    print "    *",  repo
            else:
                for pkg in operation.packages:
                    print "    *",  pkg
            print

    def redirect_output(self):
        if os.isatty(sys.stdout.fileno()):
            output = os.popen("less","w")
            sys.stdout =  sys.stderr = output

    def run(self):
        self.init(database = False, write = False)
        ctx.set_option('ignore_build_no', True)
        if ctx.get_option('snapshot'):
            self.take_snapshot()
            return
        elif ctx.get_option('takeback'):
            opno = ctx.get_option('takeback')
            if opno != -1:
                self.takeback(opno)
                return

        self.redirect_output()
        self.print_history()
