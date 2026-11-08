"""Offline provisioning tests for the pinned MXC executor installer.

全部离线：release 服务由进程内 ``http.server`` 在 loopback 上模拟，zip 由
``zipfile`` 现场构造；被 pin 的模块常量（资产 URL、zip/exe SHA256、zip 字节
上限、PE 版本读取）全部 ``monkeypatch`` 成 fixture 计算出的真值，因此既不
依赖真实 ``wxc-exec.exe``，也不访问 GitHub。覆盖：

- already_present 幂等（合法文件在位时零网络请求）。
- 下载安装全链路 happy path（下载 → zip SHA → 解压 → exe SHA → 原子替换），
  再调一次回到 already_present。
- zip SHA 不符 / zip-slip 成员 / 缺少目标成员 / 大小超限 / HTTP 500 /
  连接拒绝 / 下载超时：全部 failed，目标路径零副作用，临时目录清理。
- 既有损坏文件：failed 且绝不覆盖（保守 no-overwrite）。
- CLI 冒烟：--check/--install/--json 输出可 json.loads 且 ASCII-safe。
"""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import socket
import tempfile
import threading
import time
import zipfile
from pathlib import Path

import pytest

from core.infrastructure.codex_sandbox import executor_provision as ep

FAKE_EXE_BYTES = b"MZ" + b"vibelution-fake-wxc-exec-payload\x00" * 8


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_zip_bytes(
    exe_bytes: bytes = FAKE_EXE_BYTES,
    *,
    extra_members: list[tuple[str, bytes]] | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, blob in extra_members or []:
            archive.writestr(name, blob)
        archive.writestr(ep.ZIP_MEMBER, exe_bytes)
    return buffer.getvalue()


class _FakeReleaseServer:
    """Loopback http.server serving one fake release asset with counters."""

    def __init__(self, payload: bytes, *, status: int = 200, delay_s: float = 0.0):
        self.payload = payload
        self.status = status
        self.delay_s = delay_s
        self.request_count = 0
        outer = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            server_version = "FakeMXCRelease/1.0"

            def do_GET(self) -> None:
                outer.request_count += 1
                if outer.delay_s:
                    time.sleep(outer.delay_s)
                body = outer.payload if outer.status == 200 else b""
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def log_message(self, fmt, *args) -> None:  # keep output clean
                pass

        self._httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}/{ep.PINNED_ZIP_FILENAME}"

    def start(self) -> None:
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def fake_release(tmp_path, monkeypatch):
    """Fake loopback release server + all pins swapped to fixture values."""
    zip_bytes = _build_zip_bytes()
    server = _FakeReleaseServer(zip_bytes)
    server.start()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(ep, "PINNED_ASSET_URL", server.url)
    monkeypatch.setattr(ep, "PINNED_ZIP_SHA256", _sha256_bytes(zip_bytes))
    monkeypatch.setattr(ep, "PINNED_ZIP_SIZE_BYTES", len(zip_bytes))
    monkeypatch.setattr(ep, "PINNED_EXECUTOR_SHA256", _sha256_bytes(FAKE_EXE_BYTES))
    # 假 exe 没有 PE 版本资源：版本读取缝打桩成 1.0.1（1.0.x 版本门走真实现）。
    monkeypatch.setattr(ep, "_read_pe_file_version", lambda path: (1, 0, 1, 0))
    try:
        yield server
    finally:
        server.stop()


def _default_target(tmp_path: Path) -> Path:
    return tmp_path / "localappdata" / "Vibelution" / "sandbox" / "wxc-exec.exe"


def _leftover_temp_dirs() -> set[str]:
    return {
        p.name
        for p in Path(tempfile.gettempdir()).glob(f"{ep._TEMP_DIR_PREFIX}*")
    }


def test_check_only_missing_reports_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    status = ep.ensure_executor_installed(allow_download=False)
    assert status.installed is False
    assert status.action == "missing"
    assert status.executor_path == str(_default_target(tmp_path))
    assert not _default_target(tmp_path).exists()


