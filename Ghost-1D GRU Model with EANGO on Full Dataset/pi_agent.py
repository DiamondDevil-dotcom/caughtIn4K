import argparse
import json
import math
import socket
import statistics
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from scapy.all import ARP, Ether, ICMP, TCP, Raw, sniff


FEATURE_NAMES = [
    "Header_Length", "syn_flag_number", "rst_flag_number", "HTTP", "ARP",
    "ICMP", "LLC", "Tot sum", "Min", "IAT", "Number", "Magnitue",
    "Covariance", "Weight",
]


def features_from_packets(packets):
    lengths = [len(packet) for packet in packets]
    intervals = [max(0.0, float(b.time - a.time)) for a, b in zip(packets, packets[1:])]
    tcp_packets = [packet for packet in packets if packet.haslayer(TCP)]
    total_bytes = sum(lengths)
    duration = max(1.0, float(packets[-1].time - packets[0].time))
    values = {
        "Header_Length": float(sum(len(packet.getlayer(Ether).fields) if packet.haslayer(Ether) else 0 for packet in packets)),
        "syn_flag_number": float(sum(bool(packet[TCP].flags & 0x02) for packet in tcp_packets)),
        "rst_flag_number": float(sum(bool(packet[TCP].flags & 0x04) for packet in tcp_packets)),
        "HTTP": float(sum(packet.haslayer(TCP) and (packet[TCP].sport in (80, 8080) or packet[TCP].dport in (80, 8080) or (packet.haslayer(Raw) and bytes(packet[Raw].load).startswith((b"GET ", b"POST ", b"HTTP/")))) for packet in packets)),
        "ARP": float(sum(packet.haslayer(ARP) for packet in packets)),
        "ICMP": float(sum(packet.haslayer(ICMP) for packet in packets)),
        "LLC": float(sum(packet.haslayer(Ether) and packet[Ether].type <= 1500 for packet in packets)),
        "Tot sum": float(total_bytes),
        "Min": float(min(lengths)),
        "IAT": float(statistics.mean(intervals) if intervals else 0.0),
        "Number": float(len(packets)),
        "Magnitue": float(math.sqrt(sum(length * length for length in lengths))),
        "Covariance": float(statistics.pvariance(lengths) if len(lengths) > 1 else 0.0),
        "Weight": float(total_bytes / duration),
    }
    return [values[name] for name in FEATURE_NAMES]


def network_identity(interface, api_host):
    mac_path = f"/sys/class/net/{interface}/address"
    try:
        with open(mac_path, encoding="utf-8") as file:
            mac_address = file.read().strip().upper()
    except OSError:
        mac_address = "Unavailable"

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect((api_host, 80))
            ip_address = connection.getsockname()[0]
    except OSError:
        ip_address = "Unavailable"

    return ip_address, mac_address


def send(api_url, device, features, ip_address, mac_address):
    body = json.dumps({
        "device": device,
        "features": features,
        "ip_address": ip_address,
        "mac_address": mac_address,
    }).encode()
    request = Request(api_url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


def main():
    parser = argparse.ArgumentParser(description="caughtIn4K Raspberry Pi telemetry agent")
    parser.add_argument("--device", default="Raspberry Pi Node 1")
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--iface", default="wlan0")
    parser.add_argument("--window", type=float, default=5.0)
    args = parser.parse_args()
    api_host = urlparse(args.api_url).hostname
    capture_filter = f"not host {api_host}" if api_host else None
    ip_address, mac_address = network_identity(args.iface, api_host or "8.8.8.8")

    print(
        f"Sending real traffic from {args.device} ({ip_address}, {mac_address}) "
        f"to {args.api_url}",
        flush=True,
    )
    while True:
        packets = sniff(
            iface=args.iface,
            filter=capture_filter,
            timeout=args.window,
            store=True,
        )
        if not packets:
            continue
        try:
            result = send(
                args.api_url,
                args.device,
                features_from_packets(packets),
                ip_address,
                mac_address,
            )
            print(json.dumps(result), flush=True)
        except (HTTPError, URLError, OSError) as error:
            print(f"API unavailable: {error}", flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()