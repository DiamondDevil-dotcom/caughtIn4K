import argparse
import json
import math
import statistics
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from scapy.all import ARP, Ether, ICMP, IP, TCP, Raw, sniff


PROJECT_DIR = Path(__file__).resolve().parent
FEATURES_PATH = PROJECT_DIR / "selected_features.json"


def post_features(api_url, device, features):
    payload = json.dumps({"device": device, "features": features}).encode()
    request = Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


def packet_features(packets):
    lengths = [len(packet) for packet in packets]
    intervals = [
        max(0.0, float(b.time - a.time))
        for a, b in zip(packets, packets[1:])
    ]
    tcp_packets = [packet for packet in packets if packet.haslayer(TCP)]
    http_packets = [
        packet for packet in packets
        if packet.haslayer(TCP)
        and (packet[TCP].sport in (80, 8080) or packet[TCP].dport in (80, 8080)
             or (packet.haslayer(Raw) and bytes(packet[Raw].load).startswith((b"GET ", b"POST ", b"HTTP/"))))
    ]
    syn_count = sum(bool(packet[TCP].flags & 0x02) for packet in tcp_packets)
    rst_count = sum(bool(packet[TCP].flags & 0x04) for packet in tcp_packets)
    total_bytes = sum(lengths)
    duration = max(1.0, float(packets[-1].time - packets[0].time))
    mean_length = total_bytes / len(lengths)
    variance = statistics.pvariance(lengths) if len(lengths) > 1 else 0.0

    values = {
        "Header_Length": float(sum(len(packet.getlayer(Ether).fields) if packet.haslayer(Ether) else 0 for packet in packets)),
        "syn_flag_number": float(syn_count),
        "rst_flag_number": float(rst_count),
        "HTTP": float(len(http_packets)),
        "ARP": float(sum(packet.haslayer(ARP) for packet in packets)),
        "ICMP": float(sum(packet.haslayer(ICMP) for packet in packets)),
        "LLC": float(sum(packet.haslayer(Ether) and packet[Ether].type <= 1500 for packet in packets)),
        "Tot sum": float(total_bytes),
        "Min": float(min(lengths)),
        "IAT": float(statistics.mean(intervals) if intervals else 0.0),
        "Number": float(len(packets)),
        "Magnitue": float(math.sqrt(sum(length * length for length in lengths))),
        "Covariance": float(variance),
        "Weight": float(total_bytes / duration),
    }
    return [values[name] for name in FEATURE_NAMES]


def main():
    parser = argparse.ArgumentParser(description="Send real packet telemetry to Ghost IDS.")
    parser.add_argument("--device", required=True)
    parser.add_argument("--ip", required=True, help="IPv4 address of the IoT device")
    parser.add_argument("--api-url", default="http://10.121.31.102:8000/traffic")
    parser.add_argument("--iface", help="Capture interface; omit to use Scapy default")
    parser.add_argument("--window", type=float, default=2.0)
    args = parser.parse_args()

    print(f"Capturing real traffic for {args.device} ({args.ip})", flush=True)
    print("Requires Npcap and an elevated terminal on Windows.", flush=True)
    while True:
        packets = sniff(
            iface=args.iface,
            filter=f"host {args.ip}",
            timeout=args.window,
            store=True,
        )
        if not packets:
            continue
        features = packet_features(packets)
        while True:
            try:
                result = post_features(args.api_url, args.device, features)
                print(json.dumps(result), flush=True)
                break
            except (URLError, HTTPError, TimeoutError, OSError) as error:
                print(f"API unavailable ({error}); retrying in 2 seconds", flush=True)
                time.sleep(2)


with open(FEATURES_PATH, encoding="utf-8") as features_file:
    FEATURE_NAMES = json.load(features_file)


if __name__ == "__main__":
    main()