import keyring
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE_NAME = "AI_Chat_Client"


def _username(api_id: str) -> str:
    return f"api-key:{api_id}"


def get_api_key(api_id: str) -> str:
    try:
        return keyring.get_password(SERVICE_NAME, _username(api_id)) or ""
    except KeyringError as exc:
        raise RuntimeError("无法从系统钥匙串读取 API 密钥") from exc


def set_api_key(api_id: str, api_key: str) -> None:
    try:
        keyring.set_password(SERVICE_NAME, _username(api_id), api_key)
    except KeyringError as exc:
        raise RuntimeError("无法将 API 密钥保存到系统钥匙串") from exc


def delete_api_key(api_id: str) -> None:
    try:
        keyring.delete_password(SERVICE_NAME, _username(api_id))
    except PasswordDeleteError:
        pass
    except KeyringError as exc:
        raise RuntimeError("无法从系统钥匙串删除 API 密钥") from exc
