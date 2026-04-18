#!/usr/bin/env python3
"""
Static Server-Based Load Balancing - Tree Topology
                    s1 (LB Switch / Root)
                   /  \
                 s2    s3
                / \    / \
              h1  h2  h3  h4

Usage: sudo python3 topo.py [controller_ip]
  controller_ip: IP của VM chạy RYU (192.168.56.30)

Mapping:
  h1 = client 1   (10.0.0.1)
  h2 = client 2   (10.0.0.2)
  h3 = server 1   (10.0.0.3)
  h4 = server 2   (10.0.0.4)
  VIP             = 10.0.0.100
"""

import sys
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info

CONTROLLER_IP = sys.argv[1] if len(sys.argv) > 1 else '192.168.56.30'


class TreeLBTopo(Topo):
    """
    Tree topology (depth=2, fanout=2):

              s1  (dpid=1, LB switch, root)
             /  \
           s2    s3        (dpid=2,3  – level-1 switches)
          / \   / \
        h1  h2 h3  h4     (level-2 hosts)

    Port assignments on s1:
      s1-eth1 → s2
      s1-eth2 → s3

    Port assignments on s2:
      s2-eth1 → s1  (uplink)
      s2-eth2 → h1
      s2-eth3 → h2

    Port assignments on s3:
      s3-eth1 → s1  (uplink)
      s3-eth2 → h3  (server 1)
      s3-eth3 → h4  (server 2)
    """

    def build(self):
        # ── Hosts ──────────────────────────────────────────────────
        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01',
                          defaultRoute='via 10.0.0.1')
        h2 = self.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02',
                          defaultRoute='via 10.0.0.2')
        h3 = self.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:00:03',
                          defaultRoute='via 10.0.0.3')
        h4 = self.addHost('h4', ip='10.0.0.4/24', mac='00:00:00:00:00:04',
                          defaultRoute='via 10.0.0.4')

        # ── Switches ───────────────────────────────────────────────
        s1 = self.addSwitch('s1', dpid='0000000000000001')  # Root / LB
        s2 = self.addSwitch('s2', dpid='0000000000000002')  # Level-1 left  (clients)
        s3 = self.addSwitch('s3', dpid='0000000000000003')  # Level-1 right (servers)

        # ── Links ──────────────────────────────────────────────────
        # s1 ↔ s2  (s1:port1 — s2:port1)
        self.addLink(s1, s2, port1=1, port2=1)

        # s1 ↔ s3  (s1:port2 — s3:port1)
        self.addLink(s1, s3, port1=2, port2=1)

        # s2 ↔ h1  (s2:port2)
        self.addLink(s2, h1, port1=2)

        # s2 ↔ h2  (s2:port3)
        self.addLink(s2, h2, port1=3)

        # s3 ↔ h3  (s3:port2)  – server 1
        self.addLink(s3, h3, port1=2)

        # s3 ↔ h4  (s3:port3)  – server 2
        self.addLink(s3, h4, port1=3)


topos = {'treelbtopo': TreeLBTopo}


def run():
    setLogLevel('info')
    topo = TreeLBTopo()

    c0 = RemoteController('c0', ip=CONTROLLER_IP, port=6633)

    net = Mininet(
        topo=topo,
        switch=OVSSwitch,
        controller=c0,
        autoSetMacs=False
    )
    net.start()

    info('\n*** Tree Topology ready\n')
    info('Clients : h1=10.0.0.1  h2=10.0.0.2\n')
    info('Servers : h3=10.0.0.3  h4=10.0.0.4   VIP=10.0.0.100\n')
    info('\nRun server.py trên h3 và h4 trước khi test:\n')
    info('  mininet> h3 python3 server.py &\n')
    info('  mininet> h4 python3 server.py &\n')
    info('Test:\n')
    info('  mininet> h1 curl http://10.0.0.100\n')
    info('  mininet> h2 curl http://10.0.0.100\n\n')

    CLI(net)
    net.stop()


if __name__ == '__main__':
    run()
