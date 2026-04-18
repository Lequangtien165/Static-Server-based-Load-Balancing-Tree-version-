"""
lb_controller.py - Static Server-Based Load Balancing (Tree Topology)
RYU + OpenFlow 1.3

Tree layout:
              s1  (dpid=1, LB switch, root)
             /  \
           s2    s3        (level-1 switches)
          / \   / \
        h1  h2 h3  h4

  s1-eth1 → s2 (uplink to client side)
  s1-eth2 → s3 (uplink to server side)
  s3-eth1 → s1  s3-eth2 → h3  s3-eth3 → h4
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp, ipv4

# ── Virtual IP / MAC ───────────────────────────────────────────────────────────
VIP     = '10.0.0.100'
VIP_MAC = '00:00:00:01:00:00'

# ── Backend servers ────────────────────────────────────────────────────────────
SERVERS = [
    {'ip': '10.0.0.3', 'mac': '00:00:00:00:00:03', 'port': 2},  # h3 on s3-eth2
    {'ip': '10.0.0.4', 'mac': '00:00:00:00:00:04', 'port': 3},  # h4 on s3-eth3
]

# ── Switch roles ───────────────────────────────────────────────────────────────
LB_DPID        = 1          # s1 is the root LB switch
S1_PORT_TO_S2  = 1          # s1-eth1 → s2 (client side)
S1_PORT_TO_S3  = 2          # s1-eth2 → s3 (server side)

FLOW_IDLE_TIMEOUT = 30


class StaticLB(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rr_idx   = 0
        self.mac_to_port = {}
        self._flow_count = 0
        print("=" * 60)
        print("Static Load Balancer (Tree Topology) started")
        print(f"  VIP     = {VIP}  ({VIP_MAC})")
        print(f"  Servers = {[s['ip'] for s in SERVERS]}")
        print(f"  LB switch dpid = {LB_DPID}")
        print("=" * 60)

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _add_flow(self, dp, priority, match, actions, idle=0):
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        inst   = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod    = parser.OFPFlowMod(
            datapath=dp, priority=priority,
            match=match, instructions=inst,
            idle_timeout=idle, hard_timeout=0
        )
        dp.send_msg(mod)

    def _send_pkt(self, dp, port, pkt_obj):
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        pkt_obj.serialize()
        out = parser.OFPPacketOut(
            datapath=dp, buffer_id=ofp.OFP_NO_BUFFER,
            in_port=ofp.OFPP_CONTROLLER,
            actions=[parser.OFPActionOutput(port)],
            data=pkt_obj.data
        )
        dp.send_msg(out)

    def _packet_out(self, dp, msg, actions):
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        data   = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        out    = parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id,
            in_port=msg.match['in_port'],
            actions=actions, data=data
        )
        dp.send_msg(out)

    # ── Event: switch connect ──────────────────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp     = ev.msg.datapath
        ofp    = dp.ofproto
        parser = dp.ofproto_parser
        # Table-miss: send everything to controller
        match   = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, 0, match, actions)
        role = "LB root (s1)" if dp.id == LB_DPID else f"L2 switch (dpid={dp.id})"
        print(f"[CONNECT] {role} dpid={dp.id}")

    # ── Event: packet-in ──────────────────────────────────────────────────────
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp  = msg.datapath
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None:
            return

        if dp.id == LB_DPID:
            # s1 handles load-balancing logic
            if eth.ethertype == 0x0806:
                self._lb_arp(dp, msg, pkt)
            elif eth.ethertype == 0x0800:
                self._lb_ip(dp, msg, pkt)
        else:
            # s2, s3 act as plain L2 learning switches
            self._l2_forward(dp, msg, pkt, eth)

    # ── s2 / s3: simple L2 learning switch ────────────────────────────────────
    def _l2_forward(self, dp, msg, pkt, eth):
        ofp     = dp.ofproto
        parser  = dp.ofproto_parser
        in_port = msg.match['in_port']

        table             = self.mac_to_port.setdefault(dp.id, {})
        table[eth.src]    = in_port
        out_port          = table.get(eth.dst, ofp.OFPP_FLOOD)
        actions           = [parser.OFPActionOutput(out_port)]

        if out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=eth.dst)
            self._add_flow(dp, 1, match, actions)

        self._packet_out(dp, msg, actions)

    # ── s1: ARP proxy ─────────────────────────────────────────────────────────
    def _lb_arp(self, dp, msg, pkt):
        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt is None:
            return
        in_port = msg.match['in_port']

        if arp_pkt.opcode == arp.ARP_REQUEST and arp_pkt.dst_ip == VIP:
            print(f"[ARP]  Proxy reply VIP {VIP} → {arp_pkt.src_ip} (in_port={in_port})")
            reply = packet.Packet()
            reply.add_protocol(ethernet.ethernet(
                dst=arp_pkt.src_mac, src=VIP_MAC, ethertype=0x0806))
            reply.add_protocol(arp.arp(
                opcode=arp.ARP_REPLY,
                src_mac=VIP_MAC, src_ip=VIP,
                dst_mac=arp_pkt.src_mac, dst_ip=arp_pkt.src_ip))
            self._send_pkt(dp, in_port, reply)
        else:
            ofp    = dp.ofproto
            parser = dp.ofproto_parser
            self._packet_out(dp, msg, [parser.OFPActionOutput(ofp.OFPP_FLOOD)])

    # ── s1: IP load-balancing (Round-Robin DNAT/SNAT) ─────────────────────────
    def _lb_ip(self, dp, msg, pkt):
        ip = pkt.get_protocol(ipv4.ipv4)
        if ip is None:
            return

        ofp     = dp.ofproto
        parser  = dp.ofproto_parser
        in_port = msg.match['in_port']

        # Only intercept traffic destined for VIP
        if ip.dst != VIP:
            self._packet_out(dp, msg, [parser.OFPActionOutput(ofp.OFPP_FLOOD)])
            return

        # Round-robin server selection
        self._flow_count += 1
        srv          = SERVERS[self._rr_idx % len(SERVERS)]
        self._rr_idx += 1

        print(f"[LB]   flow #{self._flow_count:03d}  {ip.src} → VIP → {srv['ip']}  "
              f"(server port on s3: eth{srv['port']})")

        # ── Forward path: client → VIP  ==>  s1 rewrites dst, sends to s3 ──
        # in_port here is S1_PORT_TO_S2 (traffic coming from client side)
        match_fwd = parser.OFPMatch(
            in_port=S1_PORT_TO_S2,
            eth_type=0x0800,
            ipv4_src=ip.src,
            ipv4_dst=VIP
        )
        actions_fwd = [
            parser.OFPActionSetField(eth_dst=srv['mac']),
            parser.OFPActionSetField(ipv4_dst=srv['ip']),
            parser.OFPActionOutput(S1_PORT_TO_S3)      # send toward s3
        ]
        self._add_flow(dp, 10, match_fwd, actions_fwd, idle=FLOW_IDLE_TIMEOUT)

        # ── Reverse path: server → client  ==>  s1 rewrites src back to VIP ──
        # Traffic arrives from s3 side; we need to know *which* server replied.
        # We match on ipv4_src=srv['ip'] coming in on S1_PORT_TO_S3.
        match_rev = parser.OFPMatch(
            in_port=S1_PORT_TO_S3,
            eth_type=0x0800,
            ipv4_src=srv['ip'],
            ipv4_dst=ip.src
        )
        actions_rev = [
            parser.OFPActionSetField(eth_src=VIP_MAC),
            parser.OFPActionSetField(ipv4_src=VIP),
            parser.OFPActionOutput(S1_PORT_TO_S2)      # send toward clients
        ]
        self._add_flow(dp, 10, match_rev, actions_rev, idle=FLOW_IDLE_TIMEOUT)

        # Forward the triggering packet immediately (before flow is hit)
        self._packet_out(dp, msg, actions_fwd)
