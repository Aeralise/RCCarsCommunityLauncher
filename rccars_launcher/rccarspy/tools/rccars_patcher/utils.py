from .models import PatchStruct

def convert_version_hex_2_str(hex_version):
    major, minor, patch = _split_hex_version(hex_version)
    return f"{major}.{minor}.{patch}"


def convert_version_hex_2_tuple(hex_version):
    major, minor, patch = _split_hex_version(hex_version)
    return (major, minor, patch)


def _split_hex_version(hex_version):
    major = (hex_version >> 16) & 0xFF
    minor = (hex_version >> 8) & 0xFF
    patch = hex_version & 0xFF
    return major, minor, patch


def get_patch_description_by_language_code(patch_data: PatchStruct, language_code: str) -> str:
    if len(patch_data.desc_list) > 0:
        for desc in patch_data.desc_list:
            if desc.language_code == language_code:
                return desc.data.decode(encoding="utf-8")
    return ""
