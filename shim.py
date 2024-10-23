#!/usr/bin/env python3

from argparse import ArgumentParser
from queue import Empty, SimpleQueue
from socket import AF_INET, SOCK_DGRAM, socket
from textwrap import dedent
from threading import Thread
from time import sleep
from xmlrpc.server import SimpleXMLRPCServer


class BufferServer(Thread):
    def __init__(self, queue, dest_port):
        super().__init__(name=self.__class__.__name__, daemon=True)
        self.queue = queue
        self.server = SimpleXMLRPCServer(
            ('127.0.0.1', dest_port), allow_none=True, logRequests=False
        )
        self.server.register_function(self.get_packet)

    def run(self):
        self.server.serve_forever()

    def get_packet(self):
        try:
            return self.queue.get_nowait()
        except Empty:
            return None


def main():
    parser = ArgumentParser("Buffers EDL uplink traffic for Pass Commander")
    parser.add_argument(
        "-s",
        "--source-port",
        default=10025,
        type=int,
        help="port to use for the source of EDL packetse, default is %(default)s",
    )
    parser.add_argument(
        "-d",
        "--destination-port",
        default=10036,
        type=int,
        help="port to use for Pass Commander, default is %(default)s",
    )
    parser.add_argument(
        '-e',
        '--edl-command',
        help=dedent(
            '''\
            Optional EDL command to send periodically during a pass
            Must be hex formatted with no 0x prefix'''
        ),
    )

    args = parser.parse_args()
    if args.edl_command is None:
        edl = None
    else:
        edl = bytes.fromhex(args.edl_command)

    queue = SimpleQueue()
    BufferServer(queue, args.destination_port).start()
    source = socket(AF_INET, SOCK_DGRAM)
    source.bind(("", args.source_port))

    while True:
        if edl is None:
            msg = source.recv(4096)
        else:
            msg = edl
            sleep(4)

        print(msg.hex())
        queue.put(msg)


if __name__ == "__main__":
    main()
