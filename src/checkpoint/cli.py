import uuid
from pathlib import Path
from typing import Any

import click
import docker
import regex
import yaml

from .builders.docker import DockerBuilder, check_docker_auth, raw_regex
from .builders.question import QuestionBuilder
from .constants import (
    DEFAULT_CONFIG_PATH,
    WORKSPACE_TEMPLATES_PATH,
)
from .models.question import CheckpointQuestion


@click.group()
def cli():
    """Checkpoint CLI tool for PrairieLearn"""
    pass


@cli.command()
def init():
    """Initialize a new checkpoint question"""
    if Path(DEFAULT_CONFIG_PATH).exists():
        if not click.confirm(f"{DEFAULT_CONFIG_PATH} already exists. Overwrite?"):
            return

    config: dict[str, Any] = {
        "uuid": str(uuid.uuid4()),
        "title": "My Checkpoint",
        "topic": "Topic",
        "tags": ["checkpoint"],
        "image": {
            "registry": "username",
            "name": "my-checkpoint",
            "base": "python:3.11-slim",
        },
        "runtime": {
            "program": "bash",
            "program_args": [],
            "packages": [],
            "setup_commands": [],
        },
        "flags": [
            {
                "title": "Example Flag",
                "prompt": "Your first checkpoint",
                "description": "Description of what to do",
                "listener": {"target": "output", "type": "regex", "match": "example"},
                "files": [],
            }
        ],
    }

    DEFAULT_CONFIG_PATH.write_text(yaml.dump(config, sort_keys=False))
    WORKSPACE_TEMPLATES_PATH.mkdir(exist_ok=True)

    click.echo(f"✨ Created {DEFAULT_CONFIG_PATH} template")
    click.echo("Next steps:")
    click.echo(f"1. Edit {DEFAULT_CONFIG_PATH}")
    click.echo("2. Add your source files")
    click.echo("3. Run: checkpoint deploy")


@cli.command()
def login():
    """Configure Docker registry credentials"""
    username = click.prompt("Docker Hub username")
    password = click.prompt("Docker Hub password", hide_input=True)

    client = docker.from_env()
    client.login(username=username, password=password)
    click.echo("✨ Successfully logged in to Docker Hub")


@cli.command()
def build():
    """Build Docker image only"""
    if not DEFAULT_CONFIG_PATH.exists():
        click.echo(f"❌ {DEFAULT_CONFIG_PATH} not found")
        click.echo("Run 'checkpoint init' to create a new checkpoint")
        return

    config = CheckpointQuestion.from_yaml(DEFAULT_CONFIG_PATH)
    image_name = config.image.get_full_name()

    click.echo(f"🔨 Building image: {image_name}")
    builder = DockerBuilder(config)
    image_id = builder.build(image_name)
    click.echo(f"✨ Built image: {image_id}")


@cli.command()
def push():
    """Push existing Docker image"""
    if not DEFAULT_CONFIG_PATH.exists():
        click.echo(f"❌ {DEFAULT_CONFIG_PATH} not found")
        return

    config = CheckpointQuestion.from_yaml(DEFAULT_CONFIG_PATH)
    image_name = config.image.get_full_name()
    username = config.image.registry
    if not check_docker_auth(username):
        click.echo(f"❌ Docker Hub credentials not found for {username!r}")
        return

    click.echo(f"🚀 Pushing image {image_name} to Docker Hub")
    builder = DockerBuilder(config)
    builder.push(image_name)
    click.echo("✨ Image pushed")


@cli.command()
def generate():
    """Generate question info.json only"""
    if not DEFAULT_CONFIG_PATH.exists():
        click.echo(f"❌ {DEFAULT_CONFIG_PATH} not found")
        click.echo("Run 'checkpoint init' to create a new checkpoint")
        return

    config = CheckpointQuestion.from_yaml(DEFAULT_CONFIG_PATH)
    image_name = config.image.get_full_name()

    click.echo("📝 Generating question files...")
    question_builder = QuestionBuilder(config)
    question_builder.build(image_name)

    click.echo("✨ Generated info.json and question.html")


@cli.command()
def deploy():
    """Full deployment: build, push and generate"""
    if not DEFAULT_CONFIG_PATH.exists():
        click.echo(f"❌ {DEFAULT_CONFIG_PATH} not found")
        click.echo("Run 'checkpoint init' to create a new checkpoint")
        return

    config = CheckpointQuestion.from_yaml(DEFAULT_CONFIG_PATH)
    image_name = config.image.get_full_name()
    username = config.image.registry
    if not check_docker_auth(username):
        click.echo(f"❌ Docker Hub credentials not found for {username!r}")
        return

    # 1. Build Docker image
    click.echo(f"🔨 Building image: {image_name}")
    docker_builder = DockerBuilder(config)
    docker_builder.build(image_name)

    # 2. Push to registry
    click.echo(f"🚀 Pushing image {image_name} to Docker Hub")
    docker_builder.push(image_name)

    # 3. Generate question files
    click.echo("📝 Generating question files...")
    question_builder = QuestionBuilder(config)
    question_builder.build(image_name)

    click.echo("✨ Deployment complete!")


@cli.command()
@click.argument("mission_number", type=int)
def validate(mission_number: int):
    """Interactive validation for specific mission regex pattern"""
    if not DEFAULT_CONFIG_PATH.exists():
        click.echo(f"❌ {DEFAULT_CONFIG_PATH} not found")
        return

    config = CheckpointQuestion.from_yaml(DEFAULT_CONFIG_PATH)

    if mission_number < 1 or mission_number > len(config.flags):
        click.echo("❌ Invalid mission number. Available missions:")
        for i, flag in enumerate(config.flags, 1):
            click.echo(f"{i}. {flag.title}")
        return

    flag = config.flags[mission_number - 1]
    pattern_str = raw_regex(flag.listener.match)
    pattern: str = eval(pattern_str)

    try:
        compiled_regex = regex.compile(pattern, regex.DOTALL)
        click.echo(f"\nMission {mission_number}: {flag.title}")
        click.echo(f"regex pattern: {compiled_regex.pattern}")
    except regex.error as e:
        click.echo(f"❌ Invalid regex pattern: {e}")
        return

    click.echo(
        "\nEnter output to validate (double empty line to submit, Ctrl+C to exit):"
    )
    while True:
        try:
            lines: list[str] = []
            empty_line_count = 0
            while True:
                line = input()
                if not line:
                    empty_line_count += 1
                    if empty_line_count >= 2:
                        break
                else:
                    empty_line_count = 0
                lines.append(line)

            if not lines:
                continue

            output = "\n".join(lines)
            match = compiled_regex.search(output, partial=True)
            if match:
                if match.partial:
                    click.echo("🔍 Partial match found.")
                    click.echo(f"Matched up to: {match.group()!r}")
                else:
                    click.echo("✅ Match!")
                    click.echo(f"Matched text: {match.group(0)!r}")
            else:
                click.echo("❌ No match")
        except KeyboardInterrupt:
            click.echo("\nExiting validation mode")
            break
        except regex.error as e:
            click.echo(f"❌ Regex error: {e}")
