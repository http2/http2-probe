#!/usr/bin/env python

"""
get_header.py header [host]

Get the specified header for one or more servers; prints results to STDOUT.

Results can be:

 - OK - the header payload.
 - ERR - an error occured.
 
if host is supplied, that host is checked; otherwise, stdin is presumed to be 
a newline- delimited list of hosts to check. 
"""


import sys
from time import time
from thor import stop, run, schedule
from thor.http import HttpClient, header_dict
from thor.events import EventEmitter, on

import thor.loop
thor.loop.debug = False


class HeaderGetter(EventEmitter):
    "Get the specified header for a single ip:port."
    connect_timeout = 3
    wait_timeout = 5

    def __init__(self, header):
        """
        Given an IP address and port, try the magic on it, emitting a 'result' event.
        """
        EventEmitter.__init__(self)
        self.header = header.lower()
        self.client = HttpClient()
        self.client.connect_timeout = self.connect_timeout
        self.client.read_timeout = self.wait_timeout

    def check(self, host, port):
        x = self.client.exchange()        

        @on(x)
        def response_start(status, phrase, headers):
            header = ", ".join(header_dict(headers).get(self.header, ['-']))
            self.emit("result", "OK", header, host, port)
            if x.tcp_conn:
                x.tcp_conn.close()
            
        @on(x)
        def error(err_msg):
            self.emit("result", "ERR", err_msg, host, port)
            if x.tcp_conn:
                x.tcp_conn.close()
        x.request_start("HEAD", "http://%s/" % host, [("User-Agent", "Test/1.0")])
        x.request_done([])


def print_result(kind, details, host, port):
    print "%s:%s %s %s" % (
        host,
        port,
        kind,
        details
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
    header = sys.argv[1]
    if len(sys.argv) > 2:
        host = sys.argv[2]
        m = HeaderGetter(header)
        @on(m)
        def result(*args):
            print_result(*args)
            stop()
        m.check(host, 80)
        run()
    else:
        lr = LineReader(sys.stdin, print_result, HeaderGetter, header)