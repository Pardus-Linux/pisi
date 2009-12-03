# -*- coding: utf-8 -*-

# Copyright (C) 2005 - 2007, TUBITAK/UEKAE
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# Please read the COPYING file.
#

"""Yet another Pisi module for fetching files from various sources. Of
course, this is not limited to just fetching source files. We fetch
all kinds of things: source tarballs, index files, packages, and God
knows what."""

# python standard library modules
import os
import sys
import time
import base64
import shutil

import gettext
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

# pisi modules
import pisi
import pisi.util as util
import pisi.context as ctx
import pisi.uri


class FetchError(pisi.Error):
    pass


class UIHandler:
    def __init__(self, progress):
        self.filename        = None
        self.url             = None
        self.basename        = None
        self.downloaded_size = 0
        self.percent         = None
        self.rate            = 0.0
        self.eta             = '--:--:--'
        self.symbol          = '--/-'
        self.last_updated    = 0
        self.exist_size      = 0

    def start(self, archive, url, basename, total_size, text):
        if os.path.exists(archive):
            self.exist_size = os.path.getsize(archive)
        self.filename   = basename
        self.url        = url
        self.basename   = basename
        self.total_size = total_size or 0
        self.text       = text

        self.now    = lambda: time.time()
        self.t_diff = lambda: self.now() - self.s_time

        self.s_time = self.now()

    def update(self, size):
        self.size = size

        if self.total_size:
            self.percent = (size * 100.0) / self.total_size
        else:
            self.percent = 0

        if int(self.now()) != int(self.last_updated) and size > 0:
            self.rate, self.symbol = util.human_readable_rate((size - self.exist_size) / (self.now() - self.s_time))
            if self.total_size:
                self.eta  = '%02d:%02d:%02d' %\
                    tuple([i for i in time.gmtime((self.t_diff() * (100 - self.percent)) / self.percent)[3:6]])

        self._update_ui()

    def end(self, read):
        pass

    def _update_ui(self):
        ctx.ui.display_progress(operation       = "fetching",
                                percent         = self.percent,
                                filename        = self.filename,
                                total_size      = self.total_size or self.size,
                                downloaded_size = self.size,
                                rate            = self.rate,
                                eta             = self.eta,
                                symbol          = self.symbol)

        self.last_updated = self.now()


class Fetcher:
    """Fetcher can fetch a file from various sources using various
    protocols."""
    def __init__(self, url, destdir):
        if not isinstance(url, pisi.uri.URI):
            url = pisi.uri.URI(url)

        if ctx.config.get_option("authinfo"):
            url.set_auth_info(ctx.config.get_option("authinfo"))

        self.url      = url
        self.destdir  = destdir
        self.archive_file = os.path.join(self.destdir, self.url.filename())
        self.partial_file = self.archive_file + '.part'
        self.progress = None

        util.check_dir(self.destdir)


    def fetch (self):
        """Return value: Fetched file's full path.."""

        # import urlgrabber module
        try:
            import urlgrabber
        except ImportError:
            raise FetchError(_('Urlgrabber needs to be installed to run this command'))

        if not self.url.filename():
            raise FetchError(_('Filename error'))

        if not os.access(self.destdir, os.W_OK):
            raise FetchError(_('Access denied to write to destination directory: "%s"') % (self.destdir))

        if os.path.exists(self.archive_file) and not os.access(self.archive_file, os.W_OK):
            raise FetchError(_('Access denied to destination file: "%s"') % (self.archive_file))

        try:
            urlgrabber.urlgrab(self.url.get_uri(),
                           self.partial_file,
                           progress_obj     = UIHandler(self.progress),
                           http_headers     = self._get_http_headers(),
                           close_connection = 1,
                           keepalive        = 0,
                           ftp_headers      = self._get_ftp_headers(),
                           proxies          = self._get_proxies(),
                           throttle         = self._get_bandwith_limit(),
                           reget            = self._test_range_support(),
                           user_agent       = 'PiSi Fetcher/' + pisi.__version__)
        except urlgrabber.grabber.URLGrabError, e:
            raise FetchError(_('Could not fetch destination file "%s": %s') % (self.archive_file, e))

        if os.stat(self.partial_file).st_size == 0:
            os.remove(self.partial_file)
            raise FetchError(_('A problem occurred. Please check the archive address and/or permissions again.'))

        shutil.move(self.partial_file, self.archive_file)

        return self.archive_file

    def _get_http_headers(self):
        headers = []
        if self.url.auth_info() and (self.url.scheme() == "http" or self.url.scheme() == "https"):
            enc = base64.encodestring('%s:%s' % self.url.auth_info())
            headers.append(('Authorization', 'Basic %s' % enc),)
        return tuple(headers)

    def _get_ftp_headers(self):
        headers = []
        if self.url.auth_info() and self.url.scheme() == "ftp":
            enc = base64.encodestring('%s:%s' % self.url.auth_info())
            headers.append(('Authorization', 'Basic %s' % enc),)
        return tuple(headers)

    def _get_proxies(self):
        proxies = {}
        
        if ctx.config.values.general.http_proxy and self.url.scheme() == "http":
            proxies[pisi.uri.URI(ctx.config.values.general.http_proxy).scheme()] = ctx.config.values.general.http_proxy

        if ctx.config.values.general.https_proxy and self.url.scheme() == "https":
            proxies[pisi.uri.URI(ctx.config.values.general.https_proxy).scheme()] = ctx.config.values.general.https_proxy

        if ctx.config.values.general.ftp_proxy and self.url.scheme() == "ftp":
            proxies[pisi.uri.URI(ctx.config.values.general.ftp_proxy).scheme()] = ctx.config.values.general.ftp_proxy

        if self.url.scheme() in proxies:
            ctx.ui.info(_("Proxy configuration has been found for '%s' protocol") % self.url.scheme())

        return proxies

    def _get_bandwith_limit(self):
        bandwidth_limit = ctx.config.options.bandwidth_limit or ctx.config.values.general.bandwidth_limit
        if bandwidth_limit and bandwidth_limit != "0":
            ctx.ui.warning(_("Bandwidth usage is limited to %s KB/s") % bandwidth_limit)
            return 1024 * int(bandwidth_limit)
        else:
            return 0

    def _test_range_support(self):
        if not os.path.exists(self.partial_file):
            return None

        import urllib2
        file_obj = urllib2.urlopen(urllib2.Request(self.url.get_uri()))
        headers = file_obj.info()
        file_obj.close()
        if headers.has_key('Content-Length'):
            return 'check_timestamp'
        else:
            ctx.ui.debug(_("Server doesn't support partial downloads. Previously downloaded part of the file will be over-written."))
            os.remove(self.partial_file)
            return None


# helper function
def fetch_url(url, destdir, progress=None):
    fetch = Fetcher(url, destdir)
    fetch.progress = progress
    fetch.fetch()
