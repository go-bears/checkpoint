from typing import Optional

from pydantic import BaseModel, Field


class DockerConfig(BaseModel):
    """Docker configuration"""

    base_image: str = "python:3.11-slim"
    workdir: str = "/app"
    user: str = "student"
    extra_packages: list[str] = Field(default_factory=list)
    extra_commands: list[str] = Field(default_factory=list)
    volumes: dict[str, str] = Field(default_factory=dict)

    registry: str
    image: str
    image_name: Optional[str] = None

    def get_image_name(self) -> str:
        if self.image_name:
            return self.image_name
        return f"{self.registry}/checkpoint-{self.image}"
