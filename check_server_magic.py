#!/usr/bin/env python

import sys
import time
from thor import stop, run, schedule
from thor.tcp import TcpClient
from thor.events import EventEmitter, on

import thor.loop
thor.loop.debug = False


class MagicChecker(EventEmitter):
    "Test magic against a single ip:port."
    connect_timeout = 5
    wait_timeout = 7
    
    def __init__(self):
        """
        Given an IP address and port, try the magic on it, emitting a 'result' event.
        """
        EventEmitter.__init__(self)
        self.timeouts = []
        self.conn = None
        self.output = ''
        self.start = 0
        self.latency = 0
        self.client = TcpClient()
        self.client.on("connect", self.connect)
        self.client.on("connect_error", self.connect_error)
        
    def check(self, host, port, magic):
        self.host = host
        self.port = port
        self.magic = magic + "\r\n"
        self.timeouts.append(
            schedule(self.connect_timeout, self.report, "TIMEOUT", "connect")
        )
        self.conn_start = time.time()
        self.client.connect(host, port)
        
    def connect(self, conn):
        self.start = time.time()
        self.timeouts[0].delete()
        self.conn = conn
        self.timeouts.append(
            schedule(self.wait_timeout, self.report, "TIMEOUT", "wait")
        )
        conn.on("data", self.data)
        conn.on("close", self.close)
        conn.write(self.magic)
        conn.pause(False)
        
    def connect_error(self, err_type, err_id, err_str):
        self.start = time.time()
        self.latency = self.start - self.conn_start
        self.report("CONN_ERR", err_str)

    def data(self, chunk):
        self.output += chunk

    def close(self):
        self.report("CLOSE", '')

    def report(self, result, details):
        wait = time.time() - self.start - self.latency
        for timeout in self.timeouts:
            timeout.delete()
        if self.conn:
            self.conn.close()
        self.emit("result", result, details, self.output, wait)
    
if __name__ == "__main__":
    m = MagicChecker()
    @on(m)
    def result(kind, details, output, delay):
        print "%s: %s (%2.2f)" % (
            kind, 
            details and details.encode('base64_codec')[:-1] or "",
            delay
        )
        stop()
    m.check(sys.argv[1], 80, sys.argv[2])
    run()