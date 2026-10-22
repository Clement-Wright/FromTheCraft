import io
import struct
from types import SimpleNamespace

import pytest
from PIL import Image

from fromthecraft import ftd_textures as ftd


def serialized_header(path):
    path.write_bytes(struct.pack(">4IB3xIqqq", 0, 0, 22, 0, 0, 0, 48, 48, 0))


def fake_install(tmp_path, monkeypatch, *, width=2, resource_name="resources.assets.resS"):
    serialized_header(tmp_path / "globalgamemanagers")
    serialized_header(tmp_path / "resources.assets")
    raw = b"\x11\x22\x33\xff" * 4
    (tmp_path / "resources.assets.resS").write_bytes(b"prefix" + raw + b"suffix")
    calls = []

    class Texture:
        m_Width, m_Height = width, 2
        image_data = b""
        m_StreamData = SimpleNamespace(path=resource_name, offset=6, size=len(raw))

        @property
        def image(self):
            assert self.image_data == raw
            calls.append("decoded")
            return Image.frombytes("RGBA", (2, 2), raw)

    class Object:
        byte_size = 32

        def __init__(self, kind, value):
            self.type = SimpleNamespace(name=kind)
            self.value = value

        def read(self):
            calls.append(self.type.name)
            return self.value

    manager = SimpleNamespace(
        m_Container=[
            ("triplanar/metal/t_base_color", SimpleNamespace(m_FileID=1, m_PathID=23)),
            ("triplanar/other/t_base_color", SimpleNamespace(m_FileID=1, m_PathID=24)),
        ]
    )

    def reader(stream):
        return stream

    def asset(stream, name):
        calls.append(name)
        if name == "globalgamemanagers":
            return SimpleNamespace(
                objects={1: Object("ResourceManager", manager)},
                externals=[SimpleNamespace(path="resources.assets")],
            )
        return SimpleNamespace(
            objects={23: Object("Texture2D", Texture()), 24: Object("Texture2D", "must not decode")}
        )

    monkeypatch.setattr(ftd, "_unity_types", lambda: (asset, reader))
    monkeypatch.setattr(ftd, "_decode_texture", lambda texture: texture.image)
    return raw, calls


def test_exact_named_color_texture_uses_only_selected_resource_range(tmp_path, monkeypatch):
    raw, calls = fake_install(tmp_path, monkeypatch)
    key = "Triplanar/Metal/T_Base_Color.png"
    images = ftd.extract_base_colors(tmp_path, {key})
    assert set(images) == {key}
    with Image.open(io.BytesIO(images[key])) as image:
        assert image.size == (2, 2)
        assert image.tobytes() == raw
    assert calls.count("Texture2D") == 1
    assert calls.count("decoded") == 1
    assert "resources.assets" in calls


def test_texture_dimensions_are_checked_before_loading_streamed_pixels(tmp_path, monkeypatch):
    _, calls = fake_install(tmp_path, monkeypatch, width=2049)
    assert ftd.extract_base_colors(tmp_path, {"Triplanar/Metal/T_Base_Color.png"}) == {}
    assert "decoded" not in calls


def test_resource_paths_cannot_escape_the_game_data_directory(tmp_path, monkeypatch):
    _, calls = fake_install(tmp_path, monkeypatch, resource_name="../outside.resS")
    assert ftd.extract_base_colors(tmp_path, {"Triplanar/Metal/T_Base_Color.png"}) == {}
    assert "decoded" not in calls


def test_missing_optional_unitypy_is_a_clean_fallback(tmp_path, monkeypatch):
    def absent():
        raise ImportError("UnityPy unavailable")

    monkeypatch.setattr(ftd, "_unity_types", absent)
    assert ftd.extract_base_colors(tmp_path, {"Triplanar/Metal/T_Base_Color.png"}) == {}


@pytest.mark.parametrize(
    "name", ["../outside.png", "/outside.png", "C:/outside.png", "https://example.com/a.png"]
)
def test_untrusted_resource_references_are_rejected_before_parsing(tmp_path, monkeypatch, name):
    monkeypatch.setattr(ftd, "_unity_types", lambda: pytest.fail("must not import UnityPy"))
    assert ftd.extract_base_colors(tmp_path, {name}) == {}


def test_oversize_metadata_is_rejected_before_unitypy_parsing(tmp_path, monkeypatch):
    serialized_header(tmp_path / "globalgamemanagers")
    with (tmp_path / "globalgamemanagers").open("r+b") as stream:
        stream.seek(20)
        stream.write(struct.pack(">I", 128 * 1024**2 + 1))
    calls = []
    monkeypatch.setattr(ftd, "_unity_types", lambda: (lambda *a, **kw: calls.append(a), lambda x: x))
    assert ftd.extract_base_colors(tmp_path, {"Triplanar/Metal/T_Base_Color.png"}) == {}
    assert calls == []


def test_bounded_stream_never_allows_a_read_to_eof(tmp_path):
    path = tmp_path / "large.resS"
    path.write_bytes(b"12345678")
    with path.open("rb") as stream:
        bounded = ftd._BoundedStream(stream, 8)
        with pytest.raises(ValueError, match="bounded"):
            bounded.read()
        assert bounded.read(4) == b"1234"
        with pytest.raises(ValueError, match="budget"):
            bounded.read(5)


def test_texture_only_decoder_does_not_load_the_audio_runtime():
    import sys

    raw = bytes((255, 0, 0, 255)) * 4
    texture = SimpleNamespace(
        m_Width=2, m_Height=2, m_TextureFormat=4, object_reader=None, get_image_data=lambda: raw
    )
    before = "fmod_toolkit" in sys.modules
    image = ftd._decode_texture(texture)
    try:
        assert image.size == (2, 2)
        assert image.tobytes() == raw
        assert ("fmod_toolkit" in sys.modules) == before
    finally:
        image.close()
