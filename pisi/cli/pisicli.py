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

import sys
import optparse

import gettext
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

import pisi
import pisi.cli
import pisi.cli.command as command
import pisi.cli.addrepo
import pisi.cli.build
import pisi.cli.check
import pisi.cli.clean
import pisi.cli.configurepending
import pisi.cli.deletecache
import pisi.cli.delta
import pisi.cli.emerge
import pisi.cli.fetch
import pisi.cli.graph
import pisi.cli.index
import pisi.cli.info
import pisi.cli.install
import pisi.cli.history
import pisi.cli.listnewest
import pisi.cli.listavailable
import pisi.cli.listcomponents
import pisi.cli.listinstalled
import pisi.cli.listpending
import pisi.cli.listrepo
import pisi.cli.listsources
import pisi.cli.listupgrades
import pisi.cli.rebuilddb
import pisi.cli.remove
import pisi.cli.removerepo
import pisi.cli.searchfile
import pisi.cli.search
import pisi.cli.updaterepo
import pisi.cli.upgrade

#FIXME: why does this has to be imported last
import pisi.cli.help

class ParserError(pisi.Exception):
    pass

class PreParser(optparse.OptionParser):
    """consumes any options, and finds arguments from command line"""

    def __init__(self, version):
        optparse.OptionParser.__init__(self, usage=pisi.cli.help.usage_text, version=version)

    def error(self, msg):
        raise ParserError, msg

    def parse_args(self, args=None):
        self.opts = []
        self.rargs = self._get_args(args)
        self._process_args()
        return (self.opts, self.args)

    def _process_args(self):
        args = []
        rargs = self.rargs
        if not self.allow_interspersed_args:
            first_arg = False
        while rargs:
            arg = rargs[0]
            def option():
                if not self.allow_interspersed_args and first_arg:
                    self.error(_('Options must precede non-option arguments'))
                arg = rargs[0]
                if arg.startswith('--'):
                    self.opts.append(arg[2:])
                else:
                    self.opts.append(arg[1:])
                del rargs[0]
                return
            # We handle bare "--" explicitly, and bare "-" is handled by the
            # standard arg handler since the short arg case ensures that the
            # len of the opt string is greater than 1.
            if arg == "--":
                del rargs[0]
                break
            elif arg[0:2] == "--":
                # process a single long option (possibly with value(s))
                option()
            elif arg[:1] == "-" and len(arg) > 1:
                # process a cluster of short options (possibly with
                # value(s) for the last one only)
                option()
            else: # then it must be an argument
                args.append(arg)
                del rargs[0]
        self.args = args


class PisiCLI(object):

    def __init__(self, orig_args=None):
        # first construct a parser for common options
        # this is really dummy
        self.parser = PreParser(version="%prog " + pisi.__version__)
        try:
            opts, args = self.parser.parse_args(args=orig_args)
            if len(args)==0: # more explicit than using IndexError
                if 'version' in opts:
                    self.parser.print_version()
                    sys.exit(0)
                elif 'help' in opts or 'h' in opts:
                    self.die()
                raise pisi.cli.Error(_('No command given'))
            cmd_name = args[0]
        except ParserError:
            raise pisi.cli.Error(_('Command line parsing error'))

        self.command = command.Command.get_command(cmd_name, args=orig_args)
        if not self.command:
            raise pisi.cli.Error(_("Unrecognized command: %s") % cmd_name)

    def die(self):
        pisi.cli.printu('\n' + self.parser.format_help())
        sys.exit(1)

    def run_command(self):
        self.command.run()
