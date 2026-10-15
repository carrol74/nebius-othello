import json
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from nemothello.calibration import calibration_passed
from nemothello.policy import GENERATION_MODE, SYMBOLS, TEMPLATE_VERSION


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    pytrio_api_key: SecretStr
    pytrio_base_model: str = "Qwen/Qwen3.5-4B"
    pytrio_model_path: str = Field(min_length=1)
    pytrio_policy_mode: Literal["single-token-generation", "candidate-batch-1d"] = GENERATION_MODE
    pytrio_template_version: Literal[
        "othello-candidates-v1", "othello-rule-features-v1",
    ] = TEMPLATE_VERSION
    pytrio_calibration_path: Path = Path("../eval/results/serving-calibration.json")
    token_factory_api_key: SecretStr
    token_factory_base_url: str = "https://api.tokenfactory.nebius.com/v1"
    token_factory_model_id: str = Field(min_length=1)
    edax_executable: Path
    edax_eval_file: Path
    edax_version: str = Field(min_length=1)
    edax_level: int = Field(default=8, ge=1, le=10)
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
        for secret in (
            self.pytrio_api_key, self.token_factory_api_key, self.backend_service_token,
        ):
            if not secret.get_secret_value().strip():
                raise ValueError("平台密钥和服务凭据不能为空")
        report = json.loads(self.pytrio_calibration_path.read_text(encoding="utf-8"))
        source_key = ("source_sampler_path" if self.pytrio_policy_mode == GENERATION_MODE
                      else "source_model_path")
        if (not calibration_passed(report, self.pytrio_base_model, self.pytrio_policy_mode,
                                   self.pytrio_template_version)
                or report.get("symbols") != SYMBOLS
                or report.get(source_key) != self.pytrio_model_path
                or len(report.get("samples", [])) < 2):
            raise ValueError("服务启动需要当前 adapter、基座、模板与落子模式通过真实校准的报告")
