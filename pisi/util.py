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

"""misc. utility functions, including process and file utils"""

# standard python modules
import os
import re
import sys
import sha
import shutil
import string
import statvfs
import operator
import subprocess

import gettext
__trans = gettext.translation('pisi', fallback=True)
_ = __trans.ugettext

# pisi modules
import pisi
import pisi.context as ctx

class Error(pisi.Error):
    pass

class FileError(Error):
    pass


#########################
# spec validation utility #
#########################

def print_errors(errlist):
    for err in errlist:
        ctx.ui.error(err)


#########################
# string/list/functional#
#########################

def every(pred, seq):
    return reduce(operator.and_, map(pred, seq), True)

def any(pred, seq):
    return reduce(operator.or_, map(pred, seq), False)

def unzip(seq):
    return zip(*seq)

def concat(l):
    """Concatenate a list of lists."""
    return reduce( operator.concat, l )

def strlist(l):
    """Concatenate string reps of l's elements."""
    return "".join(map(lambda x: str(x) + ' ', l))

def multisplit(str, chars):
    """Split str with any of the chars."""
    l = [str]
    for c in chars:
        l = concat(map(lambda x:x.split(c), l))
    return l

def same(l):
    """Check if all elements of a sequence are equal."""
    if len(l)==0:
        return True
    else:
        last = l.pop()
        for x in l:
            if x!=last:
                return False
        return True

def prefix(a, b):
    """Check if sequence a is a prefix of sequence b."""
    if len(a)>len(b):
        return False
    for i in range(0,len(a)):
        if a[i]!=b[i]:
            return False
    return True

def remove_prefix(a,b):
    """Remove prefix a from sequence b."""
    assert prefix(a,b)
    return b[len(a):]

def human_readable_size(size = 0):
    symbols, depth = [' B', 'KB', 'MB', 'GB'], 0

    while size > 1000 and depth < 3:
        size = float(size / 1024)
        depth += 1

    return size, symbols[depth]

def human_readable_rate(size = 0):
    x = human_readable_size(size)
    return x[0], x[1] + '/s'

##############################
# Process Releated Functions #
##############################

