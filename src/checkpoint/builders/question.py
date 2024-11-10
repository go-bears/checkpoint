import json
import shutil
from pathlib import Path
from string import Template

from ..constants import QUESTION_HTML_PATH, WORKSPACE_TEMPLATES_PATH
from ..models.question import CheckpointQuestion

QUESTION_INFO_PATH = Path("info.json")
PL_SERVER_PATH = Path("server.py")


class QuestionBuilder:
    def __init__(self, config: CheckpointQuestion):
        self.config = config
        self.builder_dir = Path(__file__).parent

    def build(self, image_name: str):
        """Build PrairieLearn question files"""
        # 1. Create workspaceTemplates directory
        WORKSPACE_TEMPLATES_PATH.mkdir(exist_ok=True)

        # 2. Generate question info.json
        info = self.config.generate_info_json(image_name)
        QUESTION_INFO_PATH.write_text(json.dumps(info, indent=2))

        # 3. Copy PrairieLearn server.py
        shutil.copy2(self.builder_dir / "pl_server.py.template", PL_SERVER_PATH)

        # 4. Generate question.html from template
        # We use string.Template instead of jinja2 here because the the generated
        # question.html will also be used by the PrairieLearn as a jinja2 template.
        # So {{ }} will conflict.
        template = Template((self.builder_dir / "question.html.j2").read_text())
        description = (
            f"Welcome to the {self.config.title}! This interactive tutorial will "
            "guide you through a series of missions. Complete each mission by "
            "following the instructions in the terminal below."
        )
        question_html = template.substitute(description=description)
        QUESTION_HTML_PATH.write_text(question_html)
