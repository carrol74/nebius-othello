from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    token_factory_api_key: SecretStr = SecretStr("")
    token_factory_base_url: str = "https://api.tokenfactory.nebius.com/v1"
    token_factory_model_id: str = ""
    edax_executable: Path
    edax_eval_file: Path
    edax_version: str = Field(min_length=1)
    edax_level: int = Field(default=8, ge=1, le=10)
    edax_opponent_level: int = Field(default=2, ge=1, le=10)
    edax_timeout_seconds: float = Field(default=60, gt=0)
    database_path: Path = Path("runtime/nemothello.sqlite3")
    backend_service_token: SecretStr
    task_limit_per_session: int = Field(default=3, ge=1)
    task_queue_limit: int = Field(default=16, ge=1)
    request_limit_per_session: int = Field(default=300, ge=1)
    request_limit_global: int = Field(default=1200, ge=1)
    request_limit_window_seconds: int = Field(default=60, ge=1)

    def validate_resources(self) -> None:
        for path in (self.edax_executable, self.edax_eval_file):
            if not path.is_file():
                raise ValueError(f"缺少必需文件：{path}")
        if not self.backend_service_token.get_secret_value().strip():
            raise ValueError("服务凭据不能为空")
        if (bool(self.token_factory_api_key.get_secret_value().strip())
                != bool(self.token_factory_model_id.strip())):
            raise ValueError("Token Factory 密钥与模型 ID 必须同时配置；均留空时仅复盘讲解不可用")
