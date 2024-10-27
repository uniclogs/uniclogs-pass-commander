#!/usr/bin/env python3
import socket


def main():
    cmdr = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    cmdr.bind(("127.0.0.1", 5005))
    #s.connect(addr)

    while True:
        packet, addr = cmdr.recvfrom(4096)
        action = packet.decode('ascii')
        print(addr, action)
        # The stationd protocol is more complex than I actually want to try to emulate.
        # This is mostly nonsense returns but class Station seems to accept them without
        # crashing.
        if action.startswith('gettemp'):
            cmdr.sendto("25".encode("ascii"), addr)
        else:
            cmdr.sendto(f"SUCCESS: {action}".encode("ascii"), addr)

if __name__ == "__main__":
    main()