def run_batch(cmd):
    """Run command and report return value and output."""
    ctx.ui.info(_('Running ') + cmd, verbose=True)
    p = subprocess.Popen(cmd, shell=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    ctx.ui.debug(_('return value for "%s" is %s') % (cmd, p.returncode))
    return (p.returncode, out, err)

# you can't use the following for Popen, oops
class TeeOutFile:
    def __init__(self, file):
        self.file = file

    def write(self, str):
        self.write(str)
        ctx.ui.debug(str)

# TODO: it might be worthwhile to try to remove the
# use of ctx.stdout, and use run_batch()'s return
# values instead. but this is good enough :)
def run_logged(cmd):
    """Run command and get the return value."""
    ctx.ui.info(_('Running ') + cmd, verbose=True)
    if ctx.stdout:
        stdout = ctx.stdout
    else:
        if ctx.get_option('debug'):
            stdout = None
        else:
            stdout = subprocess.PIPE
    if ctx.stderr:
        stderr = ctx.stderr
    else:
        if ctx.get_option('debug'):
            stderr = None
        else:
            stderr = subprocess.STDOUT

    p = subprocess.Popen(cmd, shell=True, stdout=stdout, stderr=stderr)
    out, err = p.communicate()
    ctx.ui.debug(_('return value for "%s" is %s') % (cmd, p.returncode))

    return p.returncode

######################
# Terminal functions #
######################

def xterm_title(message):
    """Set message as console window title."""
    if os.environ.has_key("TERM") and sys.stderr.isatty():
        terminalType = os.environ["TERM"]
        for term in ["xterm", "Eterm", "aterm", "rxvt", "screen", "kterm", "rxvt-unicode"]:
            if terminalType.startswith(term):
                sys.stderr.write("\x1b]2;"+str(message)+"\x07")
                sys.stderr.flush()
                break

def xterm_title_reset():
    """Reset console window title."""
    if os.environ.has_key("TERM"):
        xterm_title("")

#############################
# Path Processing Functions #
#############################

def splitpath(a):
    """split path into components and return as a list
    os.path.split doesn't do what I want like removing trailing /"""
    comps = a.split(os.path.sep)
    if comps[len(comps)-1]=='':
        comps.pop()
    return comps

def makepath(comps, relative = False, sep = os.path.sep):
    """Reconstruct a path from components."""
    path = reduce(lambda x,y: x + sep + y, comps, '')
    if relative:
        return path[len(sep):]
    else:
        return path

def parentpath(a, sep = os.path.sep):
    # remove trailing '/'
    a = a.rstrip(sep)
    return a[:a.rfind(sep)]

def parenturi(a):
    return parentpath(a, '/')

# I'm not sure how necessary this is. Ahem.
def commonprefix(l):
    """an improved version of os.path.commonprefix,
    returns a list of path components"""
    common = []
    comps = map(splitpath, l)
    for i in range(0, min(len,l)):
        compi = map(lambda x: x[i], comps) # get ith slice
        if same(compi):
            common.append(compi[0])
    return common

# but this one is necessary
def subpath(a, b):
    """Find if path a is before b in the directory tree."""
    return prefix(splitpath(a), splitpath(b))

def removepathprefix(prefix, path):
    """Remove path prefix a from b, finding the pathname rooted at a."""
    comps = remove_prefix(splitpath(prefix), splitpath(path))
    if len(comps) > 0:
        return join_path(*tuple(comps))
    else:
        return ""

def absolute_path(path):
    """Determine if given path is absolute."""
    comps = splitpath(path)
    return comps[0] == ''

def join_path(a, *p):
    """Join two or more pathname components.

    Python os.path.join cannot handle '/' at the start of latter components.

    """
    path = a
    for b in p:
        b = b.lstrip('/')
        if path == '' or path.endswith('/'):
            path +=  b
        else:
            path += '/' + b
    return path

####################################
# File/Directory Related Functions #
####################################

def check_file(file, mode = os.F_OK):
    """Shorthand to check if a file exists."""
    if not os.access(file, mode):
        raise FileError("File " + file + " not found")
    return True

# FIXME: check_dir is not a good name considering it can also create the dir
def check_dir(d):
    """Make sure given directory path exists."""
    # FIXME: What is first strip doing there?
    d = d.strip().rstrip("/")
    if not os.access(d, os.F_OK):
        os.makedirs(d)

def clean_dir(path):
    """Remove all content of a directory."""
    if os.path.exists(path):
        shutil.rmtree(path)

def creation_time(file):
    """Return the creation time of the given file."""
    if check_file(file):
        import time
        st = os.stat(file)
        return time.localtime(st.st_ctime)

def dir_size(dir):
    """Calculate the size of files under a directory."""
    # It's really hard to give an approximate value for package's
    # installed size. Gettin a sum of all files' sizes if far from
    # being true. Using 'du' command (like Debian does) can be a
    # better solution :(.
    # Not really, du calculates size on disk, this is much better -- exa

    if os.path.exists(dir) and (not os.path.isdir(dir) and not os.path.islink(dir)):
        #so, this is not a directory but file..
        return os.path.getsize(dir)

    if os.path.islink(dir):
        return long(len(os.readlink(dir)))

    def sizes():
        for root, dirs, files in os.walk(dir):
            yield sum([os.path.getsize(join_path(root, name)) for name in files if not os.path.islink(join_path(root, name))])
    return sum(sizes())

def copy_file(src,dest):
    """Copy source file to the destination file."""
    check_file(src)
    check_dir(os.path.dirname(dest))
    shutil.copyfile(src, dest)

def is_ar_file(file_path):
    return open(file_path).readline().strip() == '!<arch>'

def clean_ar_timestamps(ar_file):
    """Zero all timestamps in the ar files."""
    if not is_ar_file(ar_file):
        return
    content = open(ar_file).readlines()
    fp = open(ar_file, 'w')
    for line in content:
        pos = line.rfind(chr(32) + chr(96))
        if pos > -1 and line[pos - 57:pos + 2].find(chr(47)) > -1:
             line = line[:pos - 41] + '0000000000' + line[pos - 31:]
        fp.write(line)
    fp.close()

def calculate_hash(path):
    """Return a (path, hash) tuple for given path."""
    if os.path.islink(path):
        try:
            # For symlinks, path string is hashed instead of the content
            value = sha1_data(os.readlink(path))
        except FileError:
            ctx.ui.info(_("Including external link '%s'") % path)
            value = None
    elif os.path.isdir(path):
        ctx.ui.info(_("Including directory '%s'") % path)
        value = None
    else:
        if path.endswith('.a'):
            # .a file content changes with each compile due to timestamps
            # We pad them with zeroes, thus hash will be stable
            clean_ar_timestamps(path)
        value = sha1_file(path)

    return (path, value)

def get_file_hashes(top, excludePrefix=None, removePrefix=None):
    """Yield (path, hash) tuples for given directory tree."""
    def is_included(path):
        if excludePrefix:
            temp = remove_prefix(removePrefix, path)
            if len(filter(lambda x: temp.startswith(x), excludePrefix)) > 0:
                return False
        return True

    # single file/symlink case
    if not os.path.isdir(top) or os.path.islink(top):
        if is_included(top):
            yield calculate_hash(top)
        return

    for root, dirs, files in os.walk(top):
        # Hash files and file symlinks
        for name in files:
            path = os.path.join(root, name)
            if is_included(path):
                yield calculate_hash(path)

        # Hash symlink dirs
        # os.walk doesn't enter them, we don't want to follow them either
        # but their name and hashes must be reported
        # Discussed in bug #339
        for name in dirs:
            path = os.path.join(root, name)
            if os.path.islink(path):
                if is_included(path):
                    yield calculate_hash(path)

        # Hash empty dir
        # Discussed in bug #340
        if len(files) == 0 and len(dirs) == 0:
            if is_included(root):
                yield calculate_hash(root)


def copy_dir(src, dest):
    """Copy source dir to destination dir recursively."""
    shutil.copytree(src, dest)

def check_file_hash(filename, hash):
    """Check the file's integrity with a given hash."""
    return sha1_file(filename) == hash

def sha1_file(filename):
    """Calculate sha1 hash of file."""
    # Broken links can cause problem!
    try:
        m = sha.new()
        f = file(filename, 'rb')
        while True:
            # 256 KB seems ideal for speed/memory tradeoff
            # It wont get much faster with bigger blocks, but
            # heap peak grows
            block = f.read(256 * 1024)
            if len(block) == 0:
                # end of file
                break
            m.update(block)
            # Simple trick to keep total heap even lower
            # Delete the previous block, so while next one is read
            # we wont have two allocated blocks with same size
            del block
        return m.hexdigest()
    except IOError:
        raise FileError(_("I/O Error: Cannot calculate SHA1 hash of %s") % filename)

def sha1_data(data):
    """Calculate sha1 hash of given data."""
    m = sha.new()
    m.update(data)
    return m.hexdigest()

def uncompress(patchFile, compressType="gz", targetDir=None):
    """Uncompress the file and return the new path."""
    if targetDir:
        filePath = join_path(targetDir,
                                os.path.basename(patchFile))
    else:
        filePath = os.path.basename(patchFile)
    # remove suffix from file cause its uncompressed now
    filePath = filePath.split(".%s" % compressType)[0]

    if compressType == "gz":
        import gzip
        obj = gzip.GzipFile(patchFile)
    elif compressType == "bz2":
        import bz2
        obj = bz2.BZ2File(patchFile)

    open(filePath, "w").write(obj.read())
    return filePath


def do_patch(sourceDir, patchFile, level = 0):
    """Apply given patch to the sourceDir."""
    cwd = os.getcwd()
    os.chdir(sourceDir)

    if level == None:
        level = 0

    check_file(patchFile)

    if ctx.get_option('use_quilt'):
        patchesDir = join_path(sourceDir, ctx.const.quilt_dir_suffix)
        # Make sure sourceDir/patches directory exists and if not create one!
        if not os.path.exists(patchesDir):
            os.makedirs(patchesDir)
        # Import original patch into quilt tree
        (ret, out, err) = run_batch('quilt import -p %d -P %s \"%s\"' % (level, os.path.basename(patchFile), patchFile))
        # run quilt push to apply original patch into tree
        (ret, out, err) = run_batch('quilt push')
    else:
        # run GNU patch to apply original patch into tree
        (ret, out, err) = run_batch("patch --remove-empty-files -p%d < \"%s\"" % (level, patchFile))

    if ret:
        if out is None and err is None:
            # Which means stderr and stdout directed so they are None
            raise Error(_("ERROR: patch (%s) failed") % (patchFile))
        else:
            raise Error(_("ERROR: patch (%s) failed: %s") % (patchFile, out))

    os.chdir(cwd)


def strip_directory(top, excludelist=[]):
    for root, dirs, files in os.walk(top):
        for fn in files:
            frpath = join_path(root, fn)
            drpath = join_path(os.path.dirname(top),
                               ctx.const.debug_dir_suffix,
                               remove_prefix(top, frpath))

            # Some upstream sources have buggy libtool and ltmain.sh with them,
            # which causes wrong path entries in *.la files. And these wrong path
            # entries sometimes triggers compile-time errors or linkage problems.
            # Instead of patching all these buggy sources and maintain these patches,
            # PiSi removes wrong paths...
            if frpath.endswith(".la") and not os.path.islink(frpath):
                ladata = file(frpath).read()
                new_ladata = re.sub("-L%s/\S*" % ctx.config.tmp_dir(), "", ladata)
                new_ladata = re.sub("%s/\S*/install/" % ctx.config.tmp_dir(), "/", new_ladata)
                if new_ladata != ladata:
                    file(frpath, "w").write(new_ladata)
            # real path in .pisi package
            p = '/' + removepathprefix(top, frpath)
            strip = True
            for exclude in excludelist:
                if p.startswith(exclude):
                    strip = False
                    ctx.ui.debug("%s [%s]" %(p, "NoStrip"))

            if strip:
                if strip_file(frpath, drpath):
                    ctx.ui.debug("%s [%s]" %(p, "stripped"))


def strip_file(filepath, outpath):
    """Strip an elf file from debug symbols."""
    p = os.popen("file \"%s\"" % filepath)
    o = p.read()

    def run_strip(f, flags=""):
        p = os.popen("strip %s %s" %(flags, f))
        ret = p.close()
        if ret:
            ctx.ui.warning(_("strip command failed for file '%s'!") % f)

    def save_elf_debug(f, o):
        """copy debug info into file.debug file"""
        p = os.popen("objcopy --only-keep-debug %s %s%s" % (f, o, ctx.const.debug_file_suffix))
        ret = p.close()
        if ret:
            ctx.ui.warning(_("objcopy (keep-debug) command failed for file '%s'!") % f)

        """mark binary/shared objects to use file.debug"""
        p = os.popen("objcopy --add-gnu-debuglink=%s%s %s" % (o, ctx.const.debug_file_suffix, f))
        ret = p.close()
        if ret:
            ctx.ui.warning(_("objcopy (add-debuglink) command failed for file '%s'!") % f)

    if "current ar archive" in o:
        run_strip(filepath, "-g")
        return True

    elif "SB executable" in o:
        if ctx.config.values.build.generatedebug:
            check_dir(os.path.dirname(outpath))
            save_elf_debug(filepath, outpath)
        run_strip(filepath)
        return True

    elif "SB shared object" in o:
        if ctx.config.values.build.generatedebug:
            check_dir(os.path.dirname(outpath))
            save_elf_debug(filepath, outpath)
        run_strip(filepath, "--strip-unneeded")
        # FIXME: warn for TEXTREL
        return True

    return False

def partition_freespace(directory):
    """Return free space of given directory's partition."""
    st = os.statvfs(directory)
    return st[statvfs.F_BSIZE] * st[statvfs.F_BFREE]

########################################
# Package/Repository Related Functions #
########################################

def package_name(name, version, release, build, prependSuffix=True):
    fn = name + '-' + version + '-' + release
    if build:
        fn += '-' + str(build)
    if prependSuffix:
        fn += ctx.const.package_suffix
    return fn

def is_package_name(fn, package_name = None):
    """Check if fn is a valid filename for given package_name.

    If not given a package name, see if fn fits the package name rules

    """
    if (package_name==None) or fn.startswith(package_name + '-'):
        if fn.endswith(ctx.const.package_suffix):
            # get version string, skip separator '-'
            verstr = fn[len(package_name) + 1:
                        len(fn)-len(ctx.const.package_suffix)]
            for x in verstr.split('-'):
                # weak rule: version components after '-' start with a digit
                if x == '' or (not x[0] in string.digits):
                    return False
            return True
    return False

def parse_package_name(package_name):
    """Separate package name and version string.

    example: tasma-1.0.3-5-2 -> (tasma, 1.0.3-5-2)

    """
    # We should handle package names like 855resolution
    name = []
    for part in package_name.split("-"):
        if name != [] and part[0] in string.digits:
            break
        else:
            name.append(part)
    name = "-".join(name)
    version = package_name[len(name) + 1:]

    return (name, version)

def parse_delta_package_name(package_name):
    """Separate delta package name and release infos

    example: tasma-5-7.pisi.delta -> (tasma, 5, 7)

    """
    name, build = parse_package_name(package_name)
    build = build[:-len(ctx.const.delta_package_suffix)]
    buildFrom, buildTo = build.split("-")

    return name, buildFrom, buildTo

def filter_latest_packages(package_paths):
    """ For a given pisi package paths list where there may also be multiple versions
        of the same package, filters only the latest versioned ones """

    import pisi.version

    latest = {}
    for path in package_paths:

        root = os.path.dirname(path)
        name, version = parse_package_name(os.path.basename(path[:-len(ctx.const.package_suffix)]))

        if latest.has_key(name):
            l_version = pisi.version.Version(latest[name][2])
            r_version = pisi.version.Version(version)

            # Bug 6352
            # If two has build nos than only look to build nos
            if l_version.build and r_version.build:
                if l_version.build < r_version.build:
                    latest[name] = (root, name, version)
            else:
                if l_version < r_version:
                    latest[name] = (root, name, version)
        else:
            if version:
                latest[name] = (root, name, version)

    return map(lambda x:"%s/%s-%s.pisi" % x, latest.values())

def colorize(msg, color):
    """Colorize the given message for console output"""
    if ctx.const.colors.has_key(color) and not ctx.get_option('no_color'):
        return ctx.const.colors[color] + msg + ctx.const.colors['default']
    else:
        return msg

