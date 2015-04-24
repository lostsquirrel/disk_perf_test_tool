import re
import os
import socket
import logging
import threading
import contextlib
import subprocess


logger = logging.getLogger("wally")


def parse_creds(creds):
    # parse user:passwd@host
    user, passwd_host = creds.split(":", 1)

    if '@' not in passwd_host:
        passwd, host = passwd_host, None
    else:
        passwd, host = passwd_host.rsplit('@', 1)

    return user, passwd, host


class TaksFinished(Exception):
    pass


class Barrier(object):
    def __init__(self, count):
        self.count = count
        self.curr_count = 0
        self.cond = threading.Condition()
        self.exited = False

    def wait(self, timeout=None):
        with self.cond:
            if self.exited:
                raise TaksFinished()

            self.curr_count += 1
            if self.curr_count == self.count:
                self.curr_count = 0
                self.cond.notify_all()
                return True
            else:
                self.cond.wait(timeout=timeout)
                return False

    def exit(self):
        with self.cond:
            self.exited = True


@contextlib.contextmanager
def log_error(action, types=(Exception,)):
    if not action.startswith("!"):
        logger.debug("Starts : " + action)
    else:
        action = action[1:]

    try:
        yield
    except Exception as exc:
        if isinstance(exc, types) and not isinstance(exc, StopIteration):
            templ = "Error during {0} stage: {1!s}"
            logger.debug(templ.format(action, exc))
        raise


SMAP = dict(k=1024, m=1024 ** 2, g=1024 ** 3, t=1024 ** 4)


def ssize_to_b(ssize):
    try:
        ssize = ssize.lower()

        if ssize.endswith("b"):
            ssize = ssize[:-1]
        if ssize[-1] in SMAP:
            return int(ssize[:-1]) * SMAP[ssize[-1]]
        return int(ssize)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Unknow size format {0!r}".format(ssize))


def get_ip_for_target(target_ip):
    if not re.match("[0-9]+\.[0-9]+\.[0-9]+\.[0-9]$", target_ip):
        target_ip = socket.gethostbyname(target_ip)

    if target_ip in ('localhost', '127.0.0.1', '127.0.1.1'):
        return '127.0.0.1'

    cmd = 'ip route get to'.split(" ") + [target_ip]
    data = subprocess.Popen(cmd, stdout=subprocess.PIPE).stdout.read()

    rr1 = r'{0} via [.0-9]+ dev (?P<dev>.*?) src (?P<ip>[.0-9]+)$'
    rr1 = rr1.replace(" ", r'\s+')
    rr1 = rr1.format(target_ip.replace('.', r'\.'))

    rr2 = r'{0} dev (?P<dev>.*?) src (?P<ip>[.0-9]+)$'
    rr2 = rr2.replace(" ", r'\s+')
    rr2 = rr2.format(target_ip.replace('.', r'\.'))

    data_line = data.split("\n")[0].strip()
    res1 = re.match(rr1, data_line)
    res2 = re.match(rr2, data_line)

    if res1 is not None:
        return res1.group('ip')

    if res2 is not None:
        return res2.group('ip')

    raise OSError("Can't define interface for {0}".format(target_ip))


def open_for_append_or_create(fname):
    if not os.path.exists(fname):
        return open(fname, "w")

    fd = open(fname, 'r+')
    fd.seek(0, os.SEEK_END)
    return fd


def sec_to_str(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return "{0}:{1:02d}:{2:02d}".format(h, m, s)


def yamable(data):
    if isinstance(data, (tuple, list)):
        return map(yamable, data)

    if isinstance(data, unicode):
        return str(data)

    if isinstance(data, dict):
        res = {}
        for k, v in data.items():
            res[yamable(k)] = yamable(v)
        return res

    return data