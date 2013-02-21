#!/usr/bin/env python

"""
check_server_magic.py magic [host]

Check a given magic against one or more servers; prints results to STDOUT.

Results can be:

 - CONN_ERR - there was an error in setting up the connection.
 - CLOSE - the connection was closed.
 - TIMEOUT - there was a timeout.
 
if host is supplied, that host is checked; otherwise, stdin is presumed to be 
a newline- delimited list of hosts to check.

magic must be in hex format; one easy way to generate in Python is:

>>> "foo\r\n".encode('hex-codec')
'666f6f0d0a'
 
"""


import sys
from time import time
from thor import stop, run, schedule
from thor.tcp import TcpClient
from thor.events import EventEmitter, on

import thor.loop
thor.loop.debug = False


class MagicChecker(EventEmitter):
    "Test magic against a single ip:port."
    connect_timeout = 3
    wait_timeout = 5

    def __init__(self, magic):
        """
        Given an IP address and port, try the magic on it, emitting a 'result' event.
        """
        EventEmitter.__init__(self)
        self.magic = magic + "\n"
        self.timeouts = []
        self.conn = None
        self.output = ''
        self.start = 0
        self.latency = 0
        self.client = TcpClient()
        self.client.on("connect", self.connect)
        self.client.on("connect_error", self.connect_error)

    def check(self, host, port):
        self.host = host
        self.port = port
        self.timeouts.append(
            schedule(self.connect_timeout, self.report, "TIMEOUT", "connect")
        )
        self.conn_start = time()
        self.client.connect(host, port)

    def connect(self, conn):
        self.conn = conn
        self.start = time()
        self.latency = self.start - self.conn_start
        self.timeouts[0].delete()
        self.timeouts.append(
            schedule(self.wait_timeout, self.report, "TIMEOUT", "wait")
        )
        conn.on("data", self.data)
        conn.on("close", self.close)
        conn.write(self.magic)
        conn.pause(False)

    def connect_error(self, err_type, err_id, err_str):
        self.start = time()
        self.latency = 0
        self.report("CONN_ERR", err_str)

    def data(self, chunk):
        self.output += chunk

    def close(self):
        self.report("CLOSE", '')

    def report(self, result, details):
        if (result, details) == ("TIMEOUT", "connect"):
            wait = time() - self.conn_start
        else:
            wait = time() - self.start - self.latency
        for timeout in self.timeouts:
            timeout.delete()
        if self.conn:
            self.conn.close()
        self.emit("result", 
                  result, details, self.output, wait, self.host, self.port)


def print_result(kind, details, output, delay, host, port):
    print "%s:%s %s %2.2f - %s" % (
        host,
        port,
        kind,
        delay,
        details and details.split("\n")[0].encode('utf-8', 'replace') or "",
    )


class LineReader(object):
    """
    Given a file-like object, read lines off of it, assuming that each line is a host
    to connect to, and run processor(proc_args) on it.
    """
    max_outstanding = 500
    notify = 100
    
    def __init__(self, inp, handle_result, processor, *proc_args):
        self.input = inp
        self.handle_result = handle_result
        self.processor = processor
        self.proc_args = proc_args
        self.running = True
        self.outstanding = 0
        self.line_num = 0
        schedule(0, self.schedule_lines)
        run()

    def schedule_lines(self):
        """
        Schedule some lines to run, respecting self.rate lines per second.
        """
        unreserved = self.max_outstanding - self.outstanding
        for i in range(unreserved):
            if self.running:
                line = self.input.readline()
                self.line_num += 1
                if line == "":
                    sys.stderr.write("* Input finished.\n")
                    self.running = False
                    break
                else:
                    self.parse_line(line)
                if self.line_num % self.notify == 0:
                    sys.stderr.write("* %s processed\n" % (self.line_num))
        if self.running:
            schedule(0.1, self.schedule_lines)

    def parse_line(self, line):
        """
        Parse a line.
        """
        host = line.strip()
        if ":" in host: # ivv6
            return
        self.outstanding += 1
        proc = self.processor(*self.proc_args)
        proc.on('result', self.line_done)
        proc.check(host, 80)

    def line_done(self, *args):
        self.outstanding -= 1
        self.handle_result(*args)
        if (not self.running) and self.outstanding <= 0:
            stop()


if __name__ == "__main__":
    magic = sys.argv[1].decode('hex-codec')
    if len(sys.argv) > 2:
        host = sys.argv[2]
        m = MagicChecker(magic)
        @on(m)
        def result(*args):
            print_result(*args)
            stop()
        m.check(host, 80)
        run()
    else:
        lr = LineReader(sys.stdin, print_result, MagicChecker, magic)