def test_already_present_skips_download(fake_release, tmp_path):
    target = _default_target(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(FAKE_EXE_BYTES)
    status = ep.ensure_executor_installed(allow_download=True)
    assert status.installed is True
    assert status.action == "already_present"
    assert status.zip_sha_ok is True
    assert status.exec_sha_ok is True
    assert status.version_ok is True
    assert fake_release.request_count == 0  # 合法在位时零网络请求
    assert target.read_bytes() == FAKE_EXE_BYTES


def test_download_install_happy_path_then_idempotent(fake_release, tmp_path):
    target = _default_target(tmp_path)
    assert not target.exists()
    status = ep.ensure_executor_installed(allow_download=True)
    assert status.installed is True
    assert status.action == "downloaded"
    assert status.zip_sha_ok and status.exec_sha_ok and status.version_ok
    assert target.is_file()
    assert target.read_bytes() == FAKE_EXE_BYTES
    assert fake_release.request_count == 1

    second = ep.ensure_executor_installed(allow_download=True)
    assert second.installed is True
    assert second.action == "already_present"
    assert fake_release.request_count == 1  # 幂等：第二次不下载


def test_zip_sha_mismatch_fails_and_cleans_up(fake_release, tmp_path, monkeypatch):
    # 篡改 zip 尺寸合法（只破内容）：pin 换成该 zip 尺寸，让 SHA 校验成为失败点。
    tampered = _build_zip_bytes(exe_bytes=FAKE_EXE_BYTES + b"\x00tampered")
    fake_release.payload = tampered
    monkeypatch.setattr(ep, "PINNED_ZIP_SIZE_BYTES", len(tampered))
    target = _default_target(tmp_path)
    before = _leftover_temp_dirs()
    status = ep.ensure_executor_installed(allow_download=True)
    assert status.installed is False
    assert status.action == "failed"
    assert status.zip_sha_ok is False
    assert "sha256 mismatch" in status.detail
    assert not target.exists()
    assert _leftover_temp_dirs() == before  # 临时目录已清理


def test_zip_slip_member_rejected(fake_release, tmp_path, monkeypatch):
    # 恶意 zip：夹带 ../evil.exe 逃逸成员；pin 换成该 zip 的真值以命中解压分支。
    evil_zip = _build_zip_bytes(extra_members=[("../evil.exe", b"evil payload")])
    fake_release.payload = evil_zip
    monkeypatch.setattr(ep, "PINNED_ZIP_SHA256", _sha256_bytes(evil_zip))
    monkeypatch.setattr(ep, "PINNED_ZIP_SIZE_BYTES", len(evil_zip))
    status = ep.ensure_executor_installed(allow_download=True)
    assert status.installed is False
    assert status.action == "failed"
    assert "unsafe zip member" in status.detail
    target = _default_target(tmp_path)
    assert not target.exists()
    # 相对路径逃逸目标不得出现。
    assert not (tmp_path / "localappdata" / "Vibelution" / "sandbox" / "evil.exe").exists()
    assert not (tmp_path / "evil.exe").exists()
    assert not (tmp_path / "localappdata" / "Vibelution" / "evil.exe").exists()


def test_zip_missing_target_member_rejected(fake_release, tmp_path, monkeypatch):
    # zip 校验通过但没有目标成员：拒绝安装（发布物布局漂移防线）。
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("other/readme.txt", b"not the executor")
    stranger_zip = buffer.getvalue()
    fake_release.payload = stranger_zip
    monkeypatch.setattr(ep, "PINNED_ZIP_SHA256", _sha256_bytes(stranger_zip))
    monkeypatch.setattr(ep, "PINNED_ZIP_SIZE_BYTES", len(stranger_zip))
    status = ep.ensure_executor_installed(allow_download=True)
    assert status.installed is False
    assert status.action == "failed"
    assert "does not contain the expected member" in status.detail
    assert not _default_target(tmp_path).exists()


def test_download_size_cap_aborts(fake_release, tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "PINNED_ZIP_SIZE_BYTES", 1)  # 声明 1 字节，服务给更多
    status = ep.ensure_executor_installed(allow_download=True, timeout_s=30)
    assert status.installed is False
    assert status.action == "failed"
    assert "size cap" in status.detail
    assert not _default_target(tmp_path).exists()
    assert fake_release.request_count == 1


def test_http_500_fails_without_side_effects(fake_release, tmp_path):
    fake_release.status = 500
    status = ep.ensure_executor_installed(allow_download=True, timeout_s=30)
    assert status.installed is False
    assert status.action == "failed"
    assert "500" in status.detail
    assert not _default_target(tmp_path).exists()


def test_connection_refused_fails_without_side_effects(tmp_path, monkeypatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(
        ep,
        "PINNED_ASSET_URL",
        f"http://127.0.0.1:{dead_port}/{ep.PINNED_ZIP_FILENAME}",
    )
    status = ep.ensure_executor_installed(allow_download=True, timeout_s=10)
    assert status.installed is False
    assert status.action == "failed"
    assert status.detail  # transport detail preserved
    assert not _default_target(tmp_path).exists()


def test_slow_server_times_out_without_side_effects(tmp_path, monkeypatch):
    zip_bytes = _build_zip_bytes()
    server = _FakeReleaseServer(zip_bytes, delay_s=3.0)
    server.start()
    try:
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
        monkeypatch.setattr(ep, "PINNED_ASSET_URL", server.url)
        monkeypatch.setattr(ep, "PINNED_ZIP_SHA256", _sha256_bytes(zip_bytes))
        monkeypatch.setattr(ep, "PINNED_ZIP_SIZE_BYTES", len(zip_bytes))
        monkeypatch.setattr(ep, "PINNED_EXECUTOR_SHA256", _sha256_bytes(FAKE_EXE_BYTES))
        monkeypatch.setattr(ep, "_read_pe_file_version", lambda path: (1, 0, 1, 0))
        status = ep.ensure_executor_installed(allow_download=True, timeout_s=1)
    finally:
        server.stop()
    assert status.installed is False
    assert status.action == "failed"
    assert not _default_target(tmp_path).exists()


def test_existing_corrupt_executor_not_overwritten(fake_release, tmp_path):
    target = _default_target(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"corrupted-executor-bytes")
    status = ep.ensure_executor_installed(allow_download=True)
    assert status.installed is False
    assert status.action == "failed"
    assert "no-overwrite" in status.detail
    assert target.read_bytes() == b"corrupted-executor-bytes"
    assert fake_release.request_count == 0  # 不覆盖，也不下载


def test_cli_check_json_smoke(fake_release, tmp_path, capsys):
    target = _default_target(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(FAKE_EXE_BYTES)
    exit_code = ep.main(["--check", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert exit_code == 0
    assert payload["installed"] is True
    assert payload["action"] == "already_present"
    assert payload["executor_path"] == str(target)
    for key in ("zip_sha_ok", "exec_sha_ok", "version_ok", "detail"):
        assert key in payload
    assert out.isascii()  # GBK 控制台安全


def test_cli_install_downloads_and_json_parsable(fake_release, tmp_path, capsys):
    exit_code = ep.main(["--install", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert exit_code == 0
    assert payload["action"] == "downloaded"
    assert payload["installed"] is True
    assert _default_target(tmp_path).read_bytes() == FAKE_EXE_BYTES

    check_code = ep.main(["--check", "--json"])
    check_payload = json.loads(capsys.readouterr().out)
    assert check_code == 0
    assert check_payload["action"] == "already_present"


def test_cli_check_missing_exits_nonzero_with_json(fake_release, capsys):
    exit_code = ep.main(["--check", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert exit_code == 1
    assert payload["installed"] is False
    assert payload["action"] == "missing"
    assert out.isascii()
