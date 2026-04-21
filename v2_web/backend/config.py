"""Environment configuration via pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_token: str = ""
    llm_url: str = "http://127.0.0.1:8000"
    llm_model: str = "default"
    llm_api_key: str = ""
    output_dir: str = "output"
    projects_dir: str = ""
    tts_demo_dir: str = ""
    tts_voice: str = "despotism-doc.wav"
    tts_seed: int = 1
    tts_token_scale: float = 1.5

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
