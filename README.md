# Static Server-Based Load Balancing với SDN

> **NT541 - Programmable Network Technology** | UIT Group Project  
> Ryu Controller + OpenFlow 1.3 + Mininet | Tree Topology

---

## Topology

```
              s1  (dpid=1, LB Switch / Root)
             /  \
           s2    s3
          / \   / \
        h1  h2 h3  h4
     (clients)  (servers)
```

| Node | IP | MAC | Vai trò |
|------|----|-----|---------|
| s1 | — | dpid=1 | LB Switch (root), xử lý DNAT/SNAT |
| s2 | — | dpid=2 | L2 learning switch (phía client) |
| s3 | — | dpid=3 | L2 learning switch (phía server) |
| h1 | 10.0.0.1 | 00:00:00:00:00:01 | Client 1 |
| h2 | 10.0.0.2 | 00:00:00:00:00:02 | Client 2 |
| h3 | 10.0.0.3 | 00:00:00:00:00:03 | Server 1 |
| h4 | 10.0.0.4 | 00:00:00:00:00:04 | Server 2 |
| VIP | 10.0.0.100 | 00:00:00:01:00:00 | Virtual IP (ARP Proxy trên s1) |

---

## Cấu trúc file

```
project/
├── topo.py           # Khởi tạo Tree Topology trong Mininet
├── lb_controller.py  # Ryu Controller - Load Balancing logic
└── server.py         # HTTP server đơn giản chạy trên h3, h4
```

---

## Cách chạy

### Bước 1 — Khởi động Ryu Controller (VM 1)

```bash
ryu-manager lb_controller.py
```

### Bước 2 — Khởi động Mininet (VM 2)

```bash
# Thay IP bằng IP thực của VM chạy Ryu
sudo python3 topo.py 192.168.x.x
```

### Bước 3 — Khởi động server trên h3, h4

```
mininet> h3 python3 server.py &
mininet> h4 python3 server.py &
```

### Bước 4 — Kiểm thử

```
mininet> h1 curl http://10.0.0.100
mininet> h1 curl http://10.0.0.100
mininet> h2 curl http://10.0.0.100
```

---

## Kết quả mong đợi

**Mininet:**
```
mininet> h1 curl http://10.0.0.100
Hello from SERVER 10.0.0.3

mininet> h1 curl http://10.0.0.100
Hello from SERVER 10.0.0.4

mininet> h2 curl http://10.0.0.100
Hello from SERVER 10.0.0.3
```

**Ryu log:**
```
[CONNECT] LB root (s1) dpid=1
[CONNECT] L2 switch (dpid=2)
[CONNECT] L2 switch (dpid=3)
[ARP]  Proxy reply VIP 10.0.0.100 -> 10.0.0.1 (in_port=1)
[LB]   flow #001  10.0.0.1 -> VIP -> 10.0.0.3  (server port on s3: eth2)
[LB]   flow #002  10.0.0.1 -> VIP -> 10.0.0.4  (server port on s3: eth3)
```

---

## Cơ chế hoạt động

- **ARP Proxy**: s1 tự trả lời ARP request hỏi VIP, trả về `VIP_MAC` mà không flood ra mạng
- **Round-Robin**: mỗi luồng IP mới đến VIP được phân phối luân phiên giữa h3 và h4
- **DNAT**: s1 đổi `dst IP/MAC` từ VIP → server thực khi gói đi xuống
- **SNAT**: s1 đổi `src IP/MAC` từ server thực → VIP khi gói trả về
- **Flow rule**: `idle_timeout=30s` — switch tự xử lý gói tiếp theo, không cần qua controller

---

## Lưu ý

- `server.py` không cần thay đổi — tự detect IP host qua UDP trick
- Nếu test liên tiếp nhanh, flow cũ còn hiệu lực (30s) nên curl có thể vào cùng server
- Thêm server: mở rộng s3 và cập nhật `SERVERS[]` trong `lb_controller.py`
- Đảm bảo `CONTROLLER_IP` trong `topo.py` trỏ đúng IP VM chạy Ryu
