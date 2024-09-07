#!/usr/bin/env python3
from xmlrpc.server import SimpleXMLRPCServer

# TODO: configure address


class Flowgraph:
    def __init__(self):
        self.morse_bump = 0

        self.server = SimpleXMLRPCServer(('127.0.0.2', 10080), allow_none=True, logRequests=False)
        self.server.register_instance(self)

    def start(self):
        self.server.serve_forever()

    def stop(self):
        self.server.shutdown()

    def get_tx_center_frequency(self):
        return 1_265_000_000

    def get_rx_target_frequency(self):
        return 436_500_000

    def set_gpredict_tx_frequency(self, value):
        print("TX Freq", value)

    def set_gpredict_rx_frequency(self, value):
        print("RX Freq", value)

    def set_morse_bump(self, val):
        self.morse_bump = val

    def get_morse_bump(self):
        return self.morse_bump


if __name__ == '__main__':
    Flowgraph()
