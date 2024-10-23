#!/usr/bin/env python3
'''Tiny testing script to request packets from shim.py'''

from time import sleep
from xmlrpc.client import Binary, ServerProxy

proxy = ServerProxy("http://localhost:10036")
while True:
    result = proxy.get_packet()
    if isinstance(result, Binary):
        print(result.data.hex())
    else:
        print(result)
    sleep(0.5)
