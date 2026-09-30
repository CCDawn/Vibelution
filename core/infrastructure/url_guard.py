"""URL 出口防护（egress guard）：URL 字面量层面的统一出站目标策略。

纯函数模块，不做任何网络访问。所有对模型可控或环境可控 URL 发起出站请求的
入口（web_fetch、research 检索后端、DOI registry 兜底等）都应复用这里的判定，
不得各自复制私网/保留段清单。

判定结构借鉴 ZCode CLI 的 webfetch-egress-guard（tool/handlers/webfetch-egress-guard.ts）：
- localhost / *.localhost 一律拒绝；
- IP 字面量必须是公网单播地址：198.18.0.0/15 基准网段（RFC 2544）与
  special-use IPv6 段（RFC 6890 等）显式排除；
- IPv4-mapped（::ffff:0:0/96）与 NAT64/DNS64 well-known 前缀（64:ff9b::/96，
  RFC 6052）编码的地址先还原出低 32 位 IPv4，再套同一套 IPv4 策略——
  否则 `64:ff9b::127.0.0.1` 这类编码会绕过私网拦截；
- 刻意不做 DNS preflight：部分网络下本地解析 1s 内无法完成，会让公网 URL
  在真实 fetch 之前就失败。DNS rebinding 与「重定向落内网」由各入口用
  「每跳过本模块校验 + 受控重定向」防护，不在这里解。
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

# 本机/内部域名后缀。`.local` 是 mDNS，`.internal` 是内网约定域；
# `.localhost` 与裸 `localhost` 同义（RFC 6761）。
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal")

# 旧版校验函数显式列出的本机字面量；命中时返回「本机」文案而非通用私网文案。
_EXPLICIT_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1"})

# IPv4 非公网单播段。显式列出而不依赖 stdlib ``ipaddress`` 的 ``is_private``：
# 该属性的网络清单随 Python 版本变动（如 gh-113171 在 3.12.4 重划过
# is_global/is_private 口径），安全边界不能随解释器版本漂移。
_IPV4_BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "0.0.0.0/8",  # "this network"（RFC 791）
        "10.0.0.0/8",  # 私网（RFC 1918）
        "100.64.0.0/10",  # CGN 共享地址（RFC 6598）
        "127.0.0.0/8",  # 环回
        "169.254.0.0/16",  # 链路本地
        "172.16.0.0/12",  # 私网（RFC 1918）
        "192.0.0.0/24",  # IETF 协议保留
        "192.0.2.0/24",  # TEST-NET-1 文档段
        "192.88.99.0/24",  # 6to4 relay anycast（已废弃）
        "192.168.0.0/16",  # 私网（RFC 1918）
        "198.18.0.0/15",  # 基准测试网段（RFC 2544）
        "198.51.100.0/24",  # TEST-NET-2 文档段
        "203.0.113.0/24",  # TEST-NET-3 文档段
        "224.0.0.0/4",  # 组播
        "240.0.0.0/4",  # 保留（含 255.255.255.255 广播）
    )
)

# IPv6 special-use 段。64:ff9b::/96（NAT64 well-known 前缀）不在清单里：
# 它编码的是 IPv4 目标，先经 ``_unwrap_carrier_ipv6`` 还原再按 IPv4 策略判定。
# 2001::/23 整段是 IETF 协议保留，覆盖 Teredo（2001::/32）、基准（2001:2::/48）、
# ORCHID（2001:10::/28）、ORCHIDv2（2001:20::/28）等；2001:db8::/32（文档段）
# 在 /23 之外，单独列出。
_IPV6_BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "::/128",  # 未指定地址
        "::1/128",  # 环回
        "::ffff:0:0/96",  # IPv4-mapped（正常应已还原，兜底保留）
        "64:ff9b:1::/48",  # NAT64 local-use 前缀（RFC 8215）
        "100::/64",  # discard-only（RFC 6666）
        "2001::/23",  # IETF 协议保留（Teredo/基准/ORCHID 等）
        "2001:db8::/32",  # 文档段
        "2002::/16",  # 6to4（内嵌 IPv4，已废弃；整体拒绝）
        "fc00::/7",  # unique-local
        "fe80::/10",  # 链路本地
        "ff00::/8",  # 组播
    )
)

# NAT64/DNS64 well-known 前缀（RFC 6052）。低 32 位是编码的 IPv4 地址。
_NAT64_WELL_KNOWN_NETWORK = ipaddress.ip_network("64:ff9b::/96")
_IPV4_MAPPED_NETWORK = ipaddress.ip_network("::ffff:0:0/96")

LOCAL_HOST_ERROR = "出于安全原因，不允许访问本机或内部网络地址"
PRIVATE_IP_ERROR = "出于安全原因，不允许访问私有、环回或保留 IP 地址"


def normalize_hostname(hostname: str) -> str:
    """归一化主机名：去空白、去方括号、小写、去末尾根点。"""
    host = str(hostname or "").strip().lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host.removesuffix(".")


def is_local_hostname(hostname: str) -> bool:
    """localhost / *.localhost 判定（大小写与根点已归一化）。"""
    host = normalize_hostname(hostname)
    return host == "localhost" or host.endswith(".localhost")


def _unwrap_carrier_ipv6(address: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """从 IPv6 载荷地址中还原被编码的 IPv4 地址。

    覆盖两类编码：IPv4-mapped（::ffff:a.b.c.d）与 NAT64/DNS64 well-known
    前缀（64:ff9b::/96）。其余前缀（6to4 2002::/16、Teredo 等）不还原——
    它们整体落在 ``_IPV6_BLOCKED_NETWORKS`` 清单里，直接拒绝。
    """
    if address in _IPV4_MAPPED_NETWORK:
        mapped = address.ipv4_mapped
        return mapped
    if address in _NAT64_WELL_KNOWN_NETWORK:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return None


def is_public_ip_address(address: str) -> bool:
    """IP 字面量必须是公网单播地址；解析失败一律视为不公开。"""
    host = normalize_hostname(address)
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv6Address):
        unwrapped = _unwrap_carrier_ipv6(parsed)
        if unwrapped is not None:
            return _is_public_ipv4(unwrapped)
        return not _in_networks(parsed, _IPV6_BLOCKED_NETWORKS)
    return _is_public_ipv4(parsed)


def _is_public_ipv4(address: ipaddress.IPv4Address) -> bool:
    return not _in_networks(address, _IPV4_BLOCKED_NETWORKS)


def _in_networks(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> bool:
    return any(address in network for network in networks)


def validate_public_http_url(url: str) -> str:
    """校验出站 URL；通过返回 ``""``，否则返回面向模型的中文错误说明。

    覆盖：scheme 白名单、必须携带主机名、禁止 userinfo、本机/内部域名后缀、
    IP 字面量的公网单播策略（含 mapped/NAT64 还原）。域名解析结果不在
    本函数范围内——见模块 docstring 的「不做 DNS preflight」取舍。
    """
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"}:
        return "URL 必须使用 http:// 或 https://"
    if not parsed.hostname:
        return "URL 缺少主机名"
    if parsed.username or parsed.password:
        return "URL 不能包含用户名或密码"
    host = normalize_hostname(parsed.hostname)
    # 旧版 tools.web_search_tool._validate_public_http_url 的显式字面量集合；
    # 保留这一层的独立文案映射，既有调用方的错误文案语义不漂移。
    if host in _EXPLICIT_LOCAL_HOSTS or host == "localhost" or host.endswith(BLOCKED_HOST_SUFFIXES):
        return LOCAL_HOST_ERROR
    if is_ip_literal_candidate(host) and not is_public_ip_address(host):
        return PRIVATE_IP_ERROR
    return ""


def is_ip_literal_candidate(host: str) -> bool:
    """主机名是否应按 IP 字面量处理。

    合法域名不允许出现 ``:``（IPv6 记法）或 ``%``（zone id），因此带这两个
    字符但解析失败的主机名按不公开处理（fail closed），防止变形字面量绕过。
    """
    if not host:
        return False
    if ":" in host or "%" in host:
        return True
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


__all__ = [
    "BLOCKED_HOST_SUFFIXES",
    "LOCAL_HOST_ERROR",
    "PRIVATE_IP_ERROR",
    "is_ip_literal_candidate",
    "is_local_hostname",
    "is_public_ip_address",
    "normalize_hostname",
    "validate_public_http_url",
]